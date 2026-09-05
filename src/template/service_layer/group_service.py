"""Service for managing groups and memberships."""

from typing import Optional

from sqlalchemy.exc import IntegrityError

from template.adapters.repositories import GroupRepository
from template.domain.models.group import Group, GroupStatus, GroupType
from template.domain.models.member import Member


class GroupService:
    """Application service for managing groups and memberships."""

    def __init__(self, repository: GroupRepository):
        """Initialize group service."""
        self._repo = repository

    def create(self, name: str, creator_member_id: int, group_type: GroupType = GroupType.REGULAR) -> Group:
        """Create a new group and add the creator as a member.

        The type is fixed at creation: converting between ongoing and one-time would have to
        decide which month a trip's spending belongs to, or collapse months that may already
        be settled.
        """
        group = self._repo.create(name, group_type=group_type)
        self._repo.add_member(group.id, creator_member_id)
        return group

    def get(self, group_id: int) -> Optional[Group]:
        """Return a group by ID."""
        return self._repo.get(group_id)

    def list_for_member(self, member_id: int) -> list[Group]:
        """Return all active groups the member belongs to."""
        return self._repo.list_for_member(member_id)

    def list_members(self, group_id: int) -> list[Member]:
        """Return all members of a group."""
        return self._repo.list_members(group_id)

    def update_name(self, group_id: int, name: str) -> Group:
        """Rename a group."""
        return self._repo.update_name(group_id, name)

    def _assert_not_personal(self, group_id: int) -> None:
        """Raise ValueError if the group is personal or does not exist."""
        group = self._repo.get(group_id)
        if not group:
            raise ValueError(f"Group {group_id} not found")
        if group.group_type == GroupType.PERSONAL:
            raise ValueError(f"Operation not allowed on personal group {group_id}")

    def close(self, group_id: int) -> Group:
        """Close a group."""
        self._assert_not_personal(group_id)
        return self._repo.set_status(group_id, GroupStatus.CLOSED)

    def delete(self, group_id: int) -> Group:
        """Soft-delete a group."""
        self._assert_not_personal(group_id)
        return self._repo.set_status(group_id, GroupStatus.DELETED)

    def invite_by_email(self, group_id: int, email: str, member_repo) -> None:
        """Auto-accept invite if email matches an existing member."""
        self._assert_not_personal(group_id)
        member = member_repo.get_member_by_email(email)
        if not member:
            raise ValueError(f"No member found with email {email}")
        self._repo.add_member(group_id, member.id)

    def add_named_member(self, group_id: int, name: str, member_repo) -> Member:
        """Add a member identified only by name — a "ghost".

        The member has no contact details and no password, so nothing is ever sent to them.
        They can later claim the account through the group's join link.
        """
        self._assert_not_personal(group_id)
        member = member_repo.create_stub(name=name)
        self._repo.add_member(group_id, member.id)
        return member

    def archive(self, group_id: int, member_id: int, outstanding_balance: float) -> None:
        """Archive a group for one member.

        Per member: the group stays exactly as it is for everyone else. Blocked while the
        member still owes or is owed something — the same rule as leaving, since putting a
        group away should not hide a debt.
        """
        self._assert_not_personal(group_id)
        if abs(outstanding_balance) > 0.01:
            raise ValueError("Cannot archive a group with an outstanding balance. Settle first.")
        self._repo.set_archived(group_id, member_id, archived=True)

    def unarchive(self, group_id: int, member_id: int) -> None:
        """Bring an archived group back into the member's list."""
        self._repo.set_archived(group_id, member_id, archived=False)

    def list_archived_for_member(self, member_id: int) -> list[Group]:
        """Return the groups this member has archived."""
        return self._repo.list_for_member(member_id, archived=True)

    def refresh_archived_state(self, group_id: int, expense_repo) -> None:
        """Unarchive the group for any member whose balance is no longer zero.

        This is what makes archiving safe to silence: debt cannot accumulate behind an
        archived group, because acquiring debt is exactly what brings it back. Called after an
        expense changes — the only moment a balance can move.
        """
        archived_ids = self._repo.list_archived_member_ids(group_id)
        if not archived_ids:
            return
        shares = expense_repo.get_all_monthly_shares(group_id)
        for member_id in archived_ids:
            key = str(member_id)
            outstanding = max(
                (abs(share.balances.get(key, 0.0)) for share in shares.values() if not share.is_settled),
                default=0.0,
            )
            if outstanding > 0.01:
                self._repo.set_archived(group_id, member_id, archived=False)

    def leave(self, group_id: int, member_id: int, member_balance: float) -> None:
        """Remove a member from the group. Blocked if they have a non-zero balance."""
        self._assert_not_personal(group_id)
        if abs(member_balance) > 0.01:
            raise ValueError("Cannot leave group with an outstanding balance. Settle first.")
        self._repo.remove_member(group_id, member_id)

    def is_member(self, group_id: int, member_id: int) -> bool:
        """Return True if the member belongs to the group."""
        return self._repo.is_member(group_id, member_id)

    def get_or_create_personal_group(self, member_id: int) -> Group:
        """Return the member's personal group, creating it if it doesn't exist yet."""
        existing = self._repo.get_personal_for_owner(member_id)
        if existing:
            return existing
        try:
            group = self._repo.create(
                name="Personal",
                group_type=GroupType.PERSONAL,
                owner_member_id=member_id,
            )
            self._repo.add_member(group.id, member_id)
            return group
        except IntegrityError:
            # Another concurrent request already created the personal group.
            # Must rollback the aborted transaction before the session can be reused.
            self._repo.session.rollback()
            return self._repo.get_personal_for_owner(member_id)
