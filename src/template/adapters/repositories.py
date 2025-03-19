"""Repository implementations."""

from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from template.adapters.orm import ExpenseModel, MemberModel, MonthlyShareModel
from template.domain.models.category import Category
from template.domain.models.member import Member
from template.domain.models.models import Expense, MonthlyShare
from template.domain.models.repository import ExpenseRepository
from template.domain.models.split import EqualSplit, PercentageSplit
from template.domain.schemas.member import MemberUpdate


class MemberRepository:
    """Member repository"""

    def __init__(self, session: Session):
        """Initialize member repository."""
        self.session = session

    def add(self, member: Member) -> Member:
        """Add a member to the repository."""
        db_member = MemberModel(
            id=member.id,
            name=member.name,
            telephone=member.telephone,
            email=member.email,
            notification_preference=member.notification_preference,
        )
        self.session.add(db_member)
        self.session.commit()
        return member

    def get(self, member_id: int) -> Optional[Member]:
        """Get a member by ID."""
        db_member = self.session.query(MemberModel).filter(MemberModel.id == member_id).first()
        if db_member:
            return Member(
                id=db_member.id,
                name=db_member.name,
                telephone=db_member.telephone,
                email=db_member.email,
                notification_preference=db_member.notification_preference,
                last_wpp_chat_datetime=db_member.last_wpp_chat_datetime,
            )
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
                notification_preference=db_member.notification_preference,
                last_wpp_chat_datetime=db_member.last_wpp_chat_datetime,
            )
        return None

    def get_member_by_phone(self, phone: str) -> Optional[Member]:
        """Get a member by their phone number."""
        db_member = self.session.query(MemberModel).filter(MemberModel.telephone == phone).first()
        if db_member:
            return Member(
                id=db_member.id,
                name=db_member.name,
                telephone=db_member.telephone,
                email=db_member.email,
                notification_preference=db_member.notification_preference,
                last_wpp_chat_datetime=db_member.last_wpp_chat_datetime,
            )
        return None

    def update_last_wpp_chat(self, phone: str) -> Optional[Member]:
        """Update the last WhatsApp chat datetime for a member."""
        db_member = self.session.query(MemberModel).filter(MemberModel.telephone == phone).first()
        if not db_member:
            return None

        # Use timezone-aware UTC datetime
        db_member.last_wpp_chat_datetime = datetime.now(timezone.utc)
        self.session.commit()

        # print updated datetime
        print("Updated last_wpp_chat_datetime for member:", db_member.last_wpp_chat_datetime)

        return Member(
            id=db_member.id,
            name=db_member.name,
            telephone=db_member.telephone,
            email=db_member.email,
            notification_preference=db_member.notification_preference,
            last_wpp_chat_datetime=db_member.last_wpp_chat_datetime,
        )

    def get_last_wpp_chat_time(self, member: Member) -> Optional[datetime]:
        """Get the last WhatsApp chat datetime for a member."""
        db_member = self.session.query(MemberModel).filter(MemberModel.id == member.id).first()
        if not db_member:
            return None
        return db_member.last_wpp_chat_datetime

    def list(self) -> List[Member]:
        """List all members."""
        return [
            Member(
                id=m.id,
                name=m.name,
                telephone=m.telephone,
                email=m.email,
                notification_preference=m.notification_preference,
                last_wpp_chat_datetime=m.last_wpp_chat_datetime,
            )
            for m in self.session.query(MemberModel).all()
        ]

    def _should_update_chat_datetime(
        self, new_datetime: Optional[datetime], current_datetime: Optional[datetime]
    ) -> bool:
        """Check if the last WhatsApp chat datetime should be updated."""
        if not new_datetime:
            return False

        if not new_datetime.tzinfo:
            new_datetime = new_datetime.replace(tzinfo=timezone.utc)

        if not current_datetime:
            return True

        if not current_datetime.tzinfo:
            current_datetime = current_datetime.replace(tzinfo=timezone.utc)

        return new_datetime > current_datetime

    def update(self, member_id: int, update_data: MemberUpdate) -> Optional[Member]:
        """Update a member's information."""
        db_member = self.session.query(MemberModel).filter(MemberModel.id == member_id).first()
        if not db_member:
            return None

        print("Updating member with fields:")
        print(f"\tname: {update_data.name}")
        print(f"\ttelephone: {update_data.telephone}")
        print(f"\temail: {update_data.email}")
        print(f"\tnotification_preference: {update_data.notification_preference}")
        print(f"\tlast_wpp_chat_datetime: {update_data.last_wpp_chat_datetime}")

        # Update only the fields that are provided
        if update_data.name is not None:
            db_member.name = update_data.name
        if update_data.telephone is not None:
            db_member.telephone = update_data.telephone
        if update_data.email is not None:
            db_member.email = update_data.email
        if update_data.notification_preference is not None:
            db_member.notification_preference = update_data.notification_preference
        if update_data.last_wpp_chat_datetime is not None:
            if self._should_update_chat_datetime(update_data.last_wpp_chat_datetime, db_member.last_wpp_chat_datetime):
                db_member.last_wpp_chat_datetime = update_data.last_wpp_chat_datetime

        self.session.commit()
        return Member(
            id=db_member.id,
            name=db_member.name,
            telephone=db_member.telephone,
            email=db_member.email,
            notification_preference=db_member.notification_preference,
            last_wpp_chat_datetime=db_member.last_wpp_chat_datetime,
        )


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
            parent_expense_id=expense.parent_expense_id,
        )
        self.session.add(db_expense)
        self.session.commit()
        expense.id = db_expense.id
        print(f"Successfully saved expense with ID: {expense.id}")

    def get_expense(self, expense_id: int) -> Optional[Expense]:
        """Get an expense by ID from the database."""
        db_expense = self.session.query(ExpenseModel).filter_by(id=expense_id).first()
        if not db_expense:
            return None
        return self._to_domain_expense(db_expense)

    def get_child_expenses(self, parent_expense_id: int) -> List[Expense]:
        """Get all child expenses for a given parent expense ID."""
        db_expenses = self.session.query(ExpenseModel).filter_by(parent_expense_id=parent_expense_id).all()
        return [self._to_domain_expense(db_expense) for db_expense in db_expenses]

    def get_parent_expense(self, expense_id: int) -> Optional[Expense]:
        """Get the parent expense for a given expense ID."""
        # First get the expense to check its parent_expense_id
        db_expense = self.session.query(ExpenseModel).filter_by(id=expense_id).first()
        if not db_expense or not db_expense.parent_expense_id:
            return None

        # Now get the parent expense
        parent_expense = self.session.query(ExpenseModel).filter_by(id=db_expense.parent_expense_id).first()

        return self._to_domain_expense(parent_expense) if parent_expense else None

    def delete_expense(self, expense_id: int) -> None:
        """Delete an expense from the database."""
        print(f"Deleting expense with ID: {expense_id}")
        expense = self.session.query(ExpenseModel).filter_by(id=expense_id).first()
        if expense:
            self.session.delete(expense)
            self.session.commit()
            print(f"Successfully deleted expense with ID: {expense_id}")

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

        # Fetch the existing expense from the database
        db_expense = self.session.query(ExpenseModel).filter(ExpenseModel.id == expense.id).first()
        if not db_expense:
            raise ValueError(f"Expense with ID {expense.id} not found.")
        print(f"Updating expense {db_expense.description} (ID: {db_expense.id}) as {expense.description}")

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

    def _to_domain_expense(self, db_expense: ExpenseModel) -> Expense:
        """Convert database model to domain model."""
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
            parent_expense_id=db_expense.parent_expense_id,
        )
