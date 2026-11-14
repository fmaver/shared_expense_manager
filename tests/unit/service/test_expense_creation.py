"""create_expense_with_effects: the one path that creates an expense and fires its effects."""

from datetime import date
from unittest.mock import MagicMock

from fastapi import BackgroundTasks

from template.domain.models.enums import PaymentType
from template.domain.schemas.expense import (
    CategorySchema,
    ExpenseCreate,
    SplitStrategySchema,
)
from template.service_layer.expense_creation import create_expense_with_effects


def _data() -> ExpenseCreate:
    return ExpenseCreate(
        description="Cena",
        amount=100.0,
        date=date(2026, 11, 1),
        category=CategorySchema(name="comida"),
        payer_id=1,
        payment_type=PaymentType.DEBIT,
        installments=1,
        split_strategy=SplitStrategySchema(type="equal"),
    )


def _run(personal: bool):
    service = MagicMock()
    service.group_id = 7
    service.is_personal_group.return_value = personal
    service.create_expense.return_value = MagicMock(id=42, parent_expense_id=None)
    group_service = MagicMock()
    repository = MagicMock()
    tasks = BackgroundTasks()
    response = create_expense_with_effects(
        service=service,
        expense_data=_data(),
        creator=MagicMock(),
        background_tasks=tasks,
        member_service=MagicMock(),
        group_service=group_service,
        repository=repository,
        db=MagicMock(),
    )
    return response, tasks, group_service, repository


def test_create_expense_with_effects_skips_notifications_for_personal_group():
    response, tasks, group_service, repository = _run(personal=True)

    assert tasks.tasks == []
    group_service.refresh_archived_state.assert_called_once_with(7, repository)
    assert response.id == 42


def test_create_expense_with_effects_queues_notification_for_shared_group():
    response, tasks, group_service, repository = _run(personal=False)

    assert len(tasks.tasks) == 1
    assert tasks.tasks[0].func.__name__ == "notify_expense_created"
    assert tasks.tasks[0].kwargs["group_id"] == 7
    group_service.refresh_archived_state.assert_called_once_with(7, repository)
    assert response.id == 42
    assert response.installment_no == 1
    assert response.category == "comida"
