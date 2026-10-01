"""WhatsApp is off unless WHATSAPP_ENABLED says otherwise.

WhatsApp started charging per conversation. With the switch off, notifications go push → mail
(a WHATSAPP preference is read as EMAIL), invitations skip WhatsApp, and the preference can no
longer be chosen. NONE is still respected. With the switch on, the old behaviour comes back
untouched — that is what makes it a switch and not a removal.
"""

import asyncio
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from template.adapters.orm import MemberModel
from template.domain.models.category import Category
from template.domain.models.enums import (
    InvitationChannel,
    NotificationType,
    PaymentType,
)
from template.domain.models.member import Member
from template.domain.models.models import Expense
from template.domain.models.split import EqualSplit
from template.domain.schemas.member import MemberCreate, MemberUpdate
from template.service_layer.auth_service import AuthService
from template.service_layer.invitation_service import InvitationService
from template.service_layer.notification_service import NotificationService
from template.service_layer.whatsapp_invite_client import (
    MetaWhatsAppInviteClient,
    MockWhatsAppInviteClient,
)
from template.service_layer.whatsapp_service import enviar_mensaje_whatsapp
from template.service_layer.whatsapp_switch import whatsapp_enabled

CREATOR = Member(id=1, name="Fran", telephone="5411111111", email="fran@example.com")
WPP_SEND = "template.service_layer.notification_service.enviar_mensaje_whatsapp"


@pytest.fixture(autouse=True)
def _switch_unset(monkeypatch):
    """Every test starts from the production default: the variable is not set at all."""
    monkeypatch.delenv("WHATSAPP_ENABLED", raising=False)


def _expense() -> Expense:
    cat = Category()
    cat.name = "comida"
    return Expense(
        description="pizza",
        amount=300.0,
        date=date(2026, 9, 1),
        category=cat,
        payer_id=1,
        payment_type=PaymentType.DEBIT,
        split_strategy=EqualSplit(),
    )


def _member(preference: NotificationType, email: str | None = "guada@example.com") -> Member:
    return Member(id=2, name="Guada", telephone="5422222222", email=email, notification_preference=preference)


def _member_service() -> MagicMock:
    ms = MagicMock()
    ms.get_member_name_by_id.return_value = "Fran"
    ms.get_member.return_value = CREATOR
    ms.get_last_wpp_chat_time.return_value = None
    return ms


def _push(subscribed: bool) -> MagicMock:
    push = MagicMock()
    push.send_if_subscribed.return_value = subscribed
    return push


def _notify_created(service, member, push_service=None):
    asyncio.run(
        service.notify_expense_created(
            _expense(), [CREATOR, member], CREATOR, _member_service(), group_name="Casa", push_service=push_service
        )
    )


class TestSwitch:
    def test_unset_means_off(self):
        assert whatsapp_enabled() is False

    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
    def test_truthy_values_turn_it_on(self, monkeypatch, value):
        monkeypatch.setenv("WHATSAPP_ENABLED", value)
        assert whatsapp_enabled() is True

    @pytest.mark.parametrize("value", ["false", "0", "", "no"])
    def test_anything_else_is_off(self, monkeypatch, value):
        monkeypatch.setenv("WHATSAPP_ENABLED", value)
        assert whatsapp_enabled() is False

    def test_the_low_level_sender_refuses_to_call_meta(self, monkeypatch):
        """Last line of defence: even a caller that forgot to check never reaches Meta."""
        monkeypatch.setenv("WHATSAPP_TOKEN", "t")
        monkeypatch.setenv("WHATSAPP_URL", "https://graph.example/messages")
        with patch("template.service_layer.whatsapp_service.requests.post") as post:
            result = enviar_mensaje_whatsapp("{}")
        post.assert_not_called()
        assert result.get("status_code") != 200

    def test_the_invite_client_refuses_to_call_meta(self):
        with patch("template.service_layer.whatsapp_invite_client.enviar_mensaje_whatsapp") as send:
            MetaWhatsAppInviteClient().send_invitation("5422222222", "Fran", "Casa", "https://x/invite/t")
        send.assert_not_called()


class TestNotificationsWithSwitchOff:
    @pytest.mark.parametrize(
        "notify",
        ["created", "updated", "deleted", "settlement", "unsettle"],
    )
    def test_whatsapp_preference_is_sent_by_mail(self, notify):
        service = NotificationService()
        member = _member(NotificationType.WHATSAPP)
        ms = _member_service()
        with patch.object(service, "_send_email") as send_email, patch(WPP_SEND) as send_wpp:
            if notify == "created":
                _notify_created(service, member)
            elif notify == "updated":
                asyncio.run(service.notify_expense_updated(_expense(), _expense(), CREATOR, [CREATOR, member], ms))
            elif notify == "deleted":
                asyncio.run(service.notify_expense_deleted(_expense(), CREATOR, [CREATOR, member], ms))
            elif notify == "settlement":
                asyncio.run(service.notify_settlement(2026, 9, CREATOR.id, [CREATOR, member], ms, "Casa"))
            else:
                asyncio.run(service.notify_unsettle(2026, 9, CREATOR.id, [CREATOR, member], ms, "Casa"))

        send_wpp.assert_not_called()
        send_email.assert_called_once()
        assert send_email.call_args.args[0] == "guada@example.com"

    def test_recurring_template_whatsapp_preference_is_sent_by_mail(self):
        service = NotificationService()
        template = MagicMock()
        template.split_strategy.type = "equal"
        template.split_strategy.participant_ids = None
        template.category = "servicios"
        template.amount = 100.0
        template.start_month, template.start_year = 9, 2026
        with patch.object(service, "_send_email") as send_email, patch(WPP_SEND) as send_wpp:
            asyncio.run(
                service.notify_recurring_template_created(
                    template, [CREATOR, _member(NotificationType.WHATSAPP)], CREATOR, _member_service(), "Casa"
                )
            )
        send_wpp.assert_not_called()
        send_email.assert_called_once()

    def test_whatsapp_preference_without_email_gets_nothing(self):
        service = NotificationService()
        with patch.object(service, "_send_email") as send_email, patch(WPP_SEND) as send_wpp:
            _notify_created(service, _member(NotificationType.WHATSAPP, email=None))
        send_wpp.assert_not_called()
        send_email.assert_not_called()

    def test_whatsapp_preference_without_email_gets_nothing_on_edit(self):
        """_broadcast's EMAIL branch did not check for an address; WHATSAPP now lands there."""
        service = NotificationService()
        member = _member(NotificationType.WHATSAPP, email=None)
        with patch.object(service, "_send_email") as send_email, patch(WPP_SEND) as send_wpp:
            asyncio.run(service.notify_expense_deleted(_expense(), CREATOR, [CREATOR, member], _member_service()))
        send_wpp.assert_not_called()
        send_email.assert_not_called()

    def test_none_preference_still_gets_nothing(self):
        service = NotificationService()
        with patch.object(service, "_send_email") as send_email, patch(WPP_SEND) as send_wpp:
            _notify_created(service, _member(NotificationType.NONE))
        send_wpp.assert_not_called()
        send_email.assert_not_called()

    @pytest.mark.parametrize("preference", [NotificationType.EMAIL, NotificationType.WHATSAPP, NotificationType.NONE])
    def test_a_push_subscription_wins_over_any_preference(self, preference):
        """Granting push permission makes push the channel: no mail, no WhatsApp on top."""
        service = NotificationService()
        push = _push(subscribed=True)
        with patch.object(service, "_send_email") as send_email, patch(WPP_SEND) as send_wpp:
            _notify_created(service, _member(preference), push_service=push)
        push.send_if_subscribed.assert_called_once()
        send_email.assert_not_called()
        send_wpp.assert_not_called()

    def test_without_a_subscription_push_falls_back_to_mail(self):
        service = NotificationService()
        push = _push(subscribed=False)
        with patch.object(service, "_send_email") as send_email, patch(WPP_SEND) as send_wpp:
            _notify_created(service, _member(NotificationType.WHATSAPP), push_service=push)
        push.send_if_subscribed.assert_called_once()
        send_email.assert_called_once()
        send_wpp.assert_not_called()


class TestNotificationsWithSwitchOn:
    def test_whatsapp_preference_goes_to_whatsapp_again(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ENABLED", "true")
        service = NotificationService()
        with (
            patch.object(service, "_send_email") as send_email,
            patch(WPP_SEND, return_value={"status_code": 200}) as send_wpp,
        ):
            _notify_created(service, _member(NotificationType.WHATSAPP))
        send_email.assert_not_called()
        send_wpp.assert_called_once()
        assert "expense_notification" in send_wpp.call_args.args[0]


def _invitation_service(invitee: Member, wpp, subscribed: bool = False):
    member_repo, group_repo = MagicMock(), MagicMock()
    group_repo.get.return_value.name = "Casa"
    group_repo.is_member.side_effect = lambda group_id, member_id: member_id == CREATOR.id
    member_repo.get_member_by_phone.return_value = None
    member_repo.create_stub.return_value = invitee
    invitation_repo = MagicMock()
    notification_service = MagicMock()
    service = InvitationService(
        member_repo=member_repo,
        group_repo=group_repo,
        invitation_repo=invitation_repo,
        notification_service=notification_service,
        wpp_invite_client=wpp,
        app_base_url="https://app.example.com",
        push_service=_push(subscribed),
    )
    return service, invitation_repo, notification_service


class TestInvitations:
    PHONE_ONLY = Member(id=5, name="Nico", telephone="541199999999", email=None)

    def _invite(self, service):
        return service.create_invitation(
            group_id=1, inviter=CREATOR, name="Nico", channel=InvitationChannel.PHONE.value, contact="541199999999"
        )

    def test_phone_only_invitee_gets_no_whatsapp_but_the_invitation_exists(self):
        wpp = MockWhatsAppInviteClient()
        service, invitation_repo, notifications = _invitation_service(self.PHONE_ONLY, wpp)

        response = self._invite(service)

        assert wpp.messages == []
        notifications.send_invitation_email.assert_not_called()
        invitation_repo.create.assert_called_once()
        assert response.share_url.startswith("https://app.example.com/invite/")

    def test_with_the_switch_on_the_phone_invite_goes_by_whatsapp(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ENABLED", "true")
        wpp = MockWhatsAppInviteClient()
        service, _, _ = _invitation_service(self.PHONE_ONLY, wpp)

        self._invite(service)

        assert len(wpp.messages) == 1


class TestPreference:
    def _auth(self, member: Member) -> tuple[AuthService, MagicMock]:
        auth = AuthService.__new__(AuthService)
        repo = MagicMock()
        repo.update.return_value = member
        repo.get_member_by_email.return_value = None
        auth.member_repository = repo
        auth.db = MagicMock()
        return auth, repo

    def test_choosing_whatsapp_is_rejected_while_off(self):
        auth, repo = self._auth(CREATOR)
        with pytest.raises(ValueError, match="WhatsApp"):
            auth.update_member(CREATOR, MemberUpdate(notification_preference=NotificationType.WHATSAPP))
        repo.update.assert_not_called()

    def test_choosing_email_is_fine(self):
        auth, repo = self._auth(CREATOR)
        auth.update_member(CREATOR, MemberUpdate(notification_preference=NotificationType.EMAIL))
        repo.update.assert_called_once()

    def test_other_profile_edits_are_not_blocked(self):
        """A member whose stored preference is WHATSAPP can still rename themselves."""
        auth, repo = self._auth(CREATOR)
        auth.update_member(CREATOR, MemberUpdate(name="Francisco"))
        repo.update.assert_called_once()

    def test_choosing_whatsapp_works_when_on(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ENABLED", "true")
        auth, repo = self._auth(CREATOR)
        auth.update_member(CREATOR, MemberUpdate(notification_preference=NotificationType.WHATSAPP))
        repo.update.assert_called_once()


class TestDefaultPreference:
    def test_orm_default_is_email(self):
        column = MemberModel.__table__.c.notification_preference
        assert column.default.arg == NotificationType.EMAIL
        assert column.server_default is None, "a server default would need a migration"

    def test_registration_default_is_email(self):
        member = MemberCreate(name="Nico", email="nico@example.com", password="x")
        assert member.notification_preference == NotificationType.EMAIL
