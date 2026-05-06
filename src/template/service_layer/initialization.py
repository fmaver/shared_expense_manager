"""Service layer module for initializing application components and dependencies."""

import logging

from sqlalchemy.orm import Session

from template.adapters.database import SessionLocal, engine
from template.adapters.orm import Base, MemberModel
from template.adapters.repositories import SQLAlchemyExpenseRepository
from template.domain.models.expense_manager import ExpenseManager
from template.settings.bootstrap_settings import BootstrapSettings

log = logging.getLogger(__name__)


class InitializationService:
    @classmethod
    async def initialize(cls):
        """Initialize application services and dependencies"""
        log.info("Initializing application services and dependencies")
        try:
            Base.metadata.create_all(bind=engine)

            with SessionLocal() as db:
                cls._upsert_bootstrap_members(db)

        except Exception as e:
            log.error("Failed to initialize services: %s", str(e))
            raise

    @staticmethod
    def _upsert_bootstrap_members(db: Session) -> None:
        """Idempotently insert any members listed in MEMBERS_BOOTSTRAP_JSON.

        Members are matched by email; existing rows are never modified. When
        the env var is unset, this is a no-op so production data remains
        untouched on every restart.
        """
        bootstrap_members = BootstrapSettings().parse_members()
        if not bootstrap_members:
            return

        inserted = 0
        for entry in bootstrap_members:
            existing = db.query(MemberModel).filter(MemberModel.email == entry.email).first()
            if existing:
                continue
            db.add(MemberModel(name=entry.name, email=entry.email, telephone=entry.telephone))
            log.info("Bootstrapped member %s <%s>", entry.name, entry.email)
            inserted += 1

        if inserted == 0:
            return

        try:
            db.commit()
            log.info("Bootstrap inserted %d new member(s)", inserted)
        except Exception as e:
            db.rollback()
            log.error("Error inserting bootstrap members: %s", str(e))
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
