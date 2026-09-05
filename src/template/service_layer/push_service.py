"""Web push delivery, and deciding which channel a member gets.

Push only reaches members who added the app to their home screen — that is a platform rule on
iOS, not a choice. So push *replaces* the channel for those members rather than adding to it,
and everyone else keeps receiving email. That fallback is the point: it is what stops anyone
losing notifications entirely when WhatsApp free-form replies end.
"""

import json
import logging
import os
from typing import Optional, Union

from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from template.adapters.orm import MemberModel
from template.adapters.repositories import PushSubscriptionRepository
from template.domain.models.enums import NotificationType

logger = logging.getLogger(__name__)

PUSH_CHANNEL = "push"

# A push service answers 404/410 when the subscription no longer exists — the browser was
# uninstalled, or permission was revoked. Anything else is transient and the device is kept.
_DEAD_SUBSCRIPTION_STATUSES = (404, 410)


def resolve_channel(member: MemberModel, push_repo: PushSubscriptionRepository) -> Union[str, NotificationType]:
    """Return the single channel this member should be notified through.

    NONE wins over everything: it is an explicit opt-out, and owning a registered device does
    not undo it. Otherwise push takes precedence when the member has one, and the member's
    existing preference is the fallback for everyone else.
    """
    if member.notification_preference == NotificationType.NONE:
        return NotificationType.NONE
    if push_repo.has_any(member.id):
        return PUSH_CHANNEL
    return member.notification_preference


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
