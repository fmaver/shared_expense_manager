"""Expense manager"""
from datetime import date
from typing import Dict, Optional

from dateutil.relativedelta import relativedelta

from ...adapters.repositories import MemberRepository, SQLAlchemyExpenseRepository
from .enums import PaymentType
from .models import Expense, Member, MonthlyShare
from .repository import ExpenseRepository


class ExpenseManager:
    def __init__(self, repository: ExpenseRepository):
        self.repository = repository
        self.members: Dict[int, Member] = {}
        self._load_members()

    def _load_members(self) -> None:
        """Load members from repository."""
        if isinstance(self.repository, SQLAlchemyExpenseRepository):
            member_repository = MemberRepository(self.repository.session)
            self.members = {member.id: member for member in member_repository.list()}

    def create_and_add_expense(self, expense: Expense) -> None:
        """
        Creates and adds expense(s) based on payment type and installments.
        For credit payments, creates expenses for future months.
        """
        if expense.payment_type == PaymentType.DEBIT:
            self._add_to_monthly_share(expense, expense.date)
        else:  # CREDIT
            self._handle_credit_expense(expense)

    def _handle_credit_expense(self, expense: Expense) -> None:
        """Handles credit expenses, creating installments as needed"""
        # Calculate amount per installment
        amount_per_installment = expense.amount / expense.installments

        # For credit, payments start next month
        start_date = expense.date + relativedelta(months=1)

        # Create an expense for each installment
        for installment_no in range(1, expense.installments + 1):
            installment_date = start_date + relativedelta(months=installment_no - 1)

            installment_expense = Expense(
                description=f"{expense.description} ({installment_no}/{expense.installments})",
                amount=amount_per_installment,
                date=expense.date,
                category=expense.category,
                payer_id=expense.payer_id,
                payment_type=PaymentType.CREDIT,
                installments=expense.installments,
                installment_no=installment_no,
                split_strategy=expense.split_strategy,
            )

            self._add_to_monthly_share(installment_expense, installment_date)

    def _add_to_monthly_share(self, expense: Expense, share_date: date) -> None:
        """Add expense to monthly share and save both."""
        # Get or create monthly share for the given date
        monthly_share = self.get_monthly_balance(share_date.year, share_date.month)
        if not monthly_share:
            monthly_share = MonthlyShare(share_date.year, share_date.month)
            # Save to get an ID
            self.repository.save_monthly_share(monthly_share)
            # Fetch again to get the ID
            monthly_share = self.get_monthly_balance(share_date.year, share_date.month)
            if not monthly_share:
                raise ValueError("Failed to create monthly share")

        # At this point, monthly_share is guaranteed to be non-None
        monthly_share.add_expense(expense, self.members)
        self.repository.save_monthly_share(monthly_share)

    def get_monthly_balance(self, year: int, month: int) -> Optional[MonthlyShare]:
        """Gets the monthly share for a specific period"""
        return self.repository.get_monthly_share(year, month)

    def settle_monthly_share(self, year: int, month: int) -> None:
        """Marks a monthly share as settled"""
        monthly_share = self.repository.get_monthly_share(year, month)
        if monthly_share:
            monthly_share.settle()
            self.repository.save_monthly_share(monthly_share)

    def add_member(self, member: Member) -> None:
        """Adds a new member and recalculates all active monthly shares"""
        self.members[member.id] = member

        # Recalculate balances for all active monthly shares
        monthly_shares = self.repository.get_all_monthly_shares()
        for monthly_share in monthly_shares.values():
            if not monthly_share.is_settled:
                monthly_share.recalculate_balances(self.members)
                self.repository.save_monthly_share(monthly_share)
