import copy
from datetime import date
from decimal import Decimal

import pytest

from template.domain.models.category import Category
from template.domain.models.enums import PaymentType
from template.domain.models.member import Member
from template.domain.models.models import Expense, MonthlyShare
from template.domain.models.split import EqualSplit
from template.domain.schemas.expense import (
    CategorySchema,
    ExpenseCreate,
    SplitStrategySchema,
)
from template.service_layer.expense_service import ExpenseService


class TestExpenseService:
    @pytest.fixture
    def service(self, mock_repository):
        return ExpenseService(mock_repository)

    @pytest.fixture
    def debit_expense(self):
        category = Category()
        category.name = "food"
        return Expense(
            description="Test Debit",
            amount=100.0,
            date=date(2024, 3, 15),
            category=category,
            payer_id=1,
            payment_type=PaymentType.DEBIT,
            split_strategy=EqualSplit(),
        )

    @pytest.fixture
    def expense_data(self):
        return ExpenseCreate(
            description="Test Debit",
            amount=100.0,
            date=date(2024, 3, 15),
            category=CategorySchema(name="food"),
            payer_id=1,
            payment_type=PaymentType.DEBIT,
            installments=1,
            split_strategy=SplitStrategySchema(type="equal"),
        )

    def test_update_expense(self, service: ExpenseService, debit_expense, expense_data: ExpenseCreate):
        service._manager.add_member(Member(id=1, name="John", telephone="+1234567890", email="john@example.com"))
        service._manager.add_member(Member(id=2, name="Jane", telephone="+1234567891", email="jane@example.com"))

        service.create_expense(expense_data)

        expenses = service._manager.repository.get_expenses_by_date(expense_data.date)
        assert len(expenses) == 1
        expense_id = expenses[0].id

        # Prepare updated expense data
        updated_expense_data = ExpenseCreate(
            description="Updated Test Debit",
            amount=150.0,
            date=date(2024, 3, 15),
            category=CategorySchema(name="food"),
            payer_id=1,
            payment_type=PaymentType.DEBIT,
            installments=1,
            split_strategy=SplitStrategySchema(type="equal"),
        )

        # Update the expense
        updated_expense = service.update_expense(expense_id, updated_expense_data)

        # Verify the expense has been updated
        assert updated_expense.description == "Updated Test Debit"
        assert updated_expense.amount == 150.0

    def test_delete_expense(self, service: ExpenseService, debit_expense, expense_data):
        service._manager.add_member(Member(id=1, name="John", telephone="+1234567890", email="john@example.com"))
        service._manager.add_member(Member(id=2, name="Jane", telephone="+1234567891", email="jane@example.com"))

        # Create the expense
        service.create_expense(expense_data)

        # Check if the expense is saved in the mock repository
        assert len(service._manager.repository.expenses) == 1  # Check if one expense is saved
        assert service._manager.repository.expenses[0].description == expense_data.description  # Check the description
        assert service._manager.repository.expenses[0].amount == expense_data.amount  # Check the amount

        expenses = service._manager.repository.get_expenses_by_date(expense_data.date)
        assert len(service._manager.repository.expenses) == 1
        expense_id = expenses[0].id
        # Delete the expense
        service.delete_expense(expense_id)

        expenses = service._manager.repository.get_expenses_by_date(expense_data.date)
        assert len(service._manager.repository.expenses) == 0

        # Verify the expense is deleted
        with pytest.raises(ValueError):
            service.get_expense(expense_id)


class TestUpdateExpenseRouting:
    """All update_expense payment-type / installment routing scenarios."""

    BASE_DATE = date(2024, 3, 15)

    @pytest.fixture
    def service(self, mock_repository):
        svc = ExpenseService(mock_repository)
        svc._manager.add_member(Member(id=1, name="Alice", telephone="+1234567890", email="a@a.com"))
        svc._manager.add_member(Member(id=2, name="Bob", telephone="+1234567891", email="b@b.com"))
        return svc

    def _data(self, payment_type, installments, amount=300.0):
        return ExpenseCreate(
            description="Test",
            amount=amount,
            date=self.BASE_DATE,
            category=CategorySchema(name="food"),
            payer_id=1,
            payment_type=payment_type,
            installments=installments,
            split_strategy=SplitStrategySchema(type="equal"),
        )

    def _share(self, service, year, month):
        return service._manager.get_monthly_balance(year, month)

    def _share_expense_count(self, service, year, month):
        share = self._share(service, year, month)
        return len(share.expenses) if share else 0

    def _total_expenses(self, service):
        return len(service._manager.repository.expenses)

    # ── debit → * ──────────────────────────────────────────────────────────

    def test_debit_to_debit_updates_in_place(self, service):
        """Same month, values updated, no extra rows."""
        exp_id = service.create_expense(self._data(PaymentType.DEBIT, 1)).id
        service.update_expense(exp_id, self._data(PaymentType.DEBIT, 1, amount=500.0))

        assert self._share_expense_count(service, 2024, 3) == 1
        assert self._share(service, 2024, 3).expenses[0].amount == pytest.approx(500.0)
        assert self._total_expenses(service) == 1

    def test_debit_to_credit_single_moves_to_next_month(self, service):
        """Expense moves from March (debit) to April (credit-1)."""
        exp_id = service.create_expense(self._data(PaymentType.DEBIT, 1)).id
        service.update_expense(exp_id, self._data(PaymentType.CREDIT, 1))

        assert self._share_expense_count(service, 2024, 3) == 0
        assert self._share_expense_count(service, 2024, 4) == 1
        assert self._share(service, 2024, 4).expenses[0].payment_type == PaymentType.CREDIT
        assert self._total_expenses(service) == 1

    def test_debit_to_credit_multi_creates_installments(self, service):
        """Old single row replaced by 3 installments across Apr–Jun."""
        exp_id = service.create_expense(self._data(PaymentType.DEBIT, 1)).id
        service.update_expense(exp_id, self._data(PaymentType.CREDIT, 3))

        assert self._share_expense_count(service, 2024, 3) == 0
        assert self._share_expense_count(service, 2024, 4) == 1
        assert self._share_expense_count(service, 2024, 5) == 1
        assert self._share_expense_count(service, 2024, 6) == 1
        assert self._share(service, 2024, 4).expenses[0].amount == pytest.approx(100.0)
        assert self._total_expenses(service) == 3

    # ── credit-1 → * ───────────────────────────────────────────────────────

    def test_credit_single_to_debit_moves_back_to_original_month(self, service):
        """Expense moves from April (credit-1) back to March (debit)."""
        exp_id = service.create_expense(self._data(PaymentType.CREDIT, 1)).id
        service.update_expense(exp_id, self._data(PaymentType.DEBIT, 1))

        assert self._share_expense_count(service, 2024, 4) == 0
        assert self._share_expense_count(service, 2024, 3) == 1
        assert self._share(service, 2024, 3).expenses[0].payment_type == PaymentType.DEBIT
        assert self._total_expenses(service) == 1

    def test_credit_single_to_credit_single_stays_in_same_share(self, service):
        """credit-1 → credit-1: still in April, values updated."""
        exp_id = service.create_expense(self._data(PaymentType.CREDIT, 1)).id
        service.update_expense(exp_id, self._data(PaymentType.CREDIT, 1, amount=500.0))

        assert self._share_expense_count(service, 2024, 4) == 1
        assert self._share(service, 2024, 4).expenses[0].amount == pytest.approx(500.0)
        assert self._total_expenses(service) == 1

    def test_credit_single_to_credit_multi_creates_installments(self, service):
        """credit-1 replaced by 3 installments across Apr–Jun."""
        exp_id = service.create_expense(self._data(PaymentType.CREDIT, 1)).id
        service.update_expense(exp_id, self._data(PaymentType.CREDIT, 3))

        assert self._share_expense_count(service, 2024, 4) == 1
        assert self._share_expense_count(service, 2024, 5) == 1
        assert self._share_expense_count(service, 2024, 6) == 1
        assert self._share(service, 2024, 4).expenses[0].amount == pytest.approx(100.0)
        assert self._total_expenses(service) == 3

    # ── credit-N → * ───────────────────────────────────────────────────────

    def test_credit_multi_to_debit_deletes_children_and_moves_to_original_month(self, service):
        """All 3 credit rows deleted; single debit expense appears in March."""
        exp_id = service.create_expense(self._data(PaymentType.CREDIT, 3)).id
        # form pre-fills total (per-installment × installments) — service receives full amount
        service.update_expense(exp_id, self._data(PaymentType.DEBIT, 1, amount=300.0))

        assert self._share_expense_count(service, 2024, 4) == 0
        assert self._share_expense_count(service, 2024, 5) == 0
        assert self._share_expense_count(service, 2024, 6) == 0
        assert self._share_expense_count(service, 2024, 3) == 1
        assert self._share(service, 2024, 3).expenses[0].payment_type == PaymentType.DEBIT
        assert self._share(service, 2024, 3).expenses[0].amount == pytest.approx(300.0)
        assert self._total_expenses(service) == 1

    def test_credit_multi_to_credit_more_installments(self, service):
        """credit-3 → credit-5: two new child rows created."""
        exp_id = service.create_expense(self._data(PaymentType.CREDIT, 3)).id
        service.update_expense(exp_id, self._data(PaymentType.CREDIT, 5, amount=300.0))

        for month in range(4, 9):  # Apr–Aug
            assert self._share_expense_count(service, 2024, month) == 1, f"month {month}"
        assert self._total_expenses(service) == 5

    def test_credit_multi_to_credit_fewer_installments(self, service):
        """credit-5 → credit-3: two excess rows deleted."""
        exp_id = service.create_expense(self._data(PaymentType.CREDIT, 5)).id
        service.update_expense(exp_id, self._data(PaymentType.CREDIT, 3, amount=300.0))

        for month in range(4, 7):  # Apr–Jun kept
            assert self._share_expense_count(service, 2024, month) == 1, f"month {month}"
        for month in range(7, 9):  # Jul–Aug cleared
            assert self._share_expense_count(service, 2024, month) == 0, f"month {month}"
        assert self._total_expenses(service) == 3

    def test_credit_multi_to_credit_single(self, service):
        """credit-3 → credit-1: all children deleted, one expense stays in April."""
        exp_id = service.create_expense(self._data(PaymentType.CREDIT, 3)).id
        service.update_expense(exp_id, self._data(PaymentType.CREDIT, 1, amount=300.0))

        assert self._share_expense_count(service, 2024, 4) == 1
        assert self._share(service, 2024, 4).expenses[0].amount == pytest.approx(300.0)
        for month in range(5, 7):  # May–Jun cleared
            assert self._share_expense_count(service, 2024, month) == 0, f"month {month}"
        assert self._total_expenses(service) == 1

    def test_guard_child_installment_cannot_be_edited(self, service):
        """Attempting to edit installment_no > 1 raises ValueError."""
        service.create_expense(self._data(PaymentType.CREDIT, 3))
        children = [e for e in service._manager.repository.expenses if e.installment_no > 1]
        assert children, "No child installments found"
        with pytest.raises(ValueError, match="Cannot update"):
            service.update_expense(children[0].id, self._data(PaymentType.CREDIT, 3))
