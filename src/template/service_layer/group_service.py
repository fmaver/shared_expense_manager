"""Service for managing groups and memberships."""
from typing import Optional

from template.adapters.repositories import GroupRepository
from template.domain.models.group import Group, GroupStatus
from template.domain.models.member import Member


class GroupService:
    def __init__(self, repository: GroupRepository):
        self._repo = repository

    def create(self, name: str, creator_member_id: int) -> Group:
        """Create a new group and add the creator as a member."""
        group = self._repo.create(name)
        self._repo.add_member(group.id, creator_member_id)
        return group

    def get(self, group_id: int) -> Optional[Group]:
        return self._repo.get(group_id)

    def list_for_member(self, member_id: int) -> list[Group]:
        return self._repo.list_for_member(member_id)

    def list_members(self, group_id: int) -> list[Member]:
        return self._repo.list_members(group_id)

    def update_name(self, group_id: int, name: str) -> Group:
        return self._repo.update_name(group_id, name)

    def close(self, group_id: int) -> Group:
        return self._repo.set_status(group_id, GroupStatus.CLOSED)

    def delete(self, group_id: int) -> Group:
        return self._repo.set_status(group_id, GroupStatus.DELETED)

    def invite_by_email(self, group_id: int, email: str, member_repo) -> None:
        """Auto-accept invite if email matches an existing member."""
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
        return self._repo.is_member(group_id, member_id)
