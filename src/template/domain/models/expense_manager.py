"""Expense manager"""

import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from dateutil.relativedelta import relativedelta

from template.domain.models.category import Category
from template.domain.models.split import PercentageSplit

from .enums import PaymentType
from .models import Expense, Member, MonthlyShare
from .repository import ExpenseRepository


def compute_debt_transfers(balances: Dict[str, float]) -> List[Tuple[int, int, float]]:
    """Return the minimum list of (debtor_id, creditor_id, amount) transfers to clear all balances."""
    epsilon = 0.01
    remaining_credit: Dict[int, float] = {int(mid): amt for mid, amt in balances.items() if amt > epsilon}
    remaining_debt: Dict[int, float] = {int(mid): -amt for mid, amt in balances.items() if amt < -epsilon}
    result: List[Tuple[int, int, float]] = []

    while remaining_credit and remaining_debt:
        creditor_id = max(remaining_credit, key=lambda k: remaining_credit[k])
        debtor_id = max(remaining_debt, key=lambda k: remaining_debt[k])
        pay = round(min(remaining_credit[creditor_id], remaining_debt[debtor_id]), 2)
        if pay < epsilon:
            break
        result.append((debtor_id, creditor_id, pay))
        remaining_credit[creditor_id] -= pay
        remaining_debt[debtor_id] -= pay
        if remaining_credit[creditor_id] < epsilon:
            del remaining_credit[creditor_id]
        if remaining_debt[debtor_id] < epsilon:
            del remaining_debt[debtor_id]

    return result


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
        category = Category()
        category.name = "balance"

        for debtor_id, creditor_id, pay in compute_debt_transfers(monthly_share.balances):
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

    def _share_period_for_installment(self, purchase_date: date, installment_no: int) -> date:
        """Return a date inside the monthly share that a given installment belongs to.

        Credit payments start the month after the purchase, so cuota k falls in
        purchase month + k.
        """
        return purchase_date + relativedelta(months=installment_no)

    def _move_expense_to_share(self, expense: Expense, share_date: date) -> None:
        """Point an existing expense row at the share for share_date, creating it if needed."""
        if expense.id is None:
            raise ValueError("Cannot reassign an expense without an ID")
        monthly_share = self.get_monthly_balance(share_date.year, share_date.month)
        if not monthly_share:
            monthly_share = MonthlyShare(share_date.year, share_date.month, self.group_id)
            self.repository.save_monthly_share(monthly_share)
            monthly_share = self.get_monthly_balance(share_date.year, share_date.month)
            if not monthly_share:
                raise ValueError("Failed to create monthly share")
        self.repository.reassign_expense_to_monthly_share(expense.id, share_date.year, share_date.month, self.group_id)
        # Keep the in-memory share consistent with the FK we just moved.
        if all(existing.id != expense.id for existing in monthly_share.expenses):
            monthly_share.expenses.append(expense)

    def _shares_holding_family(self, parent_id: int, child_ids: set[int]) -> list[MonthlyShare]:
        """Return every monthly share currently holding the parent or one of its children.

        Used to recalculate the months an installment is about to leave.
        """
        family = {parent_id} | child_ids
        return [
            share
            for share in self.repository.get_all_monthly_shares(self.group_id).values()
            if any(expense.id in family for expense in share.expenses)
        ]

    def update_credit_expense(self, updated_expense: Expense) -> Expense:
        """Update a credit expense and rebuild its installment rows.

        The parent row *is* installment 1: it is updated in place so its ID survives an
        edit. Installments 2..N are deleted and rebuilt, which is what makes this correct
        rather than merely tidier — deriving each row's number, amount and month from the
        loop counter means the result cannot depend on the order the database happens to
        return existing children in, and every row is explicitly assigned to a share.

        Every installment row stores the purchase date; the month it falls in comes from
        its monthly share, not from `date`.
        """
        if updated_expense.id is None:
            raise ValueError("Expense ID cannot be None")

        parent_id = updated_expense.id
        installments = updated_expense.installments
        amount_per_installment = updated_expense.amount / installments
        base_description = re.sub(r"\s*\(\d+\/\d+\)\s*$", "", updated_expense.description)

        existing_children = self.repository.get_child_expenses(parent_id)
        child_ids = {child.id for child in existing_children if child.id is not None}

        # Capture the months this family occupies before anything moves, so the ones it
        # vacates get their balances recalculated too.
        stale_shares = self._shares_holding_family(parent_id, child_ids)

        # Drop every child; cuotas 2..N are rebuilt below from the loop counter.
        for child_id in child_ids:
            self.repository.delete_expense(child_id)

        # Installment 1 — update the parent row in place and move it to its new month.
        updated_expense.amount = amount_per_installment
        updated_expense.description = f"{base_description} (1/{installments})"
        updated_expense.installment_no = 1
        self.repository.update_expense(updated_expense)
        self._move_expense_to_share(updated_expense, self._share_period_for_installment(updated_expense.date, 1))

        # Installments 2..N — rebuilt so number, amount and month always agree.
        for installment_no in range(2, installments + 1):
            self._add_to_monthly_share(
                Expense(
                    description=f"{base_description} ({installment_no}/{installments})",
                    amount=amount_per_installment,
                    date=updated_expense.date,
                    category=updated_expense.category,
                    payer_id=updated_expense.payer_id,
                    payment_type=updated_expense.payment_type,
                    installments=installments,
                    installment_no=installment_no,
                    split_strategy=updated_expense.split_strategy,
                    parent_expense_id=parent_id,
                    currency=getattr(updated_expense, "currency", "ARS") or "ARS",
                ),
                self._share_period_for_installment(updated_expense.date, installment_no),
            )

        # Recalculate every month the family touched — vacated and newly occupied alike.
        periods = {(share.year, share.month) for share in stale_shares} | {
            (
                self._share_period_for_installment(updated_expense.date, no).year,
                self._share_period_for_installment(updated_expense.date, no).month,
            )
            for no in range(1, installments + 1)
        }
        for year, month in sorted(periods):
            monthly_share = self.get_monthly_balance(year, month)
            if monthly_share:
                self.recalculate_monthly_share(monthly_share)

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
        # pylint: disable=import-outside-toplevel
        from template.service_layer.currency_service import get_blue_rate

        # pylint: enable=import-outside-toplevel
        usd_rate = get_blue_rate() or 1.0
        monthly_share.recalculate_balances(self.members, usd_rate=usd_rate)
        self.repository.save_monthly_share(monthly_share)
        print("Monthly share recalculated")

        return monthly_share
