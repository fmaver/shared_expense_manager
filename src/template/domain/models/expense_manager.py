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
    def __init__(self, repository: ExpenseRepository):
        self.repository = repository
        self.members: Dict[int, Member] = {}
        self._load_members()

    def _load_members(self) -> None:
        """Load members from repository."""
        if isinstance(self.repository, SQLAlchemyExpenseRepository):
            member_repository = MemberRepository(self.repository.session)
            self.members = {member.id: member for member in member_repository.list()}

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
        """Add expense to monthly share and save both."""
        print("creating balance expenses..")
        # Get or create monthly share for the given date
        monthly_share = self.get_monthly_balance(share_date.year, share_date.month)
        if not monthly_share:
            print("Creating new monthly share: ", share_date.year, share_date.month)
            monthly_share = MonthlyShare(share_date.year, share_date.month)
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
        return self.repository.get_monthly_share(year, month)

    def settle_monthly_share(self, year: int, month: int) -> MonthlyShare | None:
        """Marks a monthly share as settled"""
        monthly_share = self.repository.get_monthly_share(year, month)

        if monthly_share:
            print(f"Settleing monthly Share: {monthly_share.balances}\n")
            if monthly_share.balances:
                print("Balances found")
                monthly_share_balance: Dict[str, float] = monthly_share.balances
                max_key = max(monthly_share_balance, key=monthly_share_balance.get)  # type: ignore
                max_value = monthly_share_balance[max_key]

                # Retrieve the key that does not have the maximum value
                for key in monthly_share_balance:
                    if key != max_key:
                        other_key = key  # who owes
                        break

                if max_value > 0.0:
                    balancing_expense_split = {int(other_key): 0.0, int(max_key): 100.0}
                    category = Category()
                    category.name = "balance"

                    balancing_expense = Expense(
                        description="Balancing Expense",
                        amount=max_value,
                        date=date(year, month, 1),
                        category=category,
                        payer_id=int(other_key),
                        payment_type=PaymentType.DEBIT,
                        installments=1,
                        split_strategy=PercentageSplit(balancing_expense_split),
                    )
                    self.create_and_add_expense(balancing_expense)

            monthly_share.settle()
            print("---- SETTLING MONTHLY SHARE SETTLED -----")
            self.repository.settle_monthly_share(monthly_share.year, monthly_share.month)

            return monthly_share

        return None

    def add_member(self, member: Member) -> None:
        """Adds a new member and recalculates all active monthly shares"""
        self.members[member.id] = member

        # Recalculate balances for all active monthly shares
        monthly_shares = self.repository.get_all_monthly_shares()
        for monthly_share in monthly_shares.values():
            if not monthly_share.is_settled:
                monthly_share.recalculate_balances(self.members)
                self.repository.save_monthly_share(monthly_share)

    def update_expense(self, updated_expense: Expense):
        """Update the expense and recalculate balances"""
        self.repository.update_expense(updated_expense)

        # Fetch the monthly share associated with the expense
        monthly_share = self.get_monthly_balance(updated_expense.date.year, updated_expense.date.month)
        if monthly_share:  # Update the expense in the monthly share
            for i, expense in enumerate(monthly_share.expenses):
                if expense.id == updated_expense.id:  # Assuming Expense has an 'id' attribute
                    monthly_share.expenses[i] = updated_expense
                    break
            # Recalculate balances for the monthly share
            monthly_share.recalculate_balances(self.members)
            # Save the updated monthly share
            self.repository.save_monthly_share(monthly_share)

    # flake8: noqa: C901
    def update_credit_expense(self, updated_expense: Expense) -> Expense:
        """Update a credit expense and all its related installments."""
        print(f"\n=== Starting credit expense update process for ID: {updated_expense.id} ===")

        # Get all child expenses
        if updated_expense.id is None:
            raise ValueError("Expense ID cannot be None")
        child_expenses = self.repository.get_child_expenses(updated_expense.id)

        # Calculate amount per installment from the total amount
        amount_per_installment = updated_expense.amount / updated_expense.installments

        # Clean base description (remove any existing installment suffix)
        base_description = re.sub(r"\s*\(\d+\/\d+\)\s*$", "", updated_expense.description)

        # First, if we're reducing installments, delete the excess ones
        if updated_expense.installments < len(child_expenses):
            # Drop excess installments if the updated number is less
            # Start from updated_expense.installments since we're 0-based
            for i in range((len(child_expenses) + 1), updated_expense.installments, -1):  # TODO
                excess_child = child_expenses[i - 2]
                print(f"Deleting excess installment {i - 2}: {excess_child.description}")
                if excess_child.id is None:
                    raise ValueError("Expense ID cannot be None")
                self.repository.delete_expense(excess_child.id)

        # Update the first installment with the per-installment amount
        updated_expense.amount = amount_per_installment
        updated_expense.description = f"{base_description} (1/{updated_expense.installments})"
        self.repository.update_expense(updated_expense)

        # Update remaining child installments
        for i in range(updated_expense.installments - 1):  # -1 because first installment is already handled
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

        # Recalculate the monthly share for the first installment
        first_installment_date = updated_expense.date + relativedelta(months=1)
        monthly_share = self.get_monthly_balance(first_installment_date.year, first_installment_date.month)
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
        return self.repository.get_monthly_share(expense_date.year, expense_date.month)

    def recalculate_monthly_share(self, monthly_share: MonthlyShare) -> MonthlyShare:
        """Recalculate a monthly share - resolve balances."""
        monthly_share.recalculate_balances(self.members)
        self.repository.save_monthly_share(monthly_share)
        print("Monthly share recalculated")

        return monthly_share
