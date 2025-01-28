"""Repository adapter"""
from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from template.adapters.orm import ExpenseModel, MemberModel, MonthlyShareModel
from template.domain.models.category import Category
from template.domain.models.member import Member
from template.domain.models.models import Expense, MonthlyShare
from template.domain.models.repository import ExpenseRepository
from template.domain.models.split import EqualSplit, PercentageSplit


class MemberRepository:
    """Member repository"""

    def __init__(self, session: Session):
        """Initialize member repository."""
        self.session = session

    def add(self, member: Member) -> Member:
        """Add a member to the repository."""
        db_member = MemberModel(id=member.id, name=member.name, telephone=member.telephone, email=member.email)
        self.session.add(db_member)
        self.session.commit()
        return member

    def get(self, member_id: int) -> Optional[Member]:
        """Get a member by ID."""
        db_member = self.session.query(MemberModel).filter(MemberModel.id == member_id).first()
        if db_member:
            return Member(id=db_member.id, name=db_member.name, telephone=db_member.telephone, email=db_member.email)
        return None

    def get_member_by_email(self, email: str) -> Optional[Member]:
        """Get a member by their email address."""
        db_member = self.session.query(MemberModel).filter(MemberModel.email == email).first()
        if db_member:
            return Member(
                id=db_member.id,
                name=db_member.name,
                telephone=db_member.telephone,
                email=db_member.email,
                hashed_password=db_member.hashed_password,
            )
        return None

    def list(self) -> List[Member]:
        """List all members."""
        db_members = self.session.query(MemberModel).all()
        return [Member(id=m.id, name=m.name, telephone=m.telephone, email=m.email) for m in db_members]


class SQLAlchemyExpenseRepository(ExpenseRepository):
    """SQLAlchemy implementation of the ExpenseRepository interface."""

    def __init__(self, session: Session):
        """Initialize SQLAlchemy expense repository."""
        self.session = session

    def save_monthly_share(self, monthly_share: MonthlyShare) -> None:
        """Save a monthly share and its expenses to the database."""
        print(f"\nSaving monthly share for {monthly_share.year}-{monthly_share.month}")
        print(f"Current balances: {monthly_share.balances}")

        # Find existing or create new monthly share
        db_monthly_share = (
            self.session.query(MonthlyShareModel)
            .filter(MonthlyShareModel.year == monthly_share.year, MonthlyShareModel.month == monthly_share.month)
            .first()
        )

        if not db_monthly_share:
            db_monthly_share = MonthlyShareModel(
                year=monthly_share.year,
                month=monthly_share.month,
                balances=monthly_share.balances,
                is_settled=monthly_share.is_settled,
            )
            self.session.add(db_monthly_share)
            self.session.flush()
        else:
            # Update existing monthly share
            db_monthly_share.balances = monthly_share.balances
            db_monthly_share.is_settled = monthly_share.is_settled

        # Save expenses
        for expense in monthly_share.expenses:
            if not expense.id:  # New expense
                self.add(expense, db_monthly_share.id)

        self.session.commit()
        print(f"Saved monthly share with balances: {db_monthly_share.balances}")

    def settle_monthly_share(self, year: int, month: int) -> None:
        """Settle a monthly share by year and month."""
        print(f"Settling monthly share for {year}-{month}")

        # Fetch the existing monthly share
        db_monthly_share = (
            self.session.query(MonthlyShareModel)
            .filter(MonthlyShareModel.year == year, MonthlyShareModel.month == month)
            .first()
        )

        if not db_monthly_share:
            raise ValueError(f"Monthly share for {year}-{month} not found.")

        # Update the is_settled status
        db_monthly_share.is_settled = True

        # Commit the changes to the database
        self.session.commit()
        print(f"Monthly share for {year}-{month} has been settled.")

    def get_monthly_share(self, year: int, month: int) -> Optional[MonthlyShare]:
        """Get a monthly share by year and month from the database."""
        db_monthly_share = (
            self.session.query(MonthlyShareModel)
            .filter(MonthlyShareModel.year == year, MonthlyShareModel.month == month)
            .first()
        )

        if not db_monthly_share:
            return None

        return self._to_domain_monthly_share(db_monthly_share)

    def get_all_monthly_shares(self) -> Dict[str, MonthlyShare]:
        """Get all monthly shares from the database."""
        db_monthly_shares = self.session.query(MonthlyShareModel).all()

        return {f"{share.year}-{share.month:02d}": self._to_domain_monthly_share(share) for share in db_monthly_shares}

    def _to_domain_monthly_share(self, db_share: MonthlyShareModel) -> MonthlyShare:
        """Convert database model to domain model."""
        monthly_share = MonthlyShare(db_share.year, db_share.month)
        if db_share.is_settled:
            monthly_share.settle()
        else:
            monthly_share.unsettle()
        monthly_share.balances = db_share.balances

        # Convert expenses
        for db_expense in db_share.expenses:
            category = Category()
            category.name = db_expense.category

            split_strategy = self._deserialize_split_strategy(db_expense.split_strategy)

            expense = Expense(
                id=db_expense.id,
                description=db_expense.description,
                amount=db_expense.amount,
                date=db_expense.date,
                category=category,
                payer_id=db_expense.payer_id,
                payment_type=db_expense.payment_type,
                installments=db_expense.installments,
                installment_no=db_expense.installment_no,
                split_strategy=split_strategy,
            )
            monthly_share.expenses.append(expense)

        return monthly_share

    def _serialize_split_strategy(self, strategy) -> dict:
        """Convert split strategy to JSON-serializable format."""
        if isinstance(strategy, EqualSplit):
            return {"type": "equal"}
        if isinstance(strategy, PercentageSplit):
            return {"type": "percentage", "percentages": strategy.percentages}
        raise ValueError(f"Unknown split strategy type: {type(strategy)}")

    def _deserialize_split_strategy(self, data: dict):
        """Convert JSON data back to split strategy object."""
        if data["type"] == "equal":
            return EqualSplit()
        if data["type"] == "percentage":
            return PercentageSplit(data["percentages"])
        raise ValueError(f"Unknown split strategy type: {data['type']}")

    def add(self, expense: Expense, monthly_share_id: int) -> None:
        """Save an expense to the database."""
        print(f"Saving expense: {expense.description} (Amount: {expense.amount}) to monthly share {monthly_share_id}")
        db_expense = ExpenseModel(
            description=expense.description,
            amount=expense.amount,
            date=expense.date,
            category=expense.category.name,
            payer_id=expense.payer_id,
            payment_type=expense.payment_type,
            installments=expense.installments,
            installment_no=expense.installment_no,
            split_strategy=self._serialize_split_strategy(expense.split_strategy),
            monthly_share_id=monthly_share_id,
        )
        self.session.add(db_expense)
        self.session.commit()
        expense.id = db_expense.id
        print(f"Successfully saved expense with ID: {expense.id}")

    def get_expense(self, expense_id: int) -> Optional[Expense]:
        """Get an expense by ID from the database."""
        print("finding the expense...")
        db_expense = self.session.query(ExpenseModel).filter(ExpenseModel.id == expense_id).first()
        if not db_expense:
            print("didn't find the expense")
            return None

        print("found the expense")
        # Convert the database model to the domain model
        category = Category()
        category.name = db_expense.category

        split_strategy = self._deserialize_split_strategy(db_expense.split_strategy)

        return Expense(
            id=db_expense.id,
            description=db_expense.description,
            amount=db_expense.amount,
            date=db_expense.date,
            category=category,
            payer_id=db_expense.payer_id,
            payment_type=db_expense.payment_type,
            installments=db_expense.installments,
            installment_no=db_expense.installment_no,
            split_strategy=split_strategy,
        )

    def delete_expense(self, expense_to_delete: Expense) -> None:
        """Delete an expense by ID from the database."""
        db_expense = self.session.query(ExpenseModel).filter(ExpenseModel.id == expense_to_delete.id).first()
        if not db_expense:
            raise ValueError(f"Expense with ID {expense_to_delete.id} not found.")

        self.session.delete(db_expense)
        self.session.commit()

    def get_expenses_by_date(self, specific_date: date) -> List[Expense]:
        """Get all expenses for a specific date."""
        db_expenses = self.session.query(ExpenseModel).filter(ExpenseModel.date == specific_date).all()

        return [
            Expense(
                id=db_expense.id,
                description=db_expense.description,
                amount=db_expense.amount,
                date=db_expense.date,
                category=Category(name=db_expense.category),
                payer_id=db_expense.payer_id,
                payment_type=db_expense.payment_type,
                installments=db_expense.installments,
                installment_no=db_expense.installment_no,
                split_strategy=self._deserialize_split_strategy(db_expense.split_strategy),
            )
            for db_expense in db_expenses
        ]

    def update_expense(self, expense: Expense) -> None:
        """Update an existing expense in the database."""
        print(f"Updating expense: {expense.description} (ID: {expense.id})")

        # Fetch the existing expense from the database
        db_expense = self.session.query(ExpenseModel).filter(ExpenseModel.id == expense.id).first()
        if not db_expense:
            raise ValueError(f"Expense with ID {expense.id} not found.")

        # Update the fields of the existing expense
        db_expense.description = expense.description
        db_expense.amount = expense.amount
        db_expense.date = expense.date
        db_expense.category = expense.category.name
        db_expense.payer_id = expense.payer_id
        db_expense.payment_type = expense.payment_type
        db_expense.installments = expense.installments
        db_expense.installment_no = expense.installment_no
        db_expense.split_strategy = self._serialize_split_strategy(expense.split_strategy)

        # Commit the changes to the database
        self.session.commit()
        print(f"Successfully updated expense with ID: {expense.id}")
