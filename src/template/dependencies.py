"""Dependency functions for the application."""

from fastapi import Depends
from sqlalchemy.orm import Session

from template.adapters.database import get_db
from template.adapters.repositories import (
    ChatSessionRepository,
    GroupRepository,
    IncomeRepository,
    MemberRepository,
    ProcessedMessageRepository,
    RecurringGroupExpenseRepository,
    RecurringPersonalExpenseRepository,
    SQLAlchemyExpenseRepository,
)
from template.domain.models.expense_manager import ExpenseManager
from template.domain.models.repository import ExpenseRepository
from template.service_layer.expense_service import ExpenseService
from template.service_layer.group_service import GroupService
from template.service_layer.member_service import MemberService
from template.service_layer.personal_ledger_service import PersonalLedgerService
from template.service_layer.whatsapp_client import MetaWhatsAppClient, WhatsAppClient


def get_repository(db: Session = Depends(get_db)) -> ExpenseRepository:
    """Get repository instance."""
    return SQLAlchemyExpenseRepository(db)


def get_member_repository(db: Session = Depends(get_db)) -> MemberRepository:
    """Get member repository instance."""
    return MemberRepository(db)


def get_group_repository(db: Session = Depends(get_db)) -> GroupRepository:
    """Get group repository instance."""
    return GroupRepository(db)


def get_group_service(
    group_repo: GroupRepository = Depends(get_group_repository),
) -> GroupService:
    """Get group service instance."""
    return GroupService(group_repo)


def get_expense_service(
    group_id: int,
    repository: ExpenseRepository = Depends(get_repository),
    group_repo: GroupRepository = Depends(get_group_repository),
) -> ExpenseService:
    """Get expense service instance scoped to a group."""
    return ExpenseService(repository, group_id=group_id, group_repo=group_repo)


def get_member_service(
    repository: MemberRepository = Depends(get_member_repository),
) -> MemberService:
    """Get member service instance."""
    return MemberService(repository)


def get_whatsapp_client() -> WhatsAppClient:
    """Get WhatsApp client instance."""
    return MetaWhatsAppClient()


def get_chat_session_repository(db: Session = Depends(get_db)) -> ChatSessionRepository:
    """Get chat session repository instance."""
    return ChatSessionRepository(db)


def get_processed_message_repository(db: Session = Depends(get_db)) -> ProcessedMessageRepository:
    """Get processed message repository instance."""
    return ProcessedMessageRepository(db)


def get_income_repository(db: Session = Depends(get_db)) -> IncomeRepository:
    """Get income repository instance."""
    return IncomeRepository(db)


def get_recurring_expense_repository(db: Session = Depends(get_db)) -> RecurringPersonalExpenseRepository:
    """Get recurring personal expense repository instance."""
    return RecurringPersonalExpenseRepository(db)


def get_recurring_group_expense_repository(db: Session = Depends(get_db)) -> RecurringGroupExpenseRepository:
    """Get recurring group expense repository instance."""
    return RecurringGroupExpenseRepository(db)


def get_personal_ledger_service(
    group_service: GroupService = Depends(get_group_service),
    group_repo: GroupRepository = Depends(get_group_repository),
    expense_repo: ExpenseRepository = Depends(get_repository),
    income_repo: IncomeRepository = Depends(get_income_repository),
    recurring_expense_repo: RecurringPersonalExpenseRepository = Depends(get_recurring_expense_repository),
) -> PersonalLedgerService:
    """Get personal ledger service instance."""
    return PersonalLedgerService(
        group_service=group_service,
        group_repo=group_repo,
        expense_repo=expense_repo,
        income_repo=income_repo,
        recurring_expense_repo=recurring_expense_repo,
    )


def get_recurring_group_expense_materializer(
    group_id: int,
    db: Session = Depends(get_db),
    group_repo: GroupRepository = Depends(get_group_repository),
):
    """Return a pre-wired callable that materializes recurring group expenses for a given period.

    Usage in a route::

        materializer = Depends(get_recurring_group_expense_materializer)
        materializer(year, month)
    """
    from template.service_layer.recurring_group_expense_service import (  # pylint: disable=import-outside-toplevel
        materialize_recurring_group_expenses,
    )

    expense_repo = SQLAlchemyExpenseRepository(db)
    recurring_repo = RecurringGroupExpenseRepository(db)
    expense_manager = ExpenseManager(expense_repo, group_id, group_repo)

    def _materialize(year: int, month: int) -> None:
        materialize_recurring_group_expenses(
            group_id=group_id,
            year=year,
            month=month,
            recurring_repo=recurring_repo,
            expense_repo=expense_repo,
            expense_manager=expense_manager,
        )

    return _materialize
