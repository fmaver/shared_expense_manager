"""Expense manager"""

import re
from datetime import date
from typing import Dict, Optional

from dateutil.relativedelta import relativedelta

from template.domain.models.category import Category
from template.domain.models.split import PercentageSplit

from ...adapters.repositories import MemberRepository, SQLAlchemyExpenseRepository
from .enums import PaymentType
from .models import Expense, Member, MonthlyShare
from .repository import ExpenseRepository


class ExpenseManager:
    def __init__(self, repository: ExpenseRepository, group_id: int, group_repo):
        self.repository = repository
        self.group_id = group_id
        self._group_repo = group_repo
        self.members: Dict[int, Member] = {}
        self._load_members()

    def _load_members(self) -> None:
        """Load group members from the group repository."""
        members = self._group_repo.list_members(self.group_id)
        self.members = {m.id: m for m in members}

    def create_and_add_expense(self, expense: Expense) -> Expense:
        """
        Creates and adds expense(s) based on payment type and installments.
        For credit payments, creates expenses for future months.
        Returns the created expense.
        """
        if expense.payment_type == PaymentType.DEBIT:
            self._add_to_monthly_share(expense, expense.date)
            if expense.id is None:
                raise ValueError("Expense ID cannot be None after adding to monthly share")
            return self.get_expense(expense.id)
        return self._handle_credit_expense(expense)

    def _handle_credit_expense(self, expense: Expense) -> Expense:
        """Handles credit expenses, creating installments as needed"""
        # Calculate amount per installment
        amount_per_installment = expense.amount / expense.installments

        # For credit, payments start next month
        start_date = expense.date + relativedelta(months=1)

        # Create first installment and save it to get an ID
        first_installment = Expense(
            description=f"{expense.description} (1/{expense.installments})",
            amount=amount_per_installment,
            date=expense.date,
            category=expense.category,
            payer_id=expense.payer_id,
            payment_type=PaymentType.CREDIT,
            installments=expense.installments,
            installment_no=1,
            split_strategy=expense.split_strategy,
        )
        self._add_to_monthly_share(first_installment, start_date)
        if first_installment.id is None:
            raise ValueError("First installment ID cannot be None after adding to monthly share")
        first_installment = self.get_expense(first_installment.id)  # Get fresh copy with ID

        # Create remaining installments with parent_expense_id set
        for installment_no in range(2, expense.installments + 1):
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
                parent_expense_id=first_installment.id,  # Set parent to first installment
            )

            self._add_to_monthly_share(installment_expense, installment_date)

        return first_installment

    def _add_to_monthly_share(self, expense: Expense, share_date: date) -> None:
        """Create monthly Share if doesn't exists.
        Add expense to monthly share and save both."""
        print("creating balance expenses..")
        # Get or create monthly share for the given date
        monthly_share = self.get_monthly_balance(share_date.year, share_date.month)
        if not monthly_share:
            print("Creating new monthly share: ", share_date.year, share_date.month)
            monthly_share = MonthlyShare(share_date.year, share_date.month, self.group_id)
            # Save to get an ID
            self.repository.save_monthly_share(monthly_share)
            # Fetch again to get the ID
            monthly_share = self.get_monthly_balance(share_date.year, share_date.month)
            if not monthly_share:
                raise ValueError("Failed to create monthly share")

        # At this point, monthly_share is guaranteed to be non-None
        monthly_share.add_expense(expense, self.members)
        print("EXPENSE ADDED - NOW SAVING THE EXPENSE")
        self.repository.save_monthly_share(monthly_share)

    def get_monthly_balance(self, year: int, month: int) -> Optional[MonthlyShare]:
        """Gets the monthly share for a specific period"""
        return self.repository.get_monthly_share(year, month, self.group_id)

    def settle_monthly_share(self, year: int, month: int) -> MonthlyShare | None:
        """Marks a monthly share as settled.

        For each net creditor-debtor pair, one balancing expense is generated by greedily
        matching the largest remaining creditor against the largest remaining debtor until
        balances net to zero. With two members this yields a single transfer; with N
        members it yields up to N-1 balancing expenses.
        """
        monthly_share = self.repository.get_monthly_share(year, month, self.group_id)
        if not monthly_share:
            return None

        if monthly_share.balances:
            self._generate_balancing_expenses(monthly_share, year, month)

        monthly_share.settle()
        self.repository.settle_monthly_share(monthly_share.year, monthly_share.month, self.group_id)

        return monthly_share

    def unsettle_monthly_share(self, year: int, month: int) -> MonthlyShare | None:
        """Reverse a settlement: remove auto-generated balancing expenses and reopen the month."""
        monthly_share = self.repository.get_monthly_share(year, month, self.group_id)
        if not monthly_share:
            return None

        self.repository.unsettle_monthly_share(year, month, self.group_id)
        monthly_share = self.repository.get_monthly_share(year, month, self.group_id)
        if monthly_share:
            self.recalculate_monthly_share(monthly_share)

        return self.repository.get_monthly_share(year, month, self.group_id)

    def _generate_balancing_expenses(self, monthly_share: MonthlyShare, year: int, month: int) -> None:
        """Greedy debt reduction: emit one Expense per (debtor -> creditor) pair."""
        epsilon = 0.01
        remaining_credit: Dict[int, float] = {
            int(mid): amt for mid, amt in monthly_share.balances.items() if amt > epsilon
        }
        remaining_debt: Dict[int, float] = {
            int(mid): -amt for mid, amt in monthly_share.balances.items() if amt < -epsilon
        }

        category = Category()
        category.name = "balance"

        while remaining_credit and remaining_debt:
            creditor_id = max(remaining_credit, key=lambda k: remaining_credit[k])
            debtor_id = max(remaining_debt, key=lambda k: remaining_debt[k])
            pay = round(min(remaining_credit[creditor_id], remaining_debt[debtor_id]), 2)

            if pay < epsilon:
                break

            balancing_expense = Expense(
                description="Balancing Expense",
                amount=pay,
                date=date(year, month, 1),
                category=category,
                payer_id=debtor_id,
                payment_type=PaymentType.DEBIT,
                installments=1,
                split_strategy=PercentageSplit({debtor_id: 0.0, creditor_id: 100.0}),
            )
            self.create_and_add_expense(balancing_expense)

            remaining_credit[creditor_id] -= pay
            remaining_debt[debtor_id] -= pay
            if remaining_credit[creditor_id] < epsilon:
                del remaining_credit[creditor_id]
            if remaining_debt[debtor_id] < epsilon:
                del remaining_debt[debtor_id]

    def add_member(self, member: Member) -> None:
        """Adds a new member and recalculates all active monthly shares"""
        # TODO -> Ideally, when adding a new member, we shoudln't recalculate balances.
        # ALSO like this, is not being persisted the new member in the DB
        self.members[member.id] = member

        # Recalculate balances for all active monthly shares
        monthly_shares = self.repository.get_all_monthly_shares(self.group_id)
        for monthly_share in monthly_shares.values():
            if not monthly_share.is_settled:
                self.recalculate_monthly_share(monthly_share)

    def update_expense(
        self,
        updated_expense: Expense,
        old_payment_type: Optional[PaymentType] = None,
        old_date: Optional[date] = None,
    ) -> Expense:
        """Update the expense and recalculate balances.
        In this case the expense is either DEBIT or CREDIT with 1 installment.
        old_payment_type / old_date describe where the expense lived before the edit
        so we can move it between monthly shares when payment type or date changes."""

        def _share_date(payment_type: PaymentType, d: date) -> date:
            return d + relativedelta(months=1) if payment_type == PaymentType.CREDIT else d

        prev_payment_type = old_payment_type if old_payment_type is not None else updated_expense.payment_type
        prev_date = old_date if old_date is not None else updated_expense.date
        old_share_date = _share_date(prev_payment_type, prev_date)
        new_share_date = _share_date(updated_expense.payment_type, updated_expense.date)

        self.repository.update_expense(updated_expense)

        if old_share_date != new_share_date:
            # Expense moved to a different monthly share — clean up old share first
            old_share = self.get_monthly_balance(old_share_date.year, old_share_date.month)
            if old_share:
                old_share.expenses = [e for e in old_share.expenses if e.id != updated_expense.id]
                self.recalculate_monthly_share(old_share)

            # Get or create the new monthly share and assign the expense to it
            new_share = self.get_monthly_balance(new_share_date.year, new_share_date.month)
            if not new_share:
                new_share = MonthlyShare(new_share_date.year, new_share_date.month, self.group_id)
                self.repository.save_monthly_share(new_share)
                new_share = self.get_monthly_balance(new_share_date.year, new_share_date.month)
                if not new_share:
                    raise ValueError("Failed to create monthly share")

            # Update the FK on the expense row
            if updated_expense.id is None:
                raise ValueError("Cannot reassign an expense without an ID")
            self.repository.reassign_expense_to_monthly_share(
                updated_expense.id, new_share_date.year, new_share_date.month, self.group_id
            )

            # Add to in-memory list and recalculate
            new_share.expenses.append(updated_expense)
            self.recalculate_monthly_share(new_share)
        else:
            # Same monthly share — update in place and recalculate
            monthly_share = self.get_monthly_balance(new_share_date.year, new_share_date.month)
            if monthly_share:
                for i, expense in enumerate(monthly_share.expenses):
                    if expense.id == updated_expense.id:
                        monthly_share.expenses[i] = updated_expense
                        break
                self.recalculate_monthly_share(monthly_share)

        return updated_expense

    # flake8: noqa: C901
    # pylint: disable=R0915
    def update_credit_expense(self, updated_expense: Expense) -> Expense:
        """Update a credit expense and all its related installments."""
        print(f"\n=== Starting credit expense update process for ID: {updated_expense.id} ===")

        # Get all child expenses
        if updated_expense.id is None:
            raise ValueError("Expense ID cannot be None")
        child_expenses = self.repository.get_child_expenses(updated_expense.id)
        print(f"Parent expense ID: {updated_expense.id}")
        print(f"Child expenses found with IDs: {[child_expense.id for child_expense in child_expenses]}")

        # Calculate amount per installment from the total amount
        amount_per_installment = updated_expense.amount / updated_expense.installments

        # Clean base description (remove any existing installment suffix)
        base_description = re.sub(r"\s*\(\d+\/\d+\)\s*$", "", updated_expense.description)
        current_total_installments = len(child_expenses) + 1
        print(
            f"We currently have {current_total_installments} installments, but we want {updated_expense.installments}"
        )

        # First, if we're reducing installments, delete the excess ones
        if updated_expense.installments < current_total_installments:
            print(f"Reducing installments from {current_total_installments} to {updated_expense.installments}")

            for i in range(current_total_installments, updated_expense.installments, -1):
                excess_child = child_expenses[i - 2]
                print(f"Deleting excess installment {i}: {excess_child.description}")
                if excess_child.id is None:
                    raise ValueError("Expense ID cannot be None")
                self.repository.delete_expense(excess_child.id)

                # Get and recalculate the monthly share for this installment
                installment_date = updated_expense.date + relativedelta(months=i)
                monthly_share = self.get_monthly_balance(installment_date.year, installment_date.month)
                if monthly_share:
                    self.recalculate_monthly_share(monthly_share)

        # Update the first installment with the per-installment amount
        updated_expense.amount = amount_per_installment
        updated_expense.description = f"{base_description} (1/{updated_expense.installments})"
        print("Updating first installment:")
        self.repository.update_expense(updated_expense)

        # recalculate monthly share
        installment_date = updated_expense.date + relativedelta(months=1)
        monthly_share = self.get_monthly_balance(installment_date.year, installment_date.month)
        if monthly_share:
            self.recalculate_monthly_share(monthly_share)

        # Update remaining child installments
        for i in range(
            updated_expense.installments - 1
        ):  # from 1 because first installment (position 0) is already handled
            if i < len(child_expenses):
                child = child_expenses[i]
                child.description = f"{base_description} ({i + 2}/{updated_expense.installments})"
                child.amount = amount_per_installment
                child.date = updated_expense.date
                child.category = updated_expense.category
                child.payer_id = updated_expense.payer_id
                child.payment_type = updated_expense.payment_type
                child.split_strategy = updated_expense.split_strategy
                child.installments = updated_expense.installments  # Update total installments
                child.installment_no = i + 2  # Update installment number
                child.parent_expense_id = updated_expense.id  # Set parent expense ID

                self.repository.update_expense(child)

                # Get and recalculate the monthly share for this installment
                # For credit, payments start next month
                installment_date = updated_expense.date + relativedelta(months=child.installment_no)
                monthly_share = self.get_monthly_balance(installment_date.year, installment_date.month)
                if monthly_share:
                    self.recalculate_monthly_share(monthly_share)

        print("Check if we need to create new installments...")

        # If we're increasing installments, create new ones
        if updated_expense.installments > (len(child_expenses) + 1):  # +1 to account for the parent expense
            start_installment = len(child_expenses) + 2  # +2 because we start after parent and existing children
            for i in range(start_installment, updated_expense.installments + 1):
                installment_date = updated_expense.date + relativedelta(months=i)
                new_child_expense = Expense(
                    description=f"{base_description} ({i}/{updated_expense.installments})",
                    amount=amount_per_installment,
                    date=updated_expense.date,
                    category=updated_expense.category,
                    payer_id=updated_expense.payer_id,
                    payment_type=updated_expense.payment_type,
                    installments=updated_expense.installments,
                    installment_no=i,
                    split_strategy=updated_expense.split_strategy,
                    parent_expense_id=updated_expense.id,
                )

                # Add expense to the appropriate monthly share
                self._add_to_monthly_share(new_child_expense, installment_date)

                # Get and recalculate the monthly share for this installment
                monthly_share = self.get_monthly_balance(installment_date.year, installment_date.month)
                if monthly_share:
                    self.recalculate_monthly_share(monthly_share)

        print("\n=== Credit expense update process completed ===")
        return updated_expense

    def get_expense(self, expense_id: int) -> Expense:
        """Retrieves an expense by its ID."""
        expense = self.repository.get_expense(expense_id)
        if not expense:
            raise ValueError("Expense not found")
        return expense

    def get_parent_expense(self, expense_id: int) -> Optional[Expense]:
        """Get the parent expense for a given expense ID."""
        expense = self.get_expense(expense_id)
        if expense.parent_expense_id is None:
            return None
        return self.get_expense(expense.parent_expense_id)

    def delete_expense(self, expense_id: int) -> None:
        """Delete an expense and its child installments if any."""
        print(f"\n=== Starting expense deletion process for ID: {expense_id} ===")
        expense = self.get_expense(expense_id)
        if not expense:
            raise ValueError(f"Expense with ID {expense_id} not found")

        print(f"Found expense to delete: {expense.description} (Amount: {expense.amount}, Date: {expense.date}")

        # Get all affected monthly shares before deletion
        affected_shares = set()

        # For credit expenses, payments start next month
        if expense.payment_type == PaymentType.CREDIT:
            start_date = expense.date + relativedelta(months=1)
            first_month_date = start_date
            print(f"Credit expense: First installment date will be {first_month_date}")
            monthly_share = self._get_monthly_share_for_date(first_month_date)
            if monthly_share:
                print(f"Adding monthly share for first installment date {first_month_date} to affected shares")
                affected_shares.add(monthly_share)

            # If this is a parent expense, get all child installments and their monthly shares
            if expense.installment_no == 1 and expense.id is not None:
                print("This is a parent credit expense, getting child installments...")
                child_expenses = self.repository.get_child_expenses(expense_id)
                for child in child_expenses:
                    child_date = first_month_date + relativedelta(months=child.installment_no - 1)
                    print(f"Found child installment: {child.description} (Date: {child_date})")
                    child_share = self._get_monthly_share_for_date(child_date)
                    if child_share:
                        print(f"Adding monthly share for child date {child_date} to affected shares")
                        affected_shares.add(child_share)
        else:
            # For debit expenses, use the original date
            monthly_share = self._get_monthly_share_for_date(expense.date)
            if monthly_share:
                print(f"Adding monthly share for debit expense date {expense.date} to affected shares")
                affected_shares.add(monthly_share)

        # Delete the expense (this will cascade delete child installments)
        print(f"Deleting expense ID {expense_id} and its child installments...")
        self.repository.delete_expense(expense_id)

        # Recalculate balances for all affected monthly shares
        print(f"\n=== Recalculating balances for {len(affected_shares)} affected monthly shares ===")
        for share in affected_shares:
            print(f"\nRecalculating monthly share for {share.year}-{share.month}")
            print(f"Before recalculation - Balances: {share.balances}")

            # Get a fresh copy of the monthly share after deletion
            updated_share = self.get_monthly_balance(share.year, share.month)
            if updated_share:
                self.recalculate_monthly_share(updated_share)
                print(f"After recalculation - Balances: {updated_share.balances}")
            else:
                print(f"No monthly share found for {share.year}-{share.month} after deletion")

        print("\n=== Expense deletion process completed ===")

    def _get_monthly_share_for_date(self, expense_date: date) -> Optional[MonthlyShare]:
        """Get monthly share for a given date."""
        return self.repository.get_monthly_share(expense_date.year, expense_date.month, self.group_id)

    def recalculate_monthly_share(self, monthly_share: MonthlyShare) -> MonthlyShare:
        """Recalculate a monthly share - resolve balances."""
        monthly_share.recalculate_balances(self.members)
        self.repository.save_monthly_share(monthly_share)
        print("Monthly share recalculated")

        return monthly_share
