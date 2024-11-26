"""Dependency functions for the application."""

from fastapi import Depends
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.adapters.repositories import SQLAlchemyExpenseRepository
from template.domain.models.repository import ExpenseRepository
from template.service_layer.expense_service import ExpenseService


def get_repository(db: Session = Depends(get_db)) -> ExpenseRepository:
    """Get repository instance."""
    return SQLAlchemyExpenseRepository(db)


def get_expense_service(
    repository: ExpenseRepository = Depends(get_repository),
) -> ExpenseService:
    """Get expense service instance."""
    return ExpenseService(repository)
