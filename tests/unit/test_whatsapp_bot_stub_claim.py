"""Unit tests for the WhatsApp bot stub-claim flow (_handle_stub_claim)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from template.entrypoint.whatsapp_bot import _handle_stub_claim


def _make_invitation(token="tok123", inviter_name="Alice", group_name="TestGroup"):
    inv = MagicMock()
    inv.token = token
    inv.inviter = MagicMock()
    inv.inviter.name = inviter_name
    inv.group = MagicMock()
    inv.group.name = group_name
    return inv


def _make_group(name="TestGroup"):
    g = MagicMock()
    g.name = name
    return g


def _make_wpp_client():
    client = MagicMock()
    client.send_message = MagicMock()
    return client


def _initial_estado():
    return {"estado": "inicial", "expense_data": {}}


def _confirm_estado():
    return {"estado": "onboarding_claim_confirm", "expense_data": {}}


class TestFirstContact:
    """Stub member messages for the first time — should receive confirm prompt."""

    def test_sends_confirmation_prompt_with_group_and_inviter(self):
        wpp_client = _make_wpp_client()
        invitation = _make_invitation(token="tok123", inviter_name="Alice", group_name="Casa")
        member_repo = MagicMock()
        member_repo.get.return_value.name = "Juan"

        with (
            patch("template.entrypoint.whatsapp_bot.InvitationRepository") as MockInvRepo,
            patch("template.entrypoint.whatsapp_bot.GroupRepository") as MockGroupRepo,
        ):
            MockInvRepo.return_value.latest_pending_for_member.return_value = invitation
            MockGroupRepo.return_value.list_for_member.return_value = [_make_group("Casa")]

            nuevo_estado = _handle_stub_claim(
                text="hola",
                number="54111",
                message_id="msg1",
                member_id=99,
                estado=_initial_estado(),
                db=MagicMock(),
                member_repo=member_repo,
                wpp_client=wpp_client,
            )

        assert nuevo_estado["estado"] == "onboarding_claim_confirm"
        # The body of the sent text message should mention the group, inviter, and invitee's own name
        call_args = [str(c) for c in wpp_client.send_message.call_args_list]
        combined = " ".join(call_args)
        assert "Alice" in combined
        assert "Casa" in combined
        assert "Juan" in combined

    def test_sets_state_to_confirm(self):
        wpp_client = _make_wpp_client()
        member_repo = MagicMock()
        member_repo.get.return_value.name = "Juan"
        with (
            patch("template.entrypoint.whatsapp_bot.InvitationRepository") as MockInvRepo,
            patch("template.entrypoint.whatsapp_bot.GroupRepository") as MockGroupRepo,
        ):
            MockInvRepo.return_value.latest_pending_for_member.return_value = _make_invitation()
            MockGroupRepo.return_value.list_for_member.return_value = [_make_group()]

            estado = _handle_stub_claim(
                text="cualquier cosa",
                number="54111",
                message_id="msg1",
                member_id=99,
                estado=_initial_estado(),
                db=MagicMock(),
                member_repo=member_repo,
                wpp_client=wpp_client,
            )

        assert estado["estado"] == "onboarding_claim_confirm"

    def test_no_invitation_uses_generic_inviter_name(self):
        wpp_client = _make_wpp_client()
        member_repo = MagicMock()
        member_repo.get.return_value.name = "Juan"
        with (
            patch("template.entrypoint.whatsapp_bot.InvitationRepository") as MockInvRepo,
            patch("template.entrypoint.whatsapp_bot.GroupRepository") as MockGroupRepo,
        ):
            MockInvRepo.return_value.latest_pending_for_member.return_value = None
            MockGroupRepo.return_value.list_for_member.return_value = [_make_group("Familia")]

            _handle_stub_claim(
                text="hola",
                number="54111",
                message_id="msg1",
                member_id=99,
                estado=_initial_estado(),
                db=MagicMock(),
                member_repo=member_repo,
                wpp_client=wpp_client,
            )

        call_args = " ".join(str(c) for c in wpp_client.send_message.call_args_list)
        # Should still send something mentioning the group name
        assert "Familia" in call_args


class TestConfirmYes:
    """User replies SI — should mark phone verified and send claim URL."""

    @pytest.mark.parametrize("yes_text", ["si", "SI", "Sí", "sí", "yes", "s"])
    def test_si_marks_phone_verified(self, yes_text):
        wpp_client = _make_wpp_client()
        member_repo = MagicMock()
        invitation = _make_invitation(token="tok_abc")

        with (
            patch("template.entrypoint.whatsapp_bot.InvitationRepository") as MockInvRepo,
            patch("template.entrypoint.whatsapp_bot.GroupRepository"),
            patch.dict("os.environ", {"APP_BASE_URL": "https://app.example.com"}),
        ):
            MockInvRepo.return_value.latest_pending_for_member.return_value = invitation

            _handle_stub_claim(
                text=yes_text,
                number="54111",
                message_id="msg1",
                member_id=99,
                estado=_confirm_estado(),
                db=MagicMock(),
                member_repo=member_repo,
                wpp_client=wpp_client,
            )

        member_repo.mark_phone_verified.assert_called_once_with(99)

    def test_si_sends_claim_url_with_token(self):
        wpp_client = _make_wpp_client()
        invitation = _make_invitation(token="tok_abc")

        with (
            patch("template.entrypoint.whatsapp_bot.InvitationRepository") as MockInvRepo,
            patch("template.entrypoint.whatsapp_bot.GroupRepository"),
            patch.dict("os.environ", {"APP_BASE_URL": "https://app.example.com"}),
        ):
            MockInvRepo.return_value.latest_pending_for_member.return_value = invitation

            _handle_stub_claim(
                text="si",
                number="54111",
                message_id="msg1",
                member_id=99,
                estado=_confirm_estado(),
                db=MagicMock(),
                member_repo=MagicMock(),
                wpp_client=wpp_client,
            )

        sent = " ".join(str(c) for c in wpp_client.send_message.call_args_list)
        assert "https://app.example.com/invite/tok_abc" in sent

    def test_si_no_invitation_sends_register_url(self):
        wpp_client = _make_wpp_client()

        with (
            patch("template.entrypoint.whatsapp_bot.InvitationRepository") as MockInvRepo,
            patch("template.entrypoint.whatsapp_bot.GroupRepository"),
            patch.dict("os.environ", {"APP_BASE_URL": "https://app.example.com"}),
        ):
            MockInvRepo.return_value.latest_pending_for_member.return_value = None

            _handle_stub_claim(
                text="si",
                number="54111",
                message_id="msg1",
                member_id=99,
                estado=_confirm_estado(),
                db=MagicMock(),
                member_repo=MagicMock(),
                wpp_client=wpp_client,
            )

        sent = " ".join(str(c) for c in wpp_client.send_message.call_args_list)
        assert "https://app.example.com/register" in sent

    def test_si_resets_state_to_inicial(self):
        with (
            patch("template.entrypoint.whatsapp_bot.InvitationRepository") as MockInvRepo,
            patch("template.entrypoint.whatsapp_bot.GroupRepository"),
        ):
            MockInvRepo.return_value.latest_pending_for_member.return_value = _make_invitation()

            estado = _handle_stub_claim(
                text="si",
                number="54111",
                message_id="msg1",
                member_id=99,
                estado=_confirm_estado(),
                db=MagicMock(),
                member_repo=MagicMock(),
                wpp_client=_make_wpp_client(),
            )

        assert estado["estado"] == "inicial"


class TestConfirmNo:
    """User replies NO — should clear state and send a polite message."""

    @pytest.mark.parametrize("no_text", ["no", "NO", "No", "n"])
    def test_no_resets_state(self, no_text):
        wpp_client = _make_wpp_client()

        with (
            patch("template.entrypoint.whatsapp_bot.InvitationRepository") as MockInvRepo,
            patch("template.entrypoint.whatsapp_bot.GroupRepository"),
        ):
            MockInvRepo.return_value.latest_pending_for_member.return_value = None

            estado = _handle_stub_claim(
                text=no_text,
                number="54111",
                message_id="msg1",
                member_id=99,
                estado=_confirm_estado(),
                db=MagicMock(),
                member_repo=MagicMock(),
                wpp_client=wpp_client,
            )

        assert estado["estado"] == "inicial"

    def test_no_does_not_mark_phone_verified(self):
        member_repo = MagicMock()

        with (
            patch("template.entrypoint.whatsapp_bot.InvitationRepository") as MockInvRepo,
            patch("template.entrypoint.whatsapp_bot.GroupRepository"),
        ):
            MockInvRepo.return_value.latest_pending_for_member.return_value = None

            _handle_stub_claim(
                text="no",
                number="54111",
                message_id="msg1",
                member_id=99,
                estado=_confirm_estado(),
                db=MagicMock(),
                member_repo=member_repo,
                wpp_client=_make_wpp_client(),
            )

        member_repo.mark_phone_verified.assert_not_called()

    def test_no_sends_polite_message(self):
        wpp_client = _make_wpp_client()

        with (
            patch("template.entrypoint.whatsapp_bot.InvitationRepository") as MockInvRepo,
            patch("template.entrypoint.whatsapp_bot.GroupRepository"),
        ):
            MockInvRepo.return_value.latest_pending_for_member.return_value = None

            _handle_stub_claim(
                text="no",
                number="54111",
                message_id="msg1",
                member_id=99,
                estado=_confirm_estado(),
                db=MagicMock(),
                member_repo=MagicMock(),
                wpp_client=wpp_client,
            )

        sent = " ".join(str(c) for c in wpp_client.send_message.call_args_list)
        assert "Avisale" in sent or "avisale" in sent


class TestUnrecognisedReply:
    """Unrecognised reply while in onboarding_claim_confirm — should re-prompt."""

    def test_garbage_input_stays_in_confirm_state(self):
        with (
            patch("template.entrypoint.whatsapp_bot.InvitationRepository") as MockInvRepo,
            patch("template.entrypoint.whatsapp_bot.GroupRepository"),
        ):
            MockInvRepo.return_value.latest_pending_for_member.return_value = None

            estado = _handle_stub_claim(
                text="quizas",
                number="54111",
                message_id="msg1",
                member_id=99,
                estado=_confirm_estado(),
                db=MagicMock(),
                member_repo=MagicMock(),
                wpp_client=_make_wpp_client(),
            )

        assert estado["estado"] == "onboarding_claim_confirm"

    def test_garbage_input_does_not_mark_phone_verified(self):
        member_repo = MagicMock()

        with (
            patch("template.entrypoint.whatsapp_bot.InvitationRepository") as MockInvRepo,
            patch("template.entrypoint.whatsapp_bot.GroupRepository"),
        ):
            MockInvRepo.return_value.latest_pending_for_member.return_value = None

            _handle_stub_claim(
                text="tal vez",
                number="54111",
                message_id="msg1",
                member_id=99,
                estado=_confirm_estado(),
                db=MagicMock(),
                member_repo=member_repo,
                wpp_client=_make_wpp_client(),
            )

        member_repo.mark_phone_verified.assert_not_called()
