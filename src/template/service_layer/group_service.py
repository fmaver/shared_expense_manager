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

    def create(self, name: str, creator_member_id: int) -> Group:
        """Create a new group and add the creator as a member."""
        group = self._repo.create(name)
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
        """Raise ValueError if the group is a personal group (single-member, no sharing allowed)."""
        group = self._repo.get(group_id)
        if group and group.group_type == GroupType.PERSONAL:
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

    def leave(self, group_id: int, member_id: int, member_balance: float) -> None:
        """Remove a member from the group. Blocked if they have a non-zero balance."""
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
            # Another concurrent request already created the personal group — return it.
            # The repository's session is in a bad state after IntegrityError; the commit
            # inside repo.create() means the session is closed/rolled back already.
            return self._repo.get_personal_for_owner(member_id)
