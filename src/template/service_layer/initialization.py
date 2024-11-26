"""Service layer module for initializing application components and dependencies."""

import logging

from sqlalchemy.orm import Session

from template.adapters.database import SessionLocal, engine
from template.adapters.orm import Base, MemberModel
from template.adapters.repositories import SQLAlchemyExpenseRepository
from template.domain.models.expense_manager import ExpenseManager

log = logging.getLogger(__name__)


class InitializationService:
    @classmethod
    async def initialize(cls):
        """Initialize application services and dependencies"""
        log.info("Initializing application services and dependencies")
        try:
            # Create all database tables
            Base.metadata.create_all(bind=engine)

            # Initialize default data
            with SessionLocal() as db:
                cls._initialize_default_members(db)

        except Exception as e:
            log.error("Failed to initialize services: %s", str(e))
            raise

    @staticmethod
    def _initialize_default_members(db: Session) -> None:
        """Initialize default members if they don't exist."""

        default_members = [
            {"id": 1, "name": "Fran", "telephone": "+1234567890"},
            {"id": 2, "name": "Guadi", "telephone": "+1234567891"},
        ]

        for member_data in default_members:
            # Check if member already exists
            existing = db.query(MemberModel).filter_by(id=member_data["id"]).first()
            if not existing:
                member = MemberModel(**member_data)
                db.add(member)
                log.debug("Added default member: %s (ID: %d)", member.name, member.id)
                print(f"Added default member: {member.name} (ID: {member.id})")

        db.commit()

    @staticmethod
    def initialize_expense_manager(db: Session) -> ExpenseManager:
        """Initialize the expense manager with repository."""
        log.info("Initializing expense manager")
        try:
            repository = SQLAlchemyExpenseRepository(db)
            manager = ExpenseManager(repository)

            log.info("Successfully initialized expense manager")
            return manager

        except Exception as e:
            log.error("Failed to initialize expense manager: %s", str(e))
            raise
