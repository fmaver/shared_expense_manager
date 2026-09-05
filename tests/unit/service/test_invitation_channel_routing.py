"""How an invitation chooses its channel.

The channel used to be decided by how the inviter typed the contact — an email address meant
email, a phone number meant WhatsApp. It is now decided by what actually reaches the invitee:
push if they have a registered device, then email, and WhatsApp only when neither exists.

Push is rarely available here and that is expected, not a bug: a subscription lives on an
installed app tied to an account, and most invitees have no account yet. It pays off for the
people who are already Jirens users — invited into a second group, say.
"""

from unittest.mock import MagicMock

import pytest

from template.domain.models.enums import InvitationChannel
from template.domain.models.member import Member
from template.service_layer.invitation_service import InvitationService
from template.service_layer.whatsapp_invite_client import MockWhatsAppInviteClient

INVITER = Member(id=1, name="Fran", telephone=None, email="fran@example.com", hashed_password="h")


def _build(invitee: Member, subscribed: bool):
    """An InvitationService whose repos resolve to `invitee`, with or without a push device."""
    member_repo, group_repo, invitation_repo = MagicMock(), MagicMock(), MagicMock()
    notification_service, wpp = MagicMock(), MockWhatsAppInviteClient()
    push_service = MagicMock()

    group_repo.get.return_value.name = "Viaje"
    group_repo.is_member.side_effect = lambda group_id, member_id: member_id == INVITER.id
    member_repo.get_member_by_email.return_value = invitee
    member_repo.get_member_by_phone.return_value = invitee
    push_service.send_if_subscribed.return_value = subscribed

    service = InvitationService(
        member_repo=member_repo,
        group_repo=group_repo,
        invitation_repo=invitation_repo,
        notification_service=notification_service,
        wpp_invite_client=wpp,
        app_base_url="https://app.example.com",
        push_service=push_service,
    )
    return service, notification_service, wpp, push_service


def _invite(service, channel, contact):
    service.create_invitation(group_id=1, inviter=INVITER, name="Nico", channel=channel, contact=contact)


class TestChannelRouting:
    def test_a_registered_device_wins_over_email(self):
        invitee = Member(id=2, name="Nico", telephone=None, email="nico@example.com", hashed_password="h")
        service, notifications, wpp, push = _build(invitee, subscribed=True)

        _invite(service, InvitationChannel.EMAIL.value, "nico@example.com")

        push.send_if_subscribed.assert_called_once()
        assert push.send_if_subscribed.call_args.args[0] == 2
        notifications.send_invitation_email.assert_not_called()
        assert wpp.messages == []

    def test_email_when_there_is_no_device(self):
        invitee = Member(id=2, name="Nico", telephone=None, email="nico@example.com", hashed_password="h")
        service, notifications, wpp, push = _build(invitee, subscribed=False)

        _invite(service, InvitationChannel.EMAIL.value, "nico@example.com")

        notifications.send_invitation_email.assert_called_once()
        push.send_to_member.assert_not_called()
        assert wpp.messages == []

    def test_a_phone_invite_still_prefers_email_when_the_person_has_one(self):
        """The old behaviour sent WhatsApp purely because the inviter typed a number."""
        invitee = Member(id=2, name="Nico", telephone="541199999999", email="nico@example.com", hashed_password="h")
        service, notifications, wpp, _ = _build(invitee, subscribed=False)

        _invite(service, InvitationChannel.PHONE.value, "541199999999")

        notifications.send_invitation_email.assert_called_once()
        assert wpp.messages == [], "WhatsApp is the last resort, not the phone-shaped default"

    def test_whatsapp_only_when_there_is_nothing_else(self):
        """A brand-new person invited by number: no account, no device, no email."""
        invitee = Member(id=2, name="Nico", telephone="541199999999", email=None, hashed_password=None)
        service, notifications, wpp, push = _build(invitee, subscribed=False)

        _invite(service, InvitationChannel.PHONE.value, "541199999999")

        assert len(wpp.messages) == 1
        notifications.send_invitation_email.assert_not_called()
        push.send_to_member.assert_not_called()

    def test_push_is_skipped_entirely_when_it_is_not_configured(self):
        """No VAPID keys on this deployment — invitations must still go out."""
        invitee = Member(id=2, name="Nico", telephone=None, email="nico@example.com", hashed_password="h")
        member_repo, group_repo, invitation_repo = MagicMock(), MagicMock(), MagicMock()
        notifications, wpp = MagicMock(), MockWhatsAppInviteClient()
        group_repo.get.return_value.name = "Viaje"
        group_repo.is_member.side_effect = lambda group_id, member_id: member_id == INVITER.id
        member_repo.get_member_by_email.return_value = invitee

        service = InvitationService(
            member_repo=member_repo,
            group_repo=group_repo,
            invitation_repo=invitation_repo,
            notification_service=notifications,
            wpp_invite_client=wpp,
            app_base_url="https://app.example.com",
        )
        _invite(service, InvitationChannel.EMAIL.value, "nico@example.com")

        notifications.send_invitation_email.assert_called_once()
