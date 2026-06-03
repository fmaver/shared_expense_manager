"""ORM adapter"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from template.domain.models.enums import (
    InvitationChannel,
    InvitationStatus,
    NotificationType,
    PaymentType,
)


class Base(DeclarativeBase):
    pass


class MemberModel(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    telephone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notification_preference: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType), default=NotificationType.NONE
    )
    last_wpp_chat_datetime: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expenses: Mapped[list["ExpenseModel"]] = relationship(back_populates="payer")


class GroupModel(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active")
    group_type: Mapped[str] = mapped_column(String(20), default="regular")
    owner_member_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index(
            "uq_one_personal_group_per_owner",
            "owner_member_id",
            unique=True,
            postgresql_where=text("group_type = 'personal'"),
        ),
    )

    memberships: Mapped[list["GroupMembershipModel"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupMembershipModel(Base):
    __tablename__ = "group_memberships"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"))
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("group_id", "member_id", name="uq_group_member"),)

    group: Mapped["GroupModel"] = relationship(back_populates="memberships")
    member: Mapped["MemberModel"] = relationship()


class MonthlyShareModel(Base):
    __tablename__ = "monthly_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), default=1)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    is_settled: Mapped[bool] = mapped_column(default=False)
    balances: Mapped[dict] = mapped_column(JSON)
    expenses: Mapped[list["ExpenseModel"]] = relationship(back_populates="monthly_share")
    group: Mapped["GroupModel"] = relationship()


class ExpenseModel(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(Float())
    date: Mapped[Date] = mapped_column(Date())
    category: Mapped[str] = mapped_column(String(50))
    payer_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    payment_type: Mapped[PaymentType] = mapped_column(Enum(PaymentType))
    installments: Mapped[int] = mapped_column(Integer, default=1)
    installment_no: Mapped[int] = mapped_column(Integer, default=1)
    split_strategy: Mapped[dict] = mapped_column(JSON)
    monthly_share_id: Mapped[int] = mapped_column(ForeignKey("monthly_shares.id"))
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), default=1)
    group: Mapped["GroupModel"] = relationship()
    parent_expense_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("expenses.id", ondelete="CASCADE"), nullable=True
    )

    payer: Mapped[MemberModel] = relationship(back_populates="expenses")
    monthly_share: Mapped[MonthlyShareModel] = relationship(back_populates="expenses")
    parent_expense: Mapped[Optional["ExpenseModel"]] = relationship(
        "ExpenseModel", remote_side=[id], back_populates="child_expenses"
    )
    child_expenses: Mapped[List["ExpenseModel"]] = relationship(
        "ExpenseModel", back_populates="parent_expense", cascade="all, delete-orphan"
    )


class ChatSessionModel(Base):
    """Persists per-user chatbot state, replacing the in-memory estado_actual dict."""

    __tablename__ = "chat_sessions"

    telephone: Mapped[str] = mapped_column(String(20), primary_key=True)
    estado: Mapped[str] = mapped_column(String(50), default="inicial")
    expense_data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProcessedMessageModel(Base):
    """Tracks processed WhatsApp message IDs to prevent duplicate handling on webhook retries."""

    __tablename__ = "processed_wpp_messages"

    message_id: Mapped[str] = mapped_column(Text, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InvitationModel(Base):
    """Tracks group invitations sent via email, phone, or shareable link."""

    __tablename__ = "group_invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    inviter_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    invitee_member_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"), nullable=True)
    channel: Mapped[InvitationChannel] = mapped_column(Enum(InvitationChannel))
    target: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[InvitationStatus] = mapped_column(Enum(InvitationStatus), default=InvitationStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    accepted_by_member_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"), nullable=True)

    group: Mapped["GroupModel"] = relationship(foreign_keys=[group_id])
    inviter: Mapped["MemberModel"] = relationship(foreign_keys=[inviter_id])
    invitee: Mapped[Optional["MemberModel"]] = relationship(foreign_keys=[invitee_member_id])


class GroupJoinLinkModel(Base):
    """Stores reusable shareable links for joining a group."""

    __tablename__ = "group_join_links"

    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))

    group: Mapped["GroupModel"] = relationship()
    created_by: Mapped["MemberModel"] = relationship()


class RecurringIncomeModel(Base):
    __tablename__ = "recurring_incomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    personal_group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    label: Mapped[str] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(Float())
    active: Mapped[bool] = mapped_column(default=True)
    start_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    start_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner: Mapped["MemberModel"] = relationship(foreign_keys=[owner_member_id])
    personal_group: Mapped["GroupModel"] = relationship(foreign_keys=[personal_group_id])


class IncomeInstanceModel(Base):
    __tablename__ = "income_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    personal_group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    owner_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20))
    recurring_income_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recurring_incomes.id", ondelete="SET NULL"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(Float())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # Idempotency: one snapshot per recurring template per month
        Index(
            "uq_income_instance_recurring_per_month",
            "personal_group_id",
            "year",
            "month",
            "recurring_income_id",
            unique=True,
            postgresql_where=text("source = 'recurring'"),
        ),
        # Covering index for ledger queries
        Index("ix_income_instances_group_period", "personal_group_id", "year", "month"),
        # Enforce that recurring source has a recurring_income_id
        CheckConstraint(
            "source != 'recurring' OR recurring_income_id IS NOT NULL",
            name="ck_income_instance_recurring_has_id",
        ),
        # Enforce valid source values
        CheckConstraint("source IN ('recurring', 'variable')", name="ck_income_instance_source"),
    )

    personal_group: Mapped["GroupModel"] = relationship(foreign_keys=[personal_group_id])
    owner: Mapped["MemberModel"] = relationship(foreign_keys=[owner_member_id])
    recurring_income: Mapped[Optional["RecurringIncomeModel"]] = relationship()
