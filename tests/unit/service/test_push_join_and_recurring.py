"""Push for the two events it was still missing: a recurring template, and someone joining.

The invitation itself is deliberately absent from this file. An invitation is addressed to
somebody who has no account and therefore no registered device, so push cannot carry it —
email and WhatsApp remain the only channels that reach them. What *can* be pushed is the
other side of the same event: telling the people already in the group that someone arrived.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from template.domain.models.enums import NotificationType
from template.domain.models.member import Member
from template.service_layer.notification_service import NotificationService
from template.service_layer.push_service import push_body_for_join


def _member(member_id: int, name: str, preference=NotificationType.EMAIL) -> Member:
    return Member(
        id=member_id,
        name=name,
        telephone="5411111111",
        email=f"{name.lower()}@example.com",
        notification_preference=preference,
    )


def _ghost() -> Member:
    return Member(id=9, name="Tomi", telephone=None, email=None, notification_preference=NotificationType.EMAIL)


def _push(subscribed_ids):
    """A push repo where only `subscribed_ids` have a registered device."""
    repo = MagicMock()
    repo.has_any.side_effect = lambda member_id: member_id in subscribed_ids
    return repo


class TestJoinNotification:
    """Someone joins a group — the people already in it are the ones who want to know."""

    def test_pushes_to_subscribed_members_and_emails_the_rest(self):
        service = NotificationService()
        push_service = MagicMock()
        fran, guada = _member(1, "Fran"), _member(2, "Guada")

        with patch.object(service, "_send_email") as send_email:
            asyncio.run(
                service.notify_member_joined(
                    joiner=_member(3, "Nico"),
                    members=[fran, guada, _member(3, "Nico")],
                    group_name="Viaje",
                    group_id=8,
                    push_service=push_service,
                    push_repo=_push({1}),
                )
            )

        pushed_ids = [call.args[0] for call in push_service.send_to_member.call_args_list]
        assert pushed_ids == [1], "only the member with a device gets push"
        emailed = [call.args[0] for call in send_email.call_args_list]
        assert emailed == ["guada@example.com"], "everyone else keeps their email"

    def test_the_joiner_is_not_notified_about_their_own_arrival(self):
        service = NotificationService()
        push_service = MagicMock()
        nico = _member(3, "Nico")

        with patch.object(service, "_send_email"):
            asyncio.run(
                service.notify_member_joined(
                    joiner=nico,
                    members=[nico],
                    group_name="Viaje",
                    group_id=8,
                    push_service=push_service,
                    push_repo=_push({3}),
                )
            )

        push_service.send_to_member.assert_not_called()

    def test_ghost_members_are_never_contacted(self):
        """A ghost has no email — the EMAIL branch would otherwise call _send_email(None)."""
        service = NotificationService()

        with patch.object(service, "_send_email") as send_email:
            asyncio.run(
                service.notify_member_joined(
                    joiner=_member(3, "Nico"),
                    members=[_ghost()],
                    group_name="Viaje",
                    group_id=8,
                )
            )

        send_email.assert_not_called()

    def test_claiming_a_ghost_says_which_name_was_taken_over(self):
        """ "Nico se sumó" is confusing when the group has tracked him as "Tomi" all along."""
        assert push_body_for_join("Nico", claimed_name="Tomi") == "👋 Nico se sumó como Tomi"
        assert push_body_for_join("Nico") == "👋 Nico se sumó al grupo"


class TestRecurringTemplatePush:
    """The recurring-template event was the one CRUD notification still without a push branch."""

    @pytest.mark.parametrize("subscribed", [True, False])
    def test_push_replaces_email_only_for_subscribed_members(self, subscribed):
        service = NotificationService()
        push_service = MagicMock()
        template = MagicMock(payer_id=1, category="comida", description="Netflix", amount=5000.0)
        template.start_month, template.start_year = 3, 2026

        with (
            patch.object(service, "_send_email") as send_email,
            patch.object(service, "_is_involved_in_template", return_value=True),
            patch.object(service, "_send_whatsapp", new=AsyncMock()),
        ):
            asyncio.run(
                service.notify_recurring_template_created(
                    template=template,
                    members=[_member(2, "Guada")],
                    creator=_member(1, "Fran"),
                    member_service=MagicMock(**{"get_member_name_by_id.return_value": "Fran"}),
                    group_name="Casa",
                    group_id=4,
                    push_service=push_service,
                    push_repo=_push({2} if subscribed else set()),
                )
            )

        assert push_service.send_to_member.called is subscribed
        assert send_email.called is not subscribed
