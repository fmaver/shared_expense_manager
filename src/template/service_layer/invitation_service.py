"""Invitation service — manages group invitations and stub-member onboarding."""

import secrets
from datetime import datetime, timedelta
from typing import Optional

from passlib.context import CryptContext

from template.adapters.repositories import GroupJoinLinkRepository, GroupRepository, InvitationRepository, MemberRepository
from template.domain.models.enums import InvitationChannel, InvitationStatus
from template.domain.models.member import Member
from template.domain.schemas.group import (
    GroupJoinLinkResponse,
    GroupJoinResolveResponse,
    InvitationAcceptRequest,
    InvitationResolveResponse,
    InvitationResponse,
)
from template.service_layer.whatsapp_invite_client import MockWhatsAppInviteClient, WhatsAppInviteClient

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_INVITATION_EXPIRY_DAYS = 7


def _normalise_phone(phone: str) -> str:
    """Strip the extra '9' from Argentine numbers (5491xxxxxxxx → 541xxxxxxxx)."""
    if phone.startswith("549") and len(phone) > 10:
        return "54" + phone[3:]
    return phone


class InvitationService:
    def __init__(
        self,
        member_repo: MemberRepository,
        group_repo: GroupRepository,
        invitation_repo: InvitationRepository,
        notification_service,
        wpp_invite_client: WhatsAppInviteClient,
        app_base_url: str,
    ):
        self._member_repo = member_repo
        self._group_repo = group_repo
        self._invitation_repo = invitation_repo
        self._notification_service = notification_service
        self._wpp_invite = wpp_invite_client
        self._base_url = app_base_url.rstrip("/")

    def create_invitation(
        self,
        group_id: int,
        inviter: Member,
        name: str,
        channel: str,
        contact: str,
    ) -> InvitationResponse:
        """Create an invitation, stub the member if needed, and dispatch the notification."""
        if not self._group_repo.is_member(group_id, inviter.id):
            raise ValueError(f"Member {inviter.id} is not a member of group {group_id}")

        group = self._group_repo.get(group_id)
        if not group:
            raise ValueError(f"Group {group_id} not found")

        inv_channel = InvitationChannel(channel)
        invitee_member: Optional[Member] = None

        if inv_channel == InvitationChannel.EMAIL:
            existing = self._member_repo.get_member_by_email(contact)
            if existing:
                if self._group_repo.is_member(group_id, existing.id):
                    raise ValueError(f"Member with email {contact} is already a member of this group")
                invitee_member = existing
            else:
                invitee_member = self._member_repo.create_stub(name=name, email=contact, telephone=None)
            self._group_repo.add_member(group_id, invitee_member.id)

        elif inv_channel == InvitationChannel.PHONE:
            normalised = _normalise_phone(contact)
            existing = self._member_repo.get_member_by_phone(normalised)
            if existing:
                if self._group_repo.is_member(group_id, existing.id):
                    raise ValueError(f"Member with phone {normalised} is already a member of this group")
                invitee_member = existing
            else:
                invitee_member = self._member_repo.create_stub(name=name, email=None, telephone=normalised)
            self._group_repo.add_member(group_id, invitee_member.id)
            contact = normalised

        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(days=_INVITATION_EXPIRY_DAYS)
        claim_url = f"{self._base_url}/invite/{token}"

        invitation_row = self._invitation_repo.create(
            group_id=group_id,
            inviter_id=inviter.id,
            channel=inv_channel,
            token=token,
            expires_at=expires_at,
            invitee_member_id=invitee_member.id if invitee_member else None,
            target=contact,
        )

        # Dispatch notification
        if inv_channel == InvitationChannel.EMAIL and invitee_member and invitee_member.email:
            self._notification_service.send_invitation_email(
                to_email=invitee_member.email,
                inviter_name=inviter.name,
                group_name=group.name,
                claim_url=claim_url,
            )
        elif inv_channel == InvitationChannel.PHONE and invitee_member and invitee_member.telephone:
            self._wpp_invite.send_invitation(
                to_phone=invitee_member.telephone,
                inviter_name=inviter.name,
                group_name=group.name,
                claim_url=claim_url,
            )

        return InvitationResponse(
            id=invitation_row.id,
            group_id=invitation_row.group_id,
            group_name=group.name,
            inviter_name=inviter.name,
            channel=inv_channel,
            target=contact,
            status=InvitationStatus.PENDING,
            created_at=invitation_row.created_at,
            expires_at=invitation_row.expires_at,
            share_url=claim_url,
        )

    def list_invitations(self, group_id: int) -> list[InvitationResponse]:
        """Return pending invitations for a group."""
        rows = self._invitation_repo.list_for_group(group_id, status=InvitationStatus.PENDING)
        result = []
        for row in rows:
            claim_url = f"{self._base_url}/invite/{row.token}"
            result.append(
                InvitationResponse(
                    id=row.id,
                    group_id=row.group_id,
                    group_name=row.group.name if row.group else None,
                    inviter_name=row.inviter.name if row.inviter else None,
                    channel=row.channel,
                    target=row.target,
                    status=row.status,
                    created_at=row.created_at,
                    expires_at=row.expires_at,
                    share_url=claim_url,
                )
            )
        return result

    def resolve_token(self, token: str) -> InvitationResolveResponse:
        """Return metadata about an invitation token (public, no auth required)."""
        row = self._invitation_repo.get_by_token(token)
        if not row:
            raise ValueError(f"Invitation token not found")

        now = datetime.utcnow()
        if row.status == InvitationStatus.PENDING and row.expires_at < now:
            row.status = InvitationStatus.EXPIRED

        invitee = row.invitee if hasattr(row, "invitee") else None
        known_email = invitee.email if invitee else None
        known_phone = invitee.telephone if invitee else None
        known_name = invitee.name if invitee else None

        requires_email = row.channel == InvitationChannel.PHONE and not known_email
        requires_password = True  # always need to set a password

        return InvitationResolveResponse(
            group_name=row.group.name if row.group else "",
            inviter_name=row.inviter.name if row.inviter else "",
            known_name=known_name,
            known_email=known_email,
            known_phone=known_phone,
            requires_email=requires_email,
            requires_password=requires_password,
            status=row.status,
        )

    def accept_invitation(
        self,
        token: str,
        password: str,
        email: Optional[str] = None,
        current_member: Optional[Member] = None,
    ) -> Member:
        """Claim the stub account, set credentials, and mark the invitation accepted."""
        row = self._invitation_repo.get_by_token(token)
        if not row:
            raise ValueError("Invitation token not found")
        if row.status != InvitationStatus.PENDING:
            raise ValueError(f"Invitation already {row.status.value}")
        if row.expires_at < datetime.utcnow():
            raise ValueError("Invitation has expired")

        invitee = row.invitee if hasattr(row, "invitee") else None
        if not invitee:
            raise ValueError("Invitation has no associated member")

        if current_member:
            # Logged-in user accepting — just add to group (no stub claim)
            if current_member.email and invitee.email and current_member.email != invitee.email:
                raise ValueError("Logged-in account email does not match the invited email")
            self._group_repo.add_member(row.group_id, current_member.id)
            self._invitation_repo.mark_accepted(row.id, current_member.id)
            return current_member

        # Unauthenticated accept: claim the stub
        resolve_email = email or invitee.email
        if not resolve_email:
            raise ValueError("Email is required to claim this invitation")

        # Check email not already taken by another member
        existing = self._member_repo.get_member_by_email(resolve_email)
        if existing and existing.id != invitee.id:
            raise ValueError(f"Email {resolve_email} is already registered")

        password_hash = pwd_context.hash(password)
        claimed = self._member_repo.claim_stub(invitee.id, resolve_email, password_hash)
        self._invitation_repo.mark_accepted(row.id, claimed.id)
        return claimed

    def revoke_invitation(self, token: str, revoker_member_id: int) -> None:
        """Revoke a pending invitation and clean up an orphan stub if applicable."""
        row = self._invitation_repo.get_by_token(token)
        if not row:
            raise ValueError("Invitation token not found")

        self._invitation_repo.revoke(row.id)

        # Remove the stub from the group and delete if orphaned
        if row.invitee_member_id:
            self._group_repo.remove_member(row.group_id, row.invitee_member_id)
            other_groups = self._group_repo.list_for_member(row.invitee_member_id)
            invitee = row.invitee if hasattr(row, "invitee") else None
            if not other_groups and invitee and not invitee.hashed_password:
                # Orphan stub — nothing else to do (leave the member row, avoid cascade issues).
                # A future cleanup job can prune these.
                pass


class GroupJoinLinkService:
    def __init__(
        self,
        group_repo: GroupRepository,
        member_repo: MemberRepository,
        join_link_repo: GroupJoinLinkRepository,
        app_base_url: str,
    ):
        self._group_repo = group_repo
        self._member_repo = member_repo
        self._join_link_repo = join_link_repo
        self._base_url = app_base_url.rstrip("/")

    def get_or_create_link(self, group_id: int, member_id: int) -> GroupJoinLinkResponse:
        """Return the existing join link for a group, creating one if it doesn't exist."""
        token = secrets.token_urlsafe(32)
        row = self._join_link_repo.get_or_create(group_id, member_id, token)
        return GroupJoinLinkResponse(
            token=row.token,
            url=f"{self._base_url}/join/{row.token}",
            created_at=row.created_at,
        )

    def rotate_link(self, group_id: int, member_id: int) -> GroupJoinLinkResponse:
        """Invalidate the current join link and issue a new token."""
        new_token = secrets.token_urlsafe(32)
        row = self._join_link_repo.rotate(group_id, new_token)
        return GroupJoinLinkResponse(
            token=row.token,
            url=f"{self._base_url}/join/{row.token}",
            created_at=row.created_at,
        )

    def resolve_join_token(self, token: str) -> GroupJoinResolveResponse:
        """Return group info for a join link (public, no auth)."""
        row = self._join_link_repo.get_by_token(token)
        if not row:
            raise ValueError("Join link not found or expired")
        return GroupJoinResolveResponse(
            group_name=row.group.name,
            inviter_name=row.created_by.name,
        )

    def register_and_join(self, token: str, name: str, email: str, password: str) -> Member:
        """Register a brand-new member and add them to the group for this join link."""
        row = self._join_link_repo.get_by_token(token)
        if not row:
            raise ValueError("Join link not found or expired")

        existing = self._member_repo.get_member_by_email(email)
        if existing:
            raise ValueError(f"Email {email} is already registered")

        password_hash = pwd_context.hash(password)
        new_member = self._member_repo.create_stub(name=name, email=email)
        self._member_repo.claim_stub(new_member.id, email, password_hash)
        self._group_repo.add_member(row.group_id, new_member.id)
        return self._member_repo.get(new_member.id)
