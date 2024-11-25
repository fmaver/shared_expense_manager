"""Dependency functions for the application."""

from functools import lru_cache

from fastapi import Depends

from template.domain.models.models import ExpenseManager
from template.service_layer.initialization import InitializationService


@lru_cache()
def get_expense_manager() -> ExpenseManager:
    """
    Creates or returns a cached ExpenseManager instance.

    The manager is initialized with default members and cached for subsequent requests.
    In a real application, this would likely connect to a database and handle persistence.

    Returns:
        ExpenseManager: A singleton instance of the expense manager
    """
    return InitializationService.initialize_expense_manager()


def get_initialized_manager(
    manager: ExpenseManager = Depends(get_expense_manager),
) -> ExpenseManager:
    """
    Dependency that ensures the expense manager is properly initialized.

    Args:
        manager: The expense manager instance from the cache

    Returns:
        ExpenseManager: An initialized expense manager

    Raises:
        HTTPException: If the manager is not properly initialized
    """
    if not manager.members:
        manager = InitializationService.initialize_expense_manager()
    return manager
