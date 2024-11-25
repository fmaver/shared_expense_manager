"""Service layer module for initializing application components and dependencies."""

import logging
from typing import List

from template.domain.models.member import Member
from template.domain.models.models import ExpenseManager

log = logging.getLogger(__name__)


class InitializationService:
    @classmethod
    async def initialize(cls):
        """Initialize application services and dependencies"""
        print("Initializing application services and dependencies")
        try:
            # Add initialization logic here if needed
            pass
        except Exception as e:
            log.error("Failed to initialize services: %s", str(e))
            raise

    @staticmethod
    def initialize_expense_manager() -> ExpenseManager:
        """Initialize the expense manager with default members."""
        print("Initializing expense manager")
        try:
            manager = ExpenseManager()

            # Add default members
            default_members: List[Member] = [
                Member(id=1, name="Fran", telephone="+1234567890"),
                Member(id=2, name="Guadi", telephone="+1234567891"),
            ]

            log.debug("Adding %d default members to expense manager", len(default_members))
            for member in default_members:
                log.debug("Adding member: %s (ID: %d)", member.name, member.id)
                manager.add_member(member)

            print("Successfully initialized expense manager with default members")
            return manager

        except Exception as e:
            log.error("Failed to initialize expense manager: %s", str(e))
            raise
