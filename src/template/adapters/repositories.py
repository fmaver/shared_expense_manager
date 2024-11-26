"""Repository adapter"""
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
        db_member = MemberModel(id=member.id, name=member.name, telephone=member.telephone)
        self.session.add(db_member)
        self.session.commit()
        return member

    def get(self, member_id: int) -> Optional[Member]:
        """Get a member by ID."""
        db_member = self.session.query(MemberModel).filter(MemberModel.id == member_id).first()
        if db_member:
            return Member(id=db_member.id, name=db_member.name, telephone=db_member.telephone)
        return None

    def list(self) -> List[Member]:
        """List all members."""
        db_members = self.session.query(MemberModel).all()
        return [Member(id=m.id, name=m.name, telephone=m.telephone) for m in db_members]


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
        monthly_share.is_settled = db_share.is_settled
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
