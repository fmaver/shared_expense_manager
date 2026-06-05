"""Repository implementations."""

# pylint: disable=too-many-lines

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from template.adapters.orm import (
    ChatSessionModel,
    ExpenseModel,
    GroupJoinLinkModel,
    GroupMembershipModel,
    GroupModel,
    IncomeInstanceModel,
    InvitationModel,
    MemberModel,
    MonthlyShareModel,
    ProcessedMessageModel,
    RecurringGroupExpenseInstanceModel,
    RecurringGroupExpenseModel,
    RecurringIncomeModel,
    RecurringPersonalExpenseInstanceModel,
    RecurringPersonalExpenseModel,
)
from template.domain.models.category import Category
from template.domain.models.enums import (
    InvitationChannel,
    InvitationStatus,
    NotificationType,
)
from template.domain.models.group import Group, GroupStatus, GroupType
from template.domain.models.income import (
    IncomeInstance,
    RecurringIncome,
    RecurringPersonalExpense,
    RecurringPersonalExpenseInstance,
)
from template.domain.models.member import Member
from template.domain.models.models import Expense, MonthlyShare
from template.domain.models.repository import ExpenseRepository
from template.domain.models.split import EqualSplit, ExactAmountsSplit, PercentageSplit
from template.domain.schemas.expense import (
    RecurringGroupExpenseCreate,
    RecurringGroupExpenseResponse,
    RecurringGroupExpenseUpdate,
    SplitStrategySchema,
)
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
        return self._to_domain(db_member) if db_member else None

    def get_member_by_email(self, email: str) -> Optional[Member]:
        """Get a member by their email address."""
        db_member = self.session.query(MemberModel).filter(MemberModel.email == email).first()
        return self._to_domain(db_member) if db_member else None

    def get_member_by_phone(self, phone: str) -> Optional[Member]:
        """Get a member by their phone number."""
        db_member = self.session.query(MemberModel).filter(MemberModel.telephone == phone).first()
        if db_member:
            return self._to_domain(db_member)
        return None

    def create_stub(self, name: str, email: Optional[str] = None, telephone: Optional[str] = None) -> Member:
        """Create a stub member with no password. At least one of email or telephone must be provided."""
        db_member = MemberModel(
            name=name,
            email=email,
            telephone=telephone,
            hashed_password=None,
            notification_preference=NotificationType.NONE,
        )
        self.session.add(db_member)
        self.session.commit()
        self.session.refresh(db_member)
        return self._to_domain(db_member)

    def claim_stub(self, member_id: int, email: str, password_hash: str) -> Member:
        """Set email and password on a stub member, making them a full account."""
        db_member = self.session.query(MemberModel).filter(MemberModel.id == member_id).first()
        if not db_member:
            raise ValueError(f"Member {member_id} not found")
        if db_member.hashed_password:
            raise ValueError("Member already has a password")
        db_member.email = email
        db_member.hashed_password = password_hash
        self.session.commit()
        self.session.refresh(db_member)
        return self._to_domain(db_member)

    def mark_phone_verified(self, member_id: int) -> Member:
        """Set phone_verified_at to now for the given member."""
        db_member = self.session.query(MemberModel).filter(MemberModel.id == member_id).first()
        if not db_member:
            raise ValueError(f"Member {member_id} not found")
        db_member.phone_verified_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(db_member)
        return self._to_domain(db_member)

    def _to_domain(self, db_member: MemberModel) -> Member:
        """Convert ORM model to domain Member."""
        return Member(
            id=db_member.id,
            name=db_member.name,
            telephone=db_member.telephone,
            email=db_member.email,
            hashed_password=db_member.hashed_password,
            phone_verified_at=db_member.phone_verified_at,
            notification_preference=db_member.notification_preference,
            last_wpp_chat_datetime=db_member.last_wpp_chat_datetime,
        )

    def update_last_wpp_chat(self, phone: str) -> Optional[Member]:
        """Update the last WhatsApp chat datetime for a member."""
        db_member = self.session.query(MemberModel).filter(MemberModel.telephone == phone).first()
        if not db_member:
            return None
        db_member.last_wpp_chat_datetime = datetime.now(timezone.utc)
        self.session.commit()
        print("Updated last_wpp_chat_datetime for member:", db_member.last_wpp_chat_datetime)
        return self._to_domain(db_member)

    def get_last_wpp_chat_time(self, member: Member) -> Optional[datetime]:
        """Get the last WhatsApp chat datetime for a member."""
        db_member = self.session.query(MemberModel).filter(MemberModel.id == member.id).first()
        if not db_member:
            return None
        return db_member.last_wpp_chat_datetime

    def list(self) -> List[Member]:
        """List all members."""
        return [self._to_domain(m) for m in self.session.query(MemberModel).all()]

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
        return self._to_domain(db_member)


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
            .filter(
                MonthlyShareModel.year == monthly_share.year,
                MonthlyShareModel.month == monthly_share.month,
                MonthlyShareModel.group_id == monthly_share.group_id,
            )
            .first()
        )

        if not db_monthly_share:
            db_monthly_share = MonthlyShareModel(
                year=monthly_share.year,
                month=monthly_share.month,
                group_id=monthly_share.group_id,
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
                self.add(expense, db_monthly_share.id, db_monthly_share.group_id)

        self.session.commit()
        print(f"Saved monthly share with balances: {db_monthly_share.balances}")

    def settle_monthly_share(self, year: int, month: int, group_id: int) -> None:
        """Settle a monthly share by year, month and group."""
        db_monthly_share = (
            self.session.query(MonthlyShareModel)
            .filter(
                MonthlyShareModel.year == year,
                MonthlyShareModel.month == month,
                MonthlyShareModel.group_id == group_id,
            )
            .first()
        )

        if not db_monthly_share:
            raise ValueError(f"Monthly share for {year}-{month} group {group_id} not found.")

        db_monthly_share.is_settled = True
        self.session.commit()

    def unsettle_monthly_share(self, year: int, month: int, group_id: int) -> None:
        """Remove settlement: delete all 'balance' expenses and mark as unsettled."""
        db_monthly_share = (
            self.session.query(MonthlyShareModel)
            .filter(
                MonthlyShareModel.year == year,
                MonthlyShareModel.month == month,
                MonthlyShareModel.group_id == group_id,
            )
            .first()
        )

        if not db_monthly_share:
            raise ValueError(f"Monthly share for {year}-{month} group {group_id} not found.")

        for expense in list(db_monthly_share.expenses):
            if expense.category == "balance":
                self.session.delete(expense)

        db_monthly_share.is_settled = False
        self.session.commit()

    def get_monthly_share(self, year: int, month: int, group_id: int) -> Optional[MonthlyShare]:
        """Get a monthly share by year, month and group from the database."""
        db_monthly_share = (
            self.session.query(MonthlyShareModel)
            .filter(
                MonthlyShareModel.year == year,
                MonthlyShareModel.month == month,
                MonthlyShareModel.group_id == group_id,
            )
            .first()
        )

        if not db_monthly_share:
            return None

        return self._to_domain_monthly_share(db_monthly_share)

    def get_all_monthly_shares(self, group_id: int) -> Dict[str, MonthlyShare]:
        """Get all monthly shares for a group from the database."""
        db_monthly_shares = self.session.query(MonthlyShareModel).filter(MonthlyShareModel.group_id == group_id).all()

        return {f"{share.year}-{share.month:02d}": self._to_domain_monthly_share(share) for share in db_monthly_shares}

    def _to_domain_monthly_share(self, db_share: MonthlyShareModel) -> MonthlyShare:
        """Convert database model to domain model."""
        monthly_share = MonthlyShare(db_share.year, db_share.month, db_share.group_id)
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
            payload: dict = {"type": "equal"}
            if strategy.participant_ids is not None:
                payload["participant_ids"] = strategy.participant_ids
            return payload
        if isinstance(strategy, PercentageSplit):
            return {"type": "percentage", "percentages": strategy.percentages}
        if isinstance(strategy, ExactAmountsSplit):
            return {"type": "exact", "amounts": strategy.amounts}
        raise ValueError(f"Unknown split strategy type: {type(strategy)}")

    def _deserialize_split_strategy(self, data: dict):
        """Convert JSON data back to split strategy object."""
        if data["type"] == "equal":
            return EqualSplit(participant_ids=data.get("participant_ids"))
        if data["type"] == "percentage":
            return PercentageSplit(data["percentages"])
        if data["type"] == "exact":
            return ExactAmountsSplit(data["amounts"])
        raise ValueError(f"Unknown split strategy type: {data['type']}")

    def add(self, expense: Expense, monthly_share_id: int, group_id: int) -> None:
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
            group_id=group_id,
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

    def reassign_expense_to_monthly_share(self, expense_id: int, year: int, month: int, group_id: int) -> None:
        """Move an expense to the monthly share identified by group/year/month."""
        db_expense = self.session.query(ExpenseModel).filter(ExpenseModel.id == expense_id).first()
        if not db_expense:
            raise ValueError(f"Expense with ID {expense_id} not found.")
        db_share = (
            self.session.query(MonthlyShareModel)
            .filter(
                MonthlyShareModel.year == year,
                MonthlyShareModel.month == month,
                MonthlyShareModel.group_id == group_id,
            )
            .first()
        )
        if not db_share:
            raise ValueError(f"Monthly share for {year}-{month} group {group_id} not found.")
        db_expense.monthly_share_id = db_share.id
        self.session.commit()

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

    def find_similar_expenses(  # pylint: disable=too-many-arguments, too-many-positional-arguments
        self, group_id: int, year: int, month: int, amount: float, description: str, expense_date: date
    ) -> List[Expense]:
        """Find parent expenses in the same group/month that share amount + description or amount + date."""
        normalized = description.strip().lower()
        db_expenses = (
            self.session.query(ExpenseModel)
            .join(MonthlyShareModel, ExpenseModel.monthly_share_id == MonthlyShareModel.id)
            .filter(
                ExpenseModel.group_id == group_id,
                MonthlyShareModel.year == year,
                MonthlyShareModel.month == month,
                ExpenseModel.amount == amount,
                ExpenseModel.installment_no == 1,
                or_(
                    func.lower(ExpenseModel.description) == normalized,
                    ExpenseModel.date == expense_date,
                ),
            )
            .all()
        )
        return [self._to_domain_expense(e) for e in db_expenses]


_DEFAULT_EXPENSE_DATA: Dict = {
    "service": None,
    "description": None,
    "amount": None,
    "date": None,
    "category": None,
    "payer_id": None,
    "payment_type": None,
    "installments": 1,
    "split_strategy": None,
}


# Top-level keys on the estado dict that are NOT part of expense_data but must survive
# across requests.  We serialise them into expense_data with a "_sess_" prefix so no
# DB migration is required.
_SESSION_TOPLEVEL_KEYS = ("group_id", "known_group_ids", "pending_invitation_token")


class ChatSessionRepository:
    """Persists chatbot conversation state keyed by telephone number."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create(self, telephone: str) -> Dict:
        """Return the current session state dict, creating a default one if absent."""
        row = self.session.get(ChatSessionModel, telephone)
        if row is None:
            return {"estado": "inicial", "expense_data": dict(_DEFAULT_EXPENSE_DATA)}

        raw = dict(row.expense_data or _DEFAULT_EXPENSE_DATA)

        # Separate session-level keys from expense-level keys
        session_extras: Dict = {}
        expense_data: Dict = {}
        for k, v in raw.items():
            if k.startswith("_sess_"):
                session_extras[k[len("_sess_") :]] = v  # noqa: E203
            else:
                expense_data[k] = v

        result: Dict = {"estado": row.estado, "expense_data": expense_data or dict(_DEFAULT_EXPENSE_DATA)}
        result.update(session_extras)
        return result

    def save(self, telephone: str, state: Dict) -> None:
        """Upsert the session state for telephone."""
        expense_data = dict(state.get("expense_data") or _DEFAULT_EXPENSE_DATA)

        # Persist top-level session keys alongside expense data
        for key in _SESSION_TOPLEVEL_KEYS:
            if key in state and state[key] is not None:
                expense_data[f"_sess_{key}"] = state[key]
            else:
                expense_data.pop(f"_sess_{key}", None)

        row = self.session.get(ChatSessionModel, telephone)
        if row is None:
            row = ChatSessionModel(
                telephone=telephone,
                estado=state["estado"],
                expense_data=expense_data,
                updated_at=datetime.utcnow(),
            )
            self.session.add(row)
        else:
            row.estado = state["estado"]
            row.expense_data = expense_data
            row.updated_at = datetime.utcnow()
        self.session.commit()


class ProcessedMessageRepository:
    """Tracks processed WhatsApp message IDs to deduplicate webhook retries."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def mark_if_new(self, message_id: str) -> bool:
        """Insert message_id if not already present. Returns True if new, False if duplicate."""
        self._cleanup_old()
        existing = self.session.get(ProcessedMessageModel, message_id)
        if existing is not None:
            return False
        self.session.add(ProcessedMessageModel(message_id=message_id, processed_at=datetime.utcnow()))
        self.session.commit()
        return True

    def _cleanup_old(self) -> None:
        """Delete entries older than 24 hours to keep the table small."""
        cutoff = datetime.utcnow() - timedelta(hours=24)
        self.session.query(ProcessedMessageModel).filter(ProcessedMessageModel.processed_at < cutoff).delete()
        self.session.commit()


class GroupRepository:
    """Manages groups and group memberships."""

    def __init__(self, session: Session):
        """Initialize group repository."""
        self.session = session

    def create(
        self, name: str, group_type: GroupType = GroupType.REGULAR, owner_member_id: Optional[int] = None
    ) -> Group:
        """Create a new active group."""
        model = GroupModel(name=name, status="active", group_type=group_type.value, owner_member_id=owner_member_id)
        self.session.add(model)
        self.session.flush()
        self.session.commit()
        return self._to_domain(model)

    def get(self, group_id: int) -> Optional[Group]:
        """Return a group by ID, or None if not found or deleted."""
        model = self.session.query(GroupModel).filter(GroupModel.id == group_id, GroupModel.status != "deleted").first()
        return self._to_domain(model) if model else None

    def get_personal_for_owner(self, member_id: int) -> Optional[Group]:
        """Return the personal group for the given owner, or None if it doesn't exist yet."""
        model = (
            self.session.query(GroupModel)
            .filter(
                GroupModel.owner_member_id == member_id,
                GroupModel.group_type == GroupType.PERSONAL.value,
                GroupModel.status != "deleted",
            )
            .first()
        )
        return self._to_domain(model) if model else None

    def list_for_member(self, member_id: int, include_personal: bool = False) -> list[Group]:
        """Return all active groups the member belongs to."""
        query = (
            self.session.query(GroupModel)
            .join(GroupMembershipModel, GroupModel.id == GroupMembershipModel.group_id)
            .filter(
                GroupMembershipModel.member_id == member_id,
                GroupModel.status == "active",
            )
        )
        if not include_personal:
            query = query.filter(GroupModel.group_type != GroupType.PERSONAL.value)
        return [self._to_domain(m) for m in query.all()]

    def update_name(self, group_id: int, name: str) -> Group:
        """Rename a group."""
        model = self.session.query(GroupModel).filter(GroupModel.id == group_id).first()
        if not model:
            raise ValueError(f"Group {group_id} not found")
        model.name = name
        self.session.flush()
        self.session.commit()
        return self._to_domain(model)

    def set_status(self, group_id: int, status: GroupStatus) -> Group:
        """Set the status of a group (active, closed, deleted)."""
        model = self.session.query(GroupModel).filter(GroupModel.id == group_id).first()
        if not model:
            raise ValueError(f"Group {group_id} not found")
        model.status = status.value
        self.session.flush()
        self.session.commit()
        return self._to_domain(model)

    def add_member(self, group_id: int, member_id: int) -> None:
        """Add a member to a group (idempotent)."""
        group_model = self.session.query(GroupModel).filter(GroupModel.id == group_id).first()
        if group_model and group_model.group_type == GroupType.PERSONAL.value:
            # Idempotency check: if this exact member is already in, return silently
            existing = (
                self.session.query(GroupMembershipModel)
                .filter(
                    GroupMembershipModel.group_id == group_id,
                    GroupMembershipModel.member_id == member_id,
                )
                .first()
            )
            if existing:
                return
            # For personal groups, the DB's uq_group_member constraint enforces single-member;
            # if a race causes a duplicate attempt, re-raise as a domain error
            try:
                self.session.add(GroupMembershipModel(group_id=group_id, member_id=member_id))
                self.session.flush()
                self.session.commit()
            except IntegrityError as exc:
                self.session.rollback()
                raise ValueError(f"Cannot add a second member to personal group {group_id}") from exc
            return
        existing = (
            self.session.query(GroupMembershipModel)
            .filter(
                GroupMembershipModel.group_id == group_id,
                GroupMembershipModel.member_id == member_id,
            )
            .first()
        )
        if not existing:
            self.session.add(GroupMembershipModel(group_id=group_id, member_id=member_id))
            self.session.flush()
            self.session.commit()

    def remove_member(self, group_id: int, member_id: int) -> None:
        """Remove a member from a group."""
        self.session.query(GroupMembershipModel).filter(
            GroupMembershipModel.group_id == group_id,
            GroupMembershipModel.member_id == member_id,
        ).delete()
        self.session.flush()
        self.session.commit()

    def list_members(self, group_id: int) -> list[Member]:
        """Return all members of a group as domain Member objects."""
        members = (
            self.session.query(MemberModel)
            .join(GroupMembershipModel, MemberModel.id == GroupMembershipModel.member_id)
            .filter(GroupMembershipModel.group_id == group_id)
            .all()
        )
        return [
            Member(
                id=m.id,
                name=m.name,
                telephone=m.telephone,
                email=m.email,
                hashed_password=m.hashed_password,
                phone_verified_at=m.phone_verified_at,
                notification_preference=m.notification_preference,
                last_wpp_chat_datetime=m.last_wpp_chat_datetime,
            )
            for m in members
        ]

    def is_member(self, group_id: int, member_id: int) -> bool:
        """Return True if member_id belongs to group_id."""
        return (
            self.session.query(GroupMembershipModel)
            .filter(
                GroupMembershipModel.group_id == group_id,
                GroupMembershipModel.member_id == member_id,
            )
            .first()
            is not None
        )

    def _to_domain(self, model: GroupModel) -> Group:
        """Convert ORM GroupModel to domain Group."""
        return Group(
            id=model.id,
            name=model.name,
            status=GroupStatus(model.status),
            group_type=GroupType(model.group_type),
            owner_member_id=model.owner_member_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class InvitationRepository:
    """Manages group invitations."""

    def __init__(self, session: Session):
        self.session = session

    def create(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        group_id: int,
        inviter_id: int,
        channel: InvitationChannel,
        token: str,
        expires_at: datetime,
        invitee_member_id: Optional[int] = None,
        target: Optional[str] = None,
    ) -> InvitationModel:
        """Insert a new invitation row and return it."""
        row = InvitationModel(
            group_id=group_id,
            inviter_id=inviter_id,
            invitee_member_id=invitee_member_id,
            channel=channel,
            target=target,
            token=token,
            status=InvitationStatus.PENDING,
            created_at=datetime.utcnow(),
            expires_at=expires_at,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def get_by_token(self, token: str) -> Optional[InvitationModel]:
        """Return the invitation with this token, or None."""
        return self.session.query(InvitationModel).filter(InvitationModel.token == token).first()

    def list_for_group(self, group_id: int, status: Optional[InvitationStatus] = None) -> List[InvitationModel]:
        """Return invitations for a group, optionally filtered by status."""
        q = self.session.query(InvitationModel).filter(InvitationModel.group_id == group_id)
        if status:
            q = q.filter(InvitationModel.status == status)
        return q.order_by(InvitationModel.created_at.desc()).all()

    def mark_accepted(self, invitation_id: int, accepted_by_member_id: int) -> InvitationModel:
        """Flip status to accepted."""
        row = self.session.query(InvitationModel).filter(InvitationModel.id == invitation_id).first()
        if not row:
            raise ValueError(f"Invitation {invitation_id} not found")
        row.status = InvitationStatus.ACCEPTED
        row.accepted_at = datetime.utcnow()
        row.accepted_by_member_id = accepted_by_member_id
        self.session.commit()
        self.session.refresh(row)
        return row

    def revoke(self, invitation_id: int) -> InvitationModel:
        """Flip status to revoked."""
        row = self.session.query(InvitationModel).filter(InvitationModel.id == invitation_id).first()
        if not row:
            raise ValueError(f"Invitation {invitation_id} not found")
        row.status = InvitationStatus.REVOKED
        self.session.commit()
        return row

    def latest_pending_for_member(self, member_id: int) -> Optional[InvitationModel]:
        """Return the most recent pending invitation for a stub member."""
        return (
            self.session.query(InvitationModel)
            .filter(
                InvitationModel.invitee_member_id == member_id,
                InvitationModel.status == InvitationStatus.PENDING,
            )
            .order_by(InvitationModel.created_at.desc())
            .first()
        )


class GroupJoinLinkRepository:
    """Manages reusable group join links."""

    def __init__(self, session: Session):
        self.session = session

    def get_or_create(self, group_id: int, created_by_member_id: int, token: str) -> GroupJoinLinkModel:
        """Return existing link for the group, or create one with the provided token."""
        existing = self.session.query(GroupJoinLinkModel).filter(GroupJoinLinkModel.group_id == group_id).first()
        if existing:
            return existing
        row = GroupJoinLinkModel(
            group_id=group_id,
            token=token,
            created_at=datetime.utcnow(),
            created_by_member_id=created_by_member_id,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def rotate(self, group_id: int, new_token: str) -> GroupJoinLinkModel:
        """Replace the token for an existing join link."""
        row = self.session.query(GroupJoinLinkModel).filter(GroupJoinLinkModel.group_id == group_id).first()
        if not row:
            raise ValueError(f"No join link for group {group_id}")
        row.token = new_token
        self.session.commit()
        return row

    def get_by_token(self, token: str) -> Optional[GroupJoinLinkModel]:
        """Return the join link with this token, or None."""
        return self.session.query(GroupJoinLinkModel).filter(GroupJoinLinkModel.token == token).first()


class IncomeRepository:
    """Manages recurring income templates and income instances for personal groups."""

    def __init__(self, session: Session):
        self.session = session

    # --- RecurringIncome (templates) ---

    def create_recurring(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        owner_member_id: int,
        personal_group_id: int,
        label: str,
        amount: float,
        start_year: int,
        start_month: int,
    ) -> RecurringIncome:
        """Create a new recurring income template with an explicit start month."""
        model = RecurringIncomeModel(
            owner_member_id=owner_member_id,
            personal_group_id=personal_group_id,
            label=label,
            amount=amount,
            active=True,
            start_year=start_year,
            start_month=start_month,
        )
        self.session.add(model)
        self.session.flush()
        self.session.commit()
        return self._recurring_to_domain(model)

    def list_recurring(self, personal_group_id: int, active_only: bool = False) -> list[RecurringIncome]:
        """Return recurring income templates for the group. Includes inactive by default."""
        query = self.session.query(RecurringIncomeModel).filter(
            RecurringIncomeModel.personal_group_id == personal_group_id
        )
        if active_only:
            query = query.filter(RecurringIncomeModel.active.is_(True))
        return [self._recurring_to_domain(m) for m in query.order_by(RecurringIncomeModel.id).all()]

    def get_recurring(self, income_id: int) -> Optional[RecurringIncome]:
        """Return a recurring income template by ID, or None."""
        model = self.session.query(RecurringIncomeModel).filter(RecurringIncomeModel.id == income_id).first()
        return self._recurring_to_domain(model) if model else None

    def update_recurring(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        income_id: int,
        label: Optional[str] = None,
        amount: Optional[float] = None,
        active: Optional[bool] = None,
    ) -> RecurringIncome:
        """Update fields on a recurring income template."""
        model = self.session.query(RecurringIncomeModel).filter(RecurringIncomeModel.id == income_id).first()
        if not model:
            raise ValueError(f"RecurringIncome {income_id} not found")
        if label is not None:
            model.label = label
        if amount is not None:
            model.amount = amount
        if active is not None:
            model.active = active
        self.session.flush()
        self.session.commit()
        return self._recurring_to_domain(model)

    def delete_recurring(self, income_id: int) -> None:
        """Delete a recurring income template. Only allowed when no instances reference it."""
        if self.has_instances(income_id):
            raise ValueError(
                f"Cannot delete RecurringIncome {income_id}: instances reference it. "
                "Deactivate it instead (set active=False)."
            )
        self.session.query(RecurringIncomeModel).filter(RecurringIncomeModel.id == income_id).delete()
        self.session.commit()

    def has_instances(self, income_id: int) -> bool:
        """Return True if any income instances reference this template."""
        count = (
            self.session.query(IncomeInstanceModel).filter(IncomeInstanceModel.recurring_income_id == income_id).count()
        )
        return count > 0

    # --- IncomeInstance ---

    def upsert_recurring_instance(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        personal_group_id: int,
        owner_member_id: int,
        year: int,
        month: int,
        recurring_income_id: int,
        label: str,
        amount: float,
    ) -> IncomeInstance:
        """Get-or-create a recurring income snapshot for (group, year, month, template).

        Idempotent: if the snapshot already exists, returns it unchanged (forward-only semantics for past months).
        """
        existing = (
            self.session.query(IncomeInstanceModel)
            .filter(
                IncomeInstanceModel.personal_group_id == personal_group_id,
                IncomeInstanceModel.year == year,
                IncomeInstanceModel.month == month,
                IncomeInstanceModel.recurring_income_id == recurring_income_id,
                IncomeInstanceModel.source == "recurring",
            )
            .first()
        )
        if existing:
            return self._instance_to_domain(existing)
        model = IncomeInstanceModel(
            personal_group_id=personal_group_id,
            owner_member_id=owner_member_id,
            year=year,
            month=month,
            source="recurring",
            recurring_income_id=recurring_income_id,
            label=label,
            amount=amount,
        )
        try:
            self.session.add(model)
            self.session.flush()
            self.session.commit()
            return self._instance_to_domain(model)
        except IntegrityError:
            self.session.rollback()
            # Another concurrent call already created the instance — return it
            winner = (
                self.session.query(IncomeInstanceModel)
                .filter(
                    IncomeInstanceModel.personal_group_id == personal_group_id,
                    IncomeInstanceModel.year == year,
                    IncomeInstanceModel.month == month,
                    IncomeInstanceModel.recurring_income_id == recurring_income_id,
                    IncomeInstanceModel.source == "recurring",
                )
                .first()
            )
            return self._instance_to_domain(winner)

    def update_recurring_instance_for_month(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        personal_group_id: int,
        recurring_income_id: int,
        year: int,
        month: int,
        new_label: str,
        new_amount: float,
    ) -> None:
        """Update an existing recurring income snapshot for the given (group, year, month).

        No-op if no snapshot exists yet. The caller is responsible for ensuring this is only
        called for the current month.
        """
        self.session.query(IncomeInstanceModel).filter(
            IncomeInstanceModel.personal_group_id == personal_group_id,
            IncomeInstanceModel.recurring_income_id == recurring_income_id,
            IncomeInstanceModel.year == year,
            IncomeInstanceModel.month == month,
            IncomeInstanceModel.source == "recurring",
        ).update({"label": new_label, "amount": new_amount})
        self.session.commit()

    def update_recurring_instances_from_month_onwards(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # noqa: E501
        self,
        personal_group_id: int,
        recurring_income_id: int,
        year: int,
        month: int,
        new_label: str,
        new_amount: float,
    ) -> None:
        """Bulk-update all existing recurring snapshots from (year, month) onwards.

        Past months (before the given year/month) are left unchanged (forward-only semantics).
        Not-yet-materialized future months will pick up the new template amount automatically.
        """
        from sqlalchemy import and_  # pylint: disable=import-outside-toplevel

        self.session.query(IncomeInstanceModel).filter(
            IncomeInstanceModel.personal_group_id == personal_group_id,
            IncomeInstanceModel.recurring_income_id == recurring_income_id,
            IncomeInstanceModel.source == "recurring",
            or_(
                IncomeInstanceModel.year > year,
                and_(IncomeInstanceModel.year == year, IncomeInstanceModel.month >= month),
            ),
        ).update({"label": new_label, "amount": new_amount})
        self.session.commit()

    def delete_recurring_instance_for_month(
        self, personal_group_id: int, recurring_income_id: int, year: int, month: int
    ) -> None:
        """Delete the recurring snapshot for a specific month (used when deactivating a template)."""
        self.session.query(IncomeInstanceModel).filter(
            IncomeInstanceModel.personal_group_id == personal_group_id,
            IncomeInstanceModel.recurring_income_id == recurring_income_id,
            IncomeInstanceModel.year == year,
            IncomeInstanceModel.month == month,
            IncomeInstanceModel.source == "recurring",
        ).delete()
        self.session.commit()

    def create_variable_instance(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, personal_group_id: int, owner_member_id: int, year: int, month: int, label: str, amount: float
    ) -> IncomeInstance:
        """Create a one-off variable income entry for a specific month."""
        model = IncomeInstanceModel(
            personal_group_id=personal_group_id,
            owner_member_id=owner_member_id,
            year=year,
            month=month,
            source="variable",
            recurring_income_id=None,
            label=label,
            amount=amount,
        )
        self.session.add(model)
        self.session.flush()
        self.session.commit()
        return self._instance_to_domain(model)

    def list_instances_for_month(self, personal_group_id: int, year: int, month: int) -> list[IncomeInstance]:
        """Return all income instances for a group/month, ordered by ID."""
        models = (
            self.session.query(IncomeInstanceModel)
            .filter(
                IncomeInstanceModel.personal_group_id == personal_group_id,
                IncomeInstanceModel.year == year,
                IncomeInstanceModel.month == month,
            )
            .order_by(IncomeInstanceModel.id)
            .all()
        )
        return [self._instance_to_domain(m) for m in models]

    def get_instance(self, instance_id: int) -> Optional[IncomeInstance]:
        """Return an income instance by ID, or None."""
        model = self.session.query(IncomeInstanceModel).filter(IncomeInstanceModel.id == instance_id).first()
        return self._instance_to_domain(model) if model else None

    def update_instance(
        self, instance_id: int, label: Optional[str] = None, amount: Optional[float] = None
    ) -> IncomeInstance:
        """Update label and/or amount on an income instance."""
        model = self.session.query(IncomeInstanceModel).filter(IncomeInstanceModel.id == instance_id).first()
        if not model:
            raise ValueError(f"IncomeInstance {instance_id} not found")
        if label is not None:
            model.label = label
        if amount is not None:
            model.amount = amount
        self.session.flush()
        self.session.commit()
        return self._instance_to_domain(model)

    def delete_instance(self, instance_id: int) -> None:
        """Delete an income instance."""
        self.session.query(IncomeInstanceModel).filter(IncomeInstanceModel.id == instance_id).delete()
        self.session.commit()

    # --- Private helpers ---

    def delete_recurring_instances_from_month_onwards(
        self, personal_group_id: int, recurring_income_id: int, year: int, month: int
    ) -> None:
        """Delete all recurring snapshots for this template from (year, month) onwards."""
        from sqlalchemy import and_  # pylint: disable=import-outside-toplevel

        self.session.query(IncomeInstanceModel).filter(
            IncomeInstanceModel.personal_group_id == personal_group_id,
            IncomeInstanceModel.recurring_income_id == recurring_income_id,
            IncomeInstanceModel.source == "recurring",
            or_(
                IncomeInstanceModel.year > year,
                and_(IncomeInstanceModel.year == year, IncomeInstanceModel.month >= month),
            ),
        ).delete()
        self.session.commit()

    def _recurring_to_domain(self, model: RecurringIncomeModel) -> RecurringIncome:
        return RecurringIncome(
            id=model.id,
            owner_member_id=model.owner_member_id,
            personal_group_id=model.personal_group_id,
            label=model.label,
            amount=model.amount,
            active=model.active,
            start_year=model.start_year,
            start_month=model.start_month,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _instance_to_domain(self, model: IncomeInstanceModel) -> IncomeInstance:
        return IncomeInstance(
            id=model.id,
            personal_group_id=model.personal_group_id,
            owner_member_id=model.owner_member_id,
            year=model.year,
            month=model.month,
            source=model.source,
            recurring_income_id=model.recurring_income_id,
            label=model.label,
            amount=model.amount,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class RecurringPersonalExpenseRepository:
    """Manages recurring personal expense templates and their monthly instances."""

    def __init__(self, session: Session):
        self.session = session

    # --- Templates ---

    def create(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        personal_group_id: int,
        owner_member_id: int,
        label: str,
        amount: float,
        category_name: str,
        start_year: Optional[int],
        start_month: Optional[int],
    ) -> RecurringPersonalExpense:
        """Create a new recurring personal expense template."""
        model = RecurringPersonalExpenseModel(
            personal_group_id=personal_group_id,
            owner_member_id=owner_member_id,
            label=label,
            amount=amount,
            category_name=category_name,
            active=True,
            start_year=start_year,
            start_month=start_month,
        )
        self.session.add(model)
        self.session.flush()
        self.session.commit()
        return self._to_domain(model)

    def list_for_group(self, personal_group_id: int, active_only: bool = False) -> list[RecurringPersonalExpense]:
        """Return recurring expense templates for the group. Includes inactive by default."""
        query = self.session.query(RecurringPersonalExpenseModel).filter(
            RecurringPersonalExpenseModel.personal_group_id == personal_group_id
        )
        if active_only:
            query = query.filter(RecurringPersonalExpenseModel.active.is_(True))
        return [self._to_domain(m) for m in query.order_by(RecurringPersonalExpenseModel.id).all()]

    def get(self, expense_id: int) -> Optional[RecurringPersonalExpense]:
        """Return a recurring expense template by ID, or None."""
        model = (
            self.session.query(RecurringPersonalExpenseModel)
            .filter(RecurringPersonalExpenseModel.id == expense_id)
            .first()
        )
        return self._to_domain(model) if model else None

    def update(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        expense_id: int,
        label: Optional[str] = None,
        amount: Optional[float] = None,
        category_name: Optional[str] = None,
        active: Optional[bool] = None,
    ) -> RecurringPersonalExpense:
        """Update fields on a recurring expense template."""
        model = (
            self.session.query(RecurringPersonalExpenseModel)
            .filter(RecurringPersonalExpenseModel.id == expense_id)
            .first()
        )
        if not model:
            raise ValueError(f"RecurringPersonalExpense {expense_id} not found")
        if label is not None:
            model.label = label
        if amount is not None:
            model.amount = amount
        if category_name is not None:
            model.category_name = category_name
        if active is not None:
            model.active = active
        self.session.flush()
        self.session.commit()
        return self._to_domain(model)

    def has_instances(self, expense_id: int) -> bool:
        """Return True if any instances reference this template."""
        count = (
            self.session.query(RecurringPersonalExpenseInstanceModel)
            .filter(RecurringPersonalExpenseInstanceModel.recurring_expense_id == expense_id)
            .count()
        )
        return count > 0

    def hard_delete(self, expense_id: int) -> None:
        """Delete the template entirely. Only call when no instances reference it."""
        self.session.query(RecurringPersonalExpenseModel).filter(
            RecurringPersonalExpenseModel.id == expense_id
        ).delete()
        self.session.commit()

    # --- Instances ---

    def upsert_instance(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        personal_group_id: int,
        recurring_expense_id: int,
        year: int,
        month: int,
        label: str,
        amount: float,
        category_name: str,
    ) -> RecurringPersonalExpenseInstance:
        """Get-or-create a recurring expense snapshot for (group, year, month, template).

        Idempotent: if the snapshot already exists, returns it unchanged (forward-only semantics).
        """
        existing = (
            self.session.query(RecurringPersonalExpenseInstanceModel)
            .filter(
                RecurringPersonalExpenseInstanceModel.personal_group_id == personal_group_id,
                RecurringPersonalExpenseInstanceModel.recurring_expense_id == recurring_expense_id,
                RecurringPersonalExpenseInstanceModel.year == year,
                RecurringPersonalExpenseInstanceModel.month == month,
            )
            .first()
        )
        if existing:
            return self._instance_to_domain(existing)
        model = RecurringPersonalExpenseInstanceModel(
            personal_group_id=personal_group_id,
            recurring_expense_id=recurring_expense_id,
            year=year,
            month=month,
            label=label,
            amount=amount,
            category_name=category_name,
        )
        try:
            self.session.add(model)
            self.session.flush()
            self.session.commit()
            return self._instance_to_domain(model)
        except IntegrityError:
            self.session.rollback()
            # Another concurrent call already created the instance — return it
            winner = (
                self.session.query(RecurringPersonalExpenseInstanceModel)
                .filter(
                    RecurringPersonalExpenseInstanceModel.personal_group_id == personal_group_id,
                    RecurringPersonalExpenseInstanceModel.recurring_expense_id == recurring_expense_id,
                    RecurringPersonalExpenseInstanceModel.year == year,
                    RecurringPersonalExpenseInstanceModel.month == month,
                )
                .first()
            )
            return self._instance_to_domain(winner)

    def list_instances_for_month(
        self, personal_group_id: int, year: int, month: int
    ) -> list[RecurringPersonalExpenseInstance]:
        """Return all recurring expense instances for a group/month, ordered by ID."""
        models = (
            self.session.query(RecurringPersonalExpenseInstanceModel)
            .filter(
                RecurringPersonalExpenseInstanceModel.personal_group_id == personal_group_id,
                RecurringPersonalExpenseInstanceModel.year == year,
                RecurringPersonalExpenseInstanceModel.month == month,
            )
            .order_by(RecurringPersonalExpenseInstanceModel.id)
            .all()
        )
        return [self._instance_to_domain(m) for m in models]

    def update_instances_from_month_onwards(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        personal_group_id: int,
        recurring_expense_id: int,
        year: int,
        month: int,
        new_label: str,
        new_amount: float,
        new_category_name: str,
    ) -> None:
        """Bulk-update label/amount/category_name for all instances from (year, month) onwards."""
        from sqlalchemy import and_  # pylint: disable=import-outside-toplevel

        self.session.query(RecurringPersonalExpenseInstanceModel).filter(
            RecurringPersonalExpenseInstanceModel.personal_group_id == personal_group_id,
            RecurringPersonalExpenseInstanceModel.recurring_expense_id == recurring_expense_id,
            or_(
                RecurringPersonalExpenseInstanceModel.year > year,
                and_(
                    RecurringPersonalExpenseInstanceModel.year == year,
                    RecurringPersonalExpenseInstanceModel.month >= month,
                ),
            ),
        ).update({"label": new_label, "amount": new_amount, "category_name": new_category_name})
        self.session.commit()

    def delete_instances_from_month_onwards(
        self,
        personal_group_id: int,
        recurring_expense_id: int,
        year: int,
        month: int,
    ) -> None:
        """Delete all instances for this template from (year, month) onwards."""
        from sqlalchemy import and_  # pylint: disable=import-outside-toplevel

        self.session.query(RecurringPersonalExpenseInstanceModel).filter(
            RecurringPersonalExpenseInstanceModel.personal_group_id == personal_group_id,
            RecurringPersonalExpenseInstanceModel.recurring_expense_id == recurring_expense_id,
            or_(
                RecurringPersonalExpenseInstanceModel.year > year,
                and_(
                    RecurringPersonalExpenseInstanceModel.year == year,
                    RecurringPersonalExpenseInstanceModel.month >= month,
                ),
            ),
        ).delete()
        self.session.commit()

    # --- Private helpers ---

    def _to_domain(self, model: RecurringPersonalExpenseModel) -> RecurringPersonalExpense:
        return RecurringPersonalExpense(
            id=model.id,
            personal_group_id=model.personal_group_id,
            owner_member_id=model.owner_member_id,
            label=model.label,
            amount=model.amount,
            category_name=model.category_name,
            active=model.active,
            start_year=model.start_year,
            start_month=model.start_month,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _instance_to_domain(self, model: RecurringPersonalExpenseInstanceModel) -> RecurringPersonalExpenseInstance:
        return RecurringPersonalExpenseInstance(
            id=model.id,
            personal_group_id=model.personal_group_id,
            recurring_expense_id=model.recurring_expense_id,
            year=model.year,
            month=model.month,
            label=model.label,
            amount=model.amount,
            category_name=model.category_name,
            created_at=model.created_at,
        )


class RecurringGroupExpenseRepository:
    """Manages recurring group expense templates and their monthly idempotency instances."""

    def __init__(self, session: Session):
        self.session = session

    # --- Templates ---

    def create(self, group_id: int, data: RecurringGroupExpenseCreate) -> RecurringGroupExpenseResponse:
        """Create a new recurring group expense template."""
        model = RecurringGroupExpenseModel(
            group_id=group_id,
            description=data.description,
            amount=data.amount,
            category=data.category,
            payer_id=data.payer_id,
            payment_type=data.payment_type,
            split_strategy=self._serialize_split_strategy(data.split_strategy),
            start_year=data.start_year,
            start_month=data.start_month,
            active=True,
        )
        self.session.add(model)
        self.session.flush()
        self.session.commit()
        return self._to_schema(model)

    def list_for_group(self, group_id: int, active_only: bool = True) -> List[RecurringGroupExpenseResponse]:
        """List recurring expense templates for a group."""
        query = self.session.query(RecurringGroupExpenseModel).filter(
            RecurringGroupExpenseModel.group_id == group_id
        )
        if active_only:
            query = query.filter(RecurringGroupExpenseModel.active.is_(True))
        return [self._to_schema(m) for m in query.order_by(RecurringGroupExpenseModel.id).all()]

    def get(self, template_id: int) -> Optional[RecurringGroupExpenseResponse]:
        """Get a template by id."""
        model = (
            self.session.query(RecurringGroupExpenseModel)
            .filter(RecurringGroupExpenseModel.id == template_id)
            .first()
        )
        return self._to_schema(model) if model else None

    def update(self, template_id: int, data: RecurringGroupExpenseUpdate) -> Optional[RecurringGroupExpenseResponse]:
        """Update template fields (patch semantics — only non-None fields are updated)."""
        model = (
            self.session.query(RecurringGroupExpenseModel)
            .filter(RecurringGroupExpenseModel.id == template_id)
            .first()
        )
        if not model:
            return None
        if data.description is not None:
            model.description = data.description
        if data.amount is not None:
            model.amount = data.amount
        if data.category is not None:
            model.category = data.category
        if data.payer_id is not None:
            model.payer_id = data.payer_id
        if data.payment_type is not None:
            model.payment_type = data.payment_type
        if data.split_strategy is not None:
            model.split_strategy = self._serialize_split_strategy(data.split_strategy)
        if data.start_year is not None:
            model.start_year = data.start_year
        if data.start_month is not None:
            model.start_month = data.start_month
        if data.active is not None:
            model.active = data.active
        model.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        self.session.flush()
        self.session.commit()
        return self._to_schema(model)

    def has_instances(self, template_id: int) -> bool:
        """True if any instance records exist for this template."""
        count = (
            self.session.query(RecurringGroupExpenseInstanceModel)
            .filter(RecurringGroupExpenseInstanceModel.recurring_expense_id == template_id)
            .count()
        )
        return count > 0

    def deactivate(self, template_id: int) -> None:
        """Set active=False on the template (soft delete — keeps historical expense rows)."""
        model = (
            self.session.query(RecurringGroupExpenseModel)
            .filter(RecurringGroupExpenseModel.id == template_id)
            .first()
        )
        if model:
            model.active = False
            self.session.flush()
            self.session.commit()

    def hard_delete(self, template_id: int) -> None:
        """Delete the template row entirely (cascades to instances, sets NULL on expenses)."""
        self.session.query(RecurringGroupExpenseModel).filter(
            RecurringGroupExpenseModel.id == template_id
        ).delete()
        self.session.commit()

    # --- Instances ---

    def upsert_instance(self, template_id: int, group_id: int, year: int, month: int) -> bool:
        """Idempotent create of an instance record.

        Returns True if newly created, False if already existed.
        Uses IntegrityError catch on the unique constraint (uq_recurring_group_expense_instance).
        """
        existing = (
            self.session.query(RecurringGroupExpenseInstanceModel)
            .filter(
                RecurringGroupExpenseInstanceModel.recurring_expense_id == template_id,
                RecurringGroupExpenseInstanceModel.group_id == group_id,
                RecurringGroupExpenseInstanceModel.year == year,
                RecurringGroupExpenseInstanceModel.month == month,
            )
            .first()
        )
        if existing:
            return False
        model = RecurringGroupExpenseInstanceModel(
            recurring_expense_id=template_id,
            group_id=group_id,
            year=year,
            month=month,
        )
        try:
            self.session.add(model)
            self.session.flush()
            self.session.commit()
            return True
        except IntegrityError:
            self.session.rollback()
            return False

    def update_instances_from_month_onwards(
        self, template_id: int, year: int, month: int, data: RecurringGroupExpenseUpdate
    ) -> None:
        """Instances are pure idempotency guards with no updateable data.

        When a template is edited, delete instances from the edited month onwards so they
        re-materialize with updated values on next read.
        """
        self.delete_instances_from_month_onwards(template_id, year, month)

    def delete_instances_from_month_onwards(self, template_id: int, year: int, month: int) -> None:
        """Delete instance records for this template from (year, month) onwards.

        Uses: year > given_year OR (year == given_year AND month >= given_month).
        This causes those months to re-materialize on the next read.
        """
        from sqlalchemy import and_  # pylint: disable=import-outside-toplevel

        self.session.query(RecurringGroupExpenseInstanceModel).filter(
            RecurringGroupExpenseInstanceModel.recurring_expense_id == template_id,
            or_(
                RecurringGroupExpenseInstanceModel.year > year,
                and_(
                    RecurringGroupExpenseInstanceModel.year == year,
                    RecurringGroupExpenseInstanceModel.month >= month,
                ),
            ),
        ).delete()
        self.session.commit()

    # --- Private helpers ---

    @staticmethod
    def _serialize_split_strategy(strategy: SplitStrategySchema) -> dict:
        """Convert SplitStrategySchema to a JSON-serializable dict for storage."""
        payload: dict = {"type": strategy.type}
        if strategy.type == "equal" and strategy.participant_ids is not None:
            payload["participant_ids"] = strategy.participant_ids
        elif strategy.type == "percentage" and strategy.percentages is not None:
            payload["percentages"] = strategy.percentages
        elif strategy.type == "exact" and strategy.amounts is not None:
            payload["amounts"] = strategy.amounts
        return payload

    @staticmethod
    def _deserialize_split_strategy(data: dict) -> SplitStrategySchema:
        """Convert a stored JSON dict back to a SplitStrategySchema."""
        return SplitStrategySchema(
            type=data["type"],
            participant_ids=data.get("participant_ids"),
            percentages=data.get("percentages"),
            amounts=data.get("amounts"),
        )

    def _to_schema(self, model: RecurringGroupExpenseModel) -> RecurringGroupExpenseResponse:
        """Convert an ORM model to a RecurringGroupExpenseResponse schema."""
        return RecurringGroupExpenseResponse(
            id=model.id,
            group_id=model.group_id,
            description=model.description,
            amount=model.amount,
            category=model.category,
            payer_id=model.payer_id,
            payment_type=model.payment_type,
            split_strategy=self._deserialize_split_strategy(model.split_strategy),
            start_year=model.start_year,
            start_month=model.start_month,
            active=model.active,
        )
