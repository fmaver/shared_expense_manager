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
            {"id": 1, "name": "Fran", "telephone": "5491138718498", "email": "franciscomaver.fm@gmail.com"},
            {"id": 2, "name": "Guadi", "telephone": "5491122766501", "email": "g.rodriguezmazza@gmail.com"},
        ]

        for member_data in default_members:
            # First try to find by ID
            existing = db.query(MemberModel).filter(MemberModel.id == member_data["id"]).first()

            if existing:
                # Member exists, check if it needs email update
                if not hasattr(existing, "email") or not existing.email:
                    log.info("Updating existing member %s with email information", existing.name)
                    existing.email = member_data["email"]
                    db.add(existing)
            else:
                # Member doesn't exist, create new
                member = MemberModel(**member_data)
                db.add(member)
                log.info("Added default member: %s (ID: %d)", member.name, member.id)

        try:
            db.commit()
            log.info("Successfully initialized/updated default members")
        except Exception as e:
            db.rollback()
            log.error("Error initializing/updating default members: %s", str(e))
            raise

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
