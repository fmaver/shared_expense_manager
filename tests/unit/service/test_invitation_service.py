"""Unit tests for InvitationService."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from template.domain.models.enums import InvitationChannel, InvitationStatus
from template.service_layer.invitation_service import InvitationService
from template.service_layer.whatsapp_invite_client import MockWhatsAppInviteClient


def _make_member(id_=1, name="Alice", email="alice@example.com", telephone=None, hashed_password="hash"):
    from template.domain.models.member import Member

    return Member(
        id=id_,
        name=name,
        telephone=telephone,
        email=email,
        hashed_password=hashed_password,
    )


def _make_stub(id_=99, name="Bob", email=None, telephone="541199999999"):
    from template.domain.models.member import Member

    return Member(id=id_, name=name, telephone=telephone, email=email, hashed_password=None)


def _make_invite_row(
    id_=10,
    group_id=1,
    inviter_id=1,
    invitee_member_id=99,
    channel=InvitationChannel.EMAIL,
    target="bob@example.com",
    token="tok123",
    status=InvitationStatus.PENDING,
):
    row = MagicMock()
    row.id = id_
    row.group_id = group_id
    row.inviter_id = inviter_id
    row.invitee_member_id = invitee_member_id
    row.channel = channel
    row.target = target
    row.token = token
    row.status = status
    row.created_at = datetime.utcnow()
    row.expires_at = datetime.utcnow() + timedelta(days=7)
    row.accepted_at = None
    row.accepted_by_member_id = None
    row.inviter = MagicMock(name="Alice")
    row.inviter.name = "Alice"
    row.group = MagicMock()
    row.group.name = "TestGroup"
    return row


@pytest.fixture
def mock_wpp_invite():
    return MockWhatsAppInviteClient()


@pytest.fixture
def service(mock_wpp_invite):
    member_repo = MagicMock()
    group_repo = MagicMock()
    invitation_repo = MagicMock()
    notification_service = MagicMock()
    # make group_repo.get() return a group-like object with a real name string
    group_repo.get.return_value = MagicMock(name_attr="TestGroup")
    group_repo.get.return_value.name = "TestGroup"
    return (
        InvitationService(
            member_repo=member_repo,
            group_repo=group_repo,
            invitation_repo=invitation_repo,
            notification_service=notification_service,
            wpp_invite_client=mock_wpp_invite,
            app_base_url="https://app.example.com",
        ),
        member_repo,
        group_repo,
        invitation_repo,
        notification_service,
        mock_wpp_invite,
    )


class TestCreateInvitationEmailChannel:
    def test_unknown_email_creates_stub_and_invitation(self, service):
        svc, member_repo, group_repo, invitation_repo, notification_service, mock_wpp = service
        inviter = _make_member(id_=1)
        stub = _make_stub(id_=99, email="bob@example.com", telephone=None)

        group_repo.is_member.side_effect = lambda gid, mid: mid == 1  # only inviter is member
        member_repo.get_member_by_email.return_value = None  # unknown email
        member_repo.create_stub.return_value = stub
        group_repo.add_member.return_value = None
        invitation_row = _make_invite_row(
            invitee_member_id=99, channel=InvitationChannel.EMAIL, target="bob@example.com"
        )
        invitation_repo.create.return_value = invitation_row

        with patch("template.service_layer.invitation_service.secrets.token_urlsafe", return_value="tok123"):
            result = svc.create_invitation(
                group_id=1,
                inviter=inviter,
                name="Bob",
                channel="email",
                contact="bob@example.com",
            )

        member_repo.create_stub.assert_called_once_with(name="Bob", email="bob@example.com", telephone=None)
        group_repo.add_member.assert_called_once_with(1, 99)
        invitation_repo.create.assert_called_once()
        # Email notification sent, WhatsApp not used
        notification_service.send_invitation_email.assert_called_once()
        assert len(mock_wpp.messages) == 0
        assert result.share_url is not None
        assert "tok123" in result.share_url

    def test_existing_member_not_in_group_creates_invitation_only(self, service):
        """Existing members are NOT added to the group at invite time — only when they accept."""
        svc, member_repo, group_repo, invitation_repo, notification_service, _ = service
        inviter = _make_member(id_=1)
        existing = _make_member(id_=5, email="carol@example.com")

        group_repo.is_member.side_effect = lambda gid, mid: mid == 1  # only inviter is member
        member_repo.get_member_by_email.return_value = existing
        invitation_row = _make_invite_row(invitee_member_id=5)
        invitation_repo.create.return_value = invitation_row

        with patch("template.service_layer.invitation_service.secrets.token_urlsafe", return_value="tok456"):
            svc.create_invitation(
                group_id=1, inviter=inviter, name="Carol", channel="email", contact="carol@example.com"
            )

        member_repo.create_stub.assert_not_called()
        group_repo.add_member.assert_not_called()  # added only at accept time
        invitation_repo.create.assert_called_once()

    def test_existing_stub_not_in_group_is_added_to_group(self, service):
        """Re-inviting an existing stub (email channel): add_member IS called immediately."""
        svc, member_repo, group_repo, invitation_repo, notification_service, _ = service
        inviter = _make_member(id_=1)
        existing_stub = _make_stub(id_=5, email="stub@example.com", telephone=None)

        group_repo.is_member.side_effect = lambda gid, mid: mid == 1  # only inviter is member
        member_repo.get_member_by_email.return_value = existing_stub
        invitation_row = _make_invite_row(invitee_member_id=5, target="stub@example.com")
        invitation_repo.create.return_value = invitation_row

        with patch("template.service_layer.invitation_service.secrets.token_urlsafe", return_value="tok"):
            svc.create_invitation(group_id=1, inviter=inviter, name="Stub", channel="email", contact="stub@example.com")

        member_repo.create_stub.assert_not_called()
        group_repo.add_member.assert_called_once_with(1, 5)

    def test_existing_member_already_in_group_raises(self, service):
        svc, member_repo, group_repo, invitation_repo, notification_service, _ = service
        inviter = _make_member(id_=1)
        existing = _make_member(id_=2, email="dave@example.com")

        group_repo.is_member.return_value = True  # everyone is already in the group
        member_repo.get_member_by_email.return_value = existing

        with pytest.raises(ValueError, match="already a member"):
            svc.create_invitation(group_id=1, inviter=inviter, name="Dave", channel="email", contact="dave@example.com")


class TestCreateInvitationPhoneChannel:
    def test_unknown_phone_creates_stub_and_whatsapp_mock(self, service):
        svc, member_repo, group_repo, invitation_repo, notification_service, mock_wpp = service
        inviter = _make_member(id_=1)
        stub = _make_stub(id_=99, telephone="541199999999")

        # Only inviter (id=1) is a group member; stub (id=99) is not yet.
        group_repo.is_member.side_effect = lambda gid, mid: mid == 1
        member_repo.get_member_by_phone.return_value = None
        member_repo.create_stub.return_value = stub
        invitation_row = _make_invite_row(channel=InvitationChannel.PHONE, target="541199999999")
        invitation_repo.create.return_value = invitation_row

        with patch("template.service_layer.invitation_service.secrets.token_urlsafe", return_value="tok789"):
            svc.create_invitation(group_id=1, inviter=inviter, name="Bob", channel="phone", contact="541199999999")

        member_repo.create_stub.assert_called_once_with(name="Bob", email=None, telephone="541199999999")
        assert len(mock_wpp.messages) == 1
        assert mock_wpp.messages[0]["to"] == "541199999999"

    def test_phone_normalisation_strips_extra_9(self, service):
        """Incoming phone 5491138718498 should be normalised to 541138718498 before lookup."""
        svc, member_repo, group_repo, invitation_repo, _, mock_wpp = service
        inviter = _make_member(id_=1)
        stub = _make_stub(id_=99, telephone="541138718498")

        group_repo.is_member.side_effect = lambda gid, mid: mid == 1
        member_repo.get_member_by_phone.return_value = None
        member_repo.create_stub.return_value = stub
        invitation_row = _make_invite_row(channel=InvitationChannel.PHONE, target="541138718498")
        invitation_repo.create.return_value = invitation_row

        with patch("template.service_layer.invitation_service.secrets.token_urlsafe", return_value="tok"):
            svc.create_invitation(group_id=1, inviter=inviter, name="Bob", channel="phone", contact="5491138718498")

        member_repo.get_member_by_phone.assert_called_once_with("541138718498")

    def test_existing_stub_phone_not_in_group_is_added_to_group(self, service):
        """Re-inviting an existing stub (phone channel): add_member IS called immediately."""
        svc, member_repo, group_repo, invitation_repo, _, mock_wpp = service
        inviter = _make_member(id_=1)
        existing_stub = _make_stub(id_=7, email=None, telephone="541199999999")

        group_repo.is_member.side_effect = lambda gid, mid: mid == 1
        member_repo.get_member_by_phone.return_value = existing_stub
        invitation_row = _make_invite_row(invitee_member_id=7, channel=InvitationChannel.PHONE, target="541199999999")
        invitation_repo.create.return_value = invitation_row

        with patch("template.service_layer.invitation_service.secrets.token_urlsafe", return_value="tok"):
            svc.create_invitation(group_id=1, inviter=inviter, name="Stub", channel="phone", contact="541199999999")

        member_repo.create_stub.assert_not_called()
        group_repo.add_member.assert_called_once_with(1, 7)

    def test_inviter_not_in_group_raises(self, service):
        svc, member_repo, group_repo, _, _, _ = service
        inviter = _make_member(id_=1)
        group_repo.is_member.return_value = False

        with pytest.raises(ValueError, match="not a member"):
            svc.create_invitation(group_id=1, inviter=inviter, name="Bob", channel="email", contact="bob@x.com")


class TestResolveToken:
    def test_pending_token_returns_resolve_response(self, service):
        svc, _, group_repo, invitation_repo, _, _ = service
        row = _make_invite_row(status=InvitationStatus.PENDING, channel=InvitationChannel.EMAIL, target="bob@x.com")
        row.invitee = _make_stub(id_=99, email="bob@x.com")
        invitation_repo.get_by_token.return_value = row

        result = svc.resolve_token("tok123")

        assert result.status == InvitationStatus.PENDING
        assert result.requires_password is True
        assert result.requires_email is False  # email channel → email already known
        assert result.known_email == "bob@x.com"
        assert result.is_existing_member is False

    def test_existing_member_resolve_shows_no_password_required(self, service):
        """Invitee already has an account — they log in, no new password needed."""
        svc, _, group_repo, invitation_repo, _, _ = service
        row = _make_invite_row(status=InvitationStatus.PENDING, channel=InvitationChannel.EMAIL, target="carol@x.com")
        row.invitee = _make_member(id_=5, email="carol@x.com")  # has hashed_password
        invitation_repo.get_by_token.return_value = row

        result = svc.resolve_token("tok123")

        assert result.is_existing_member is True
        assert result.requires_password is False
        assert result.requires_email is False

    def test_expired_token_returns_expired_status(self, service):
        svc, _, group_repo, invitation_repo, _, _ = service
        row = _make_invite_row(status=InvitationStatus.PENDING)
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        row.invitee = _make_stub(id_=99)
        invitation_repo.get_by_token.return_value = row

        result = svc.resolve_token("tok123")

        assert result.status == InvitationStatus.EXPIRED

    def test_nonexistent_token_raises(self, service):
        svc, _, _, invitation_repo, _, _ = service
        invitation_repo.get_by_token.return_value = None

        with pytest.raises(ValueError, match="not found"):
            svc.resolve_token("badtoken")


class TestAcceptInvitation:
    def test_accept_sets_password_and_email_on_stub(self, service):
        svc, member_repo, group_repo, invitation_repo, _, _ = service
        row = _make_invite_row(
            status=InvitationStatus.PENDING,
            channel=InvitationChannel.PHONE,
            invitee_member_id=99,
        )
        row.expires_at = datetime.utcnow() + timedelta(days=1)
        stub = _make_stub(id_=99, email=None)
        row.invitee = stub
        invitation_repo.get_by_token.return_value = row
        claimed = _make_stub(id_=99, email="bob@example.com")
        claimed.hashed_password = "newhash"
        member_repo.get_member_by_email.return_value = None  # email not yet taken
        member_repo.claim_stub.return_value = claimed
        invitation_repo.mark_accepted.return_value = row

        with patch("template.service_layer.invitation_service.pwd_context") as mock_ctx:
            mock_ctx.hash.return_value = "newhash"
            result = svc.accept_invitation(token="tok123", email="bob@example.com", password="secret123")

        member_repo.claim_stub.assert_called_once_with(99, "bob@example.com", "newhash")
        invitation_repo.mark_accepted.assert_called_once_with(row.id, 99)
        assert result.id == 99

    def test_accept_already_accepted_raises(self, service):
        svc, _, _, invitation_repo, _, _ = service
        row = _make_invite_row(status=InvitationStatus.ACCEPTED)
        row.expires_at = datetime.utcnow() + timedelta(days=1)
        row.invitee = _make_stub()
        invitation_repo.get_by_token.return_value = row

        with pytest.raises(ValueError, match="already accepted"):
            svc.accept_invitation(token="tok123", email="x@x.com", password="pass")

    def test_existing_member_accept_adds_to_group_without_password(self, service):
        """An existing member accepts via their JWT — no password required, just add to group."""
        svc, member_repo, group_repo, invitation_repo, _, _ = service
        existing = _make_member(id_=5, email="carol@x.com")
        row = _make_invite_row(status=InvitationStatus.PENDING, invitee_member_id=5)
        row.expires_at = datetime.utcnow() + timedelta(days=1)
        row.invitee = existing
        invitation_repo.get_by_token.return_value = row
        group_repo.is_member.return_value = False  # not yet in the group

        result = svc.accept_invitation(token="tok123", current_member=existing)

        group_repo.add_member.assert_called_once_with(row.group_id, existing.id)
        invitation_repo.mark_accepted.assert_called_once_with(row.id, existing.id)
        member_repo.claim_stub.assert_not_called()
        assert result.id == existing.id

    def test_stub_accept_without_password_raises(self, service):
        """Stubs must supply a password to create their account."""
        svc, _, _, invitation_repo, _, _ = service
        row = _make_invite_row(status=InvitationStatus.PENDING)
        row.expires_at = datetime.utcnow() + timedelta(days=1)
        row.invitee = _make_stub(email="bob@x.com")
        invitation_repo.get_by_token.return_value = row

        with pytest.raises(ValueError, match="Password is required"):
            svc.accept_invitation(token="tok123")


class TestRevokeInvitation:
    def test_revoke_removes_stub_from_group(self, service):
        """Stub was added to the group on invite — revoke removes them."""
        svc, member_repo, group_repo, invitation_repo, _, _ = service
        row = _make_invite_row(status=InvitationStatus.PENDING, invitee_member_id=99)
        invitation_repo.get_by_token.return_value = row
        group_repo.is_member.return_value = True  # stub is in the group

        svc.revoke_invitation(token="tok123", revoker_member_id=1)

        invitation_repo.revoke.assert_called_once_with(row.id)
        group_repo.remove_member.assert_called_once_with(row.group_id, 99)

    def test_revoke_existing_member_skips_remove_when_not_in_group(self, service):
        """Existing member was never added to the group — revoke skips remove_member."""
        svc, member_repo, group_repo, invitation_repo, _, _ = service
        row = _make_invite_row(status=InvitationStatus.PENDING, invitee_member_id=5)
        invitation_repo.get_by_token.return_value = row
        group_repo.is_member.return_value = False  # existing member not yet in the group

        svc.revoke_invitation(token="tok123", revoker_member_id=1)

        invitation_repo.revoke.assert_called_once_with(row.id)
        group_repo.remove_member.assert_not_called()
