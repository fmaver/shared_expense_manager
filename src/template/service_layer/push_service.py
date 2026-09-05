"""Web push delivery, and deciding which channel a member gets.

Push only reaches members who added the app to their home screen — that is a platform rule on
iOS, not a choice. So push *replaces* the channel for those members rather than adding to it,
and everyone else keeps receiving email. That fallback is the point: it is what stops anyone
losing notifications entirely when WhatsApp free-form replies end.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional, Union

from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from template.adapters.orm import MemberModel
from template.adapters.repositories import PushSubscriptionRepository
from template.domain.models.category import Category
from template.domain.models.enums import NotificationType
from template.domain.models.formatters import format_amount_es, month_name_es

logger = logging.getLogger(__name__)

PUSH_CHANNEL = "push"


@dataclass(frozen=True)
class PushMessage:
    """One notification's text and destination.

    The same three strings go to every recipient of an event, so callers build this once per
    notification rather than once per member — that also keeps the (possibly expensive) text
    construction out of the loop for members who are not on push at all.
    """

    title: str
    body: str
    url: str


# A push service answers 404/410 when the subscription no longer exists — the browser was
# uninstalled, or permission was revoked. Anything else is transient and the device is kept.
_DEAD_SUBSCRIPTION_STATUSES = (404, 410)


def resolve_channel(member: MemberModel, push_repo: PushSubscriptionRepository) -> Union[str, NotificationType]:
    """Return the single channel this member should be notified through.

    An active subscription wins, including over a NONE preference. Registering a device means
    tapping "turn on notifications" and granting a browser permission prompt — that *is* an
    explicit opt-in, and it would be perverse for a stale preference to silently veto it.
    NONE also happens to be the column default, so honouring it first would have made push
    look broken for most accounts.

    NONE still governs the other channels: a member with no subscription and a NONE preference
    is notified by nothing, exactly as before. Turning push off removes the subscription and
    falls straight back to that.
    """
    if push_repo.has_any(member.id):
        return PUSH_CHANNEL
    return member.notification_preference


def push_body_for_expense(expense, creator, member_service) -> str:
    """Two lines: what happened, then what it was for.

    A lock-screen notification is skimmed, not studied, so this carries only what decides
    whether to open the app. The amount goes on the first line rather than after the
    description: descriptions are free text, and a long one used to push the separator and the
    amount onto a second line where the "·" was left stranded at the start.

    The emoji is the expense's own category — 🛒 for supermercado, ✈️ for viajes — so it says
    something at a glance instead of decorating every notification identically.
    """
    payer = member_service.get_member(expense.payer_id) if expense.payer_id else None
    who = payer.name if payer else creator.name
    category = expense.category.name if expense.category else ""
    emoji = Category.get_category_emoji(category)
    symbol = "US$ " if getattr(expense, "currency", "ARS") == "USD" else "$"
    amount = f"{symbol}{format_amount_es(expense.amount)}"

    verb = "registró un préstamo de" if category.lower() == "prestamo" else "cargó"
    headline = f"{emoji} {who} {verb} {amount}".strip()

    description = (expense.description or "").strip()
    return f"{headline}\n{description}" if description else headline


def push_url_for_expense(expense, group_id) -> str:
    """Deep link straight to this expense.

    The month has to travel with it: an expense dated in another month is not on the screen
    the group opens to, so landing on the group alone would leave the user hunting for the
    very thing the notification was about. `?year=&month=` is the convention the app already
    uses; `expense` opens its detail.
    """
    base = f"/groups/{group_id}" if group_id else "/groups"
    if not group_id or expense.date is None:
        return base
    return f"{base}?year={expense.date.year}&month={expense.date.month}&expense={expense.id}"


def push_body_for_recurring_template(template, creator) -> str:
    """A new recurring template, in the shape the expense notification already uses."""
    return f"🔁 {creator.name} creó un recurrente de ${format_amount_es(template.amount)}\n{template.description}"


def push_body_for_join(joiner_name: str, claimed_name: Optional[str] = None) -> str:
    """Someone joined the group.

    When they claimed a ghost, the claimed name is the useful half: the group has been
    tracking that person as "Tomi" for weeks, so "Nico se sumó" alone reads like a stranger.
    """
    if claimed_name and claimed_name != joiner_name:
        return f"👋 {joiner_name} se sumó como {claimed_name}"
    return f"👋 {joiner_name} se sumó al grupo"


def push_body_for_invitation(inviter_name: str) -> str:
    """An invitation to a group. The group name is the title, so it is not repeated here."""
    return f"👋 {inviter_name} te invitó a este grupo"


def push_body_for_settlement(month: int, year: int) -> str:
    """A settled month, in the few words a lock screen shows."""
    return f"✅ Cuentas de {month_name_es(month)} {year} saldadas"


def push_body_for_unsettle(month: int, year: int) -> str:
    """A reopened month."""
    return f"↩️ {month_name_es(month)} {year} fue reabierto"


def push_body_for_occasion(settled: bool) -> str:
    """A one-time group closed or reopened as a whole — it has no month to name."""
    return "✅ Cuentas del grupo saldadas" if settled else "↩️ El grupo se reabrió"


def push_url_for_month(group_id, year: int, month: int) -> str:
    """Link to a specific month of a group, using the app's ?year=&month= convention."""
    if not group_id:
        return "/groups"
    return f"/groups/{group_id}?year={year}&month={month}"


class PushService:
    """Sends web push notifications to a member's registered devices."""

    def __init__(self, session: Session):
        self._repo = PushSubscriptionRepository(session)

    def send_to_member(self, member_id: int, title: str, body: str, url: str) -> None:
        """Deliver to every device this member registered.

        Never raises: a notification failing must not fail the action that triggered it. Each
        device is attempted independently, so one stale laptop subscription cannot cost the
        user the notification on their phone.
        """
        private_key = os.getenv("VAPID_PRIVATE_KEY")
        if not private_key:
            logger.warning("VAPID_PRIVATE_KEY not set — web push disabled")
            return

        payload = json.dumps({"title": title, "body": body, "url": url})
        claims = {"sub": os.getenv("VAPID_SUBJECT", "mailto:noreply@jirens.app")}

        for subscription in self._repo.list_for_member(member_id):
            try:
                webpush(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                    },
                    data=payload,
                    vapid_private_key=private_key,
                    vapid_claims=dict(claims),
                )
            except WebPushException as exc:
                self._handle_failure(subscription.endpoint, exc)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Push delivery failed for %s: %s", subscription.endpoint, exc)

    def send_if_subscribed(self, member_id: int, title: str, body: str, url: str) -> bool:
        """Deliver only if this member has a registered device. True when it was sent.

        Callers that route between channels need the answer, not just the send: they fall
        through to email when it is False. The subscription lookup uses this service's own
        repository, so a caller needs no second push dependency.
        """
        if not self._repo.has_any(member_id):
            return False
        self.send_to_member(member_id, title, body, url)
        return True

    def _handle_failure(self, endpoint: str, exc: WebPushException) -> None:
        """Drop the device only when the push service says it is gone."""
        status = _status_of(exc)
        if status in _DEAD_SUBSCRIPTION_STATUSES:
            logger.info("Push subscription gone (%s) — removing %s", status, endpoint)
            self._repo.delete_by_endpoint(endpoint)
            return
        logger.warning("Push delivery failed (%s) for %s — keeping the subscription", status, endpoint)


def _status_of(exc: WebPushException) -> Optional[int]:
    """HTTP status carried by a WebPushException, when it has one."""
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) if response is not None else None
