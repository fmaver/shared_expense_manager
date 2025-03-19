"""Dependency functions for the application."""

from fastapi import Depends
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.adapters.repositories import MemberRepository, SQLAlchemyExpenseRepository
from template.domain.models.repository import ExpenseRepository
from template.service_layer.expense_service import ExpenseService
from template.service_layer.member_service import MemberService


def get_repository(db: Session = Depends(get_db)) -> ExpenseRepository:
    """Get repository instance."""
    return SQLAlchemyExpenseRepository(db)


def get_expense_service(
    repository: ExpenseRepository = Depends(get_repository),
) -> ExpenseService:
    """Get expense service instance."""
    return ExpenseService(repository)


def get_member_service(
    repository: MemberRepository = Depends(get_repository),
) -> MemberService:
    """Get member service instance."""
    return MemberService(repository)
