"""Member service module."""

from datetime import datetime
from typing import List, Optional, Dict

from template.adapters.repositories import MemberRepository
from template.domain.models.member import Member


class MemberService:
    """Member service."""

    def __init__(self, member_repository: MemberRepository):
        """Initialize member service."""
        self._member_repository = member_repository

    def get_member(self, member_id: int) -> Optional[Member]:
        """Get a member by ID."""
        return self._member_repository.get(member_id)

    def get_member_by_phone(self, phone: str) -> Optional[Member]:
        """Get a member by phone number."""
        return self._member_repository.get_member_by_phone(phone)

    def list_members(self) -> List[Member]:
        """List all members."""
        return self._member_repository.list()

    def update_last_wpp_chat(self, phone: str) -> Optional[Member]:
        """Update the last WhatsApp chat datetime for a member."""
        return self._member_repository.update_last_wpp_chat(phone)
    
    def get_last_wpp_chat_time(self, member: Member) -> Optional[datetime]:
        """Get the last WhatsApp chat datetime for a member."""
        return self._member_repository.get_last_wpp_chat_time(member)

    def get_member_names(self) -> Dict[int, str]:
        """Get a dictionary mapping member IDs to their names."""
        members = self.list_members()
        return {member.id: member.name for member in members if member.id is not None}
        
    def get_member_id_by_name(self, name: str) -> Optional[int]:
        """Get member ID by their name (case-insensitive partial match)."""
        members_dict = self.get_member_names()
        for member_id, member_name in members_dict.items():
            if name.lower() in member_name.lower():
                return member_id
        return None

    def get_member_name_by_id(self, member_id: int) -> str:
        """Get member name by their ID."""
        members_dict = self.get_member_names()
        return members_dict.get(member_id, "Desconocido")

    def get_member_name_by_phone(self, number: str) -> Optional[str]:
        """Get member name by their phone number.

        Args:
            number (str): The phone number to validate. i.e: 5491123456789

        Returns:
            Optional[str]: The member's name if found, None otherwise
        """
        member = self.get_member_by_phone(number)
        if member:
            return member.name
        return None
