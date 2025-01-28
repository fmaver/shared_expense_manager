"""ORM adapter"""
from sqlalchemy import JSON, Date, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from template.domain.models.enums import PaymentType


class Base(DeclarativeBase):
    pass


class MemberModel(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    telephone: Mapped[str] = mapped_column(String(20))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expenses: Mapped[list["ExpenseModel"]] = relationship(back_populates="payer")


class MonthlyShareModel(Base):
    __tablename__ = "monthly_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    is_settled: Mapped[bool] = mapped_column(default=False)
    balances: Mapped[dict] = mapped_column(JSON)
    expenses: Mapped[list["ExpenseModel"]] = relationship(back_populates="monthly_share")


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

    payer: Mapped[MemberModel] = relationship(back_populates="expenses")
    monthly_share: Mapped[MonthlyShareModel] = relationship(back_populates="expenses")
