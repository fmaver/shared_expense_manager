"""Repositories behind quick capture: drafts, shortcut tokens and the group-ranking count."""

from datetime import date, datetime, timedelta

import pytest

from template.adapters.database import SessionLocal
from template.adapters.orm import (
    ExpenseDraftModel,
    ExpenseModel,
    GroupModel,
    MemberModel,
    MonthlyShareModel,
    ShortcutTokenModel,
)
from template.adapters.repositories import (
    ExpenseDraftRepository,
    ShortcutTokenRepository,
    SQLAlchemyExpenseRepository,
)
from template.domain.models.enums import PaymentType


@pytest.fixture(name="session")
def session_fixture():
    with SessionLocal() as session:
        yield session


def _member(session, email: str) -> MemberModel:
    member = MemberModel(name=email, email=email, hashed_password="x")
    session.add(member)
    session.flush()
    return member


def test_pending_drafts_are_owned_and_ordered(session):
    a, b = _member(session, "a@x.com"), _member(session, "b@x.com")
    repo = ExpenseDraftRepository(session)
    now = datetime.utcnow()
    newer = repo.add(ExpenseDraftModel(member_id=a.id, amount=2, created_at=now))
    older = repo.add(ExpenseDraftModel(member_id=a.id, amount=1, created_at=now - timedelta(hours=1)))
    repo.add(ExpenseDraftModel(member_id=b.id, amount=3))
    repo.add(ExpenseDraftModel(member_id=a.id, amount=4, status="discarded"))
    repo.commit()

    assert [d.id for d in repo.list_pending(a.id)] == [older.id, newer.id]
    assert len(repo.list_pending(b.id)) == 1


def test_get_owned_hides_other_members_drafts(session):
    a, b = _member(session, "a@x.com"), _member(session, "b@x.com")
    repo = ExpenseDraftRepository(session)
    draft = repo.add(ExpenseDraftModel(member_id=a.id))
    repo.commit()

    assert repo.get_owned(draft.id, a.id) is not None
    assert repo.get_owned(draft.id, b.id) is None
    assert repo.get_owned_for_update(draft.id, b.id) is None
    assert repo.get_owned_for_update(draft.id, a.id) is not None
    assert draft.status == "pending"


def test_only_one_active_token_after_revoke_all(session):
    a = _member(session, "a@x.com")
    repo = ShortcutTokenRepository(session)
    repo.add(ShortcutTokenModel(member_id=a.id, token_hash="h1" * 32, prefix="jrn_aaaa"))
    repo.commit()
    assert repo.find_active_by_hash("h1" * 32) is not None

    repo.revoke_all(a.id)
    repo.add(ShortcutTokenModel(member_id=a.id, token_hash="h2" * 32, prefix="jrn_bbbb"))
    repo.commit()

    assert repo.find_active_by_hash("h1" * 32) is None
    active = repo.get_active(a.id)
    assert active is not None and active.token_hash == "h2" * 32

    assert active.last_used_at is None
    repo.touch(active)
    repo.commit()
    assert active.last_used_at is not None


def test_count_recent_expenses_by_group_ignores_old_and_internal(session):
    a = _member(session, "a@x.com")
    g1, g2 = GroupModel(name="g1"), GroupModel(name="g2")
    session.add_all([g1, g2])
    session.flush()
    share = MonthlyShareModel(group_id=g1.id, year=2026, month=1, balances={})
    session.add(share)
    session.flush()

    def add(group, category, when, installment_no=1):
        session.add(
            ExpenseModel(
                description="x",
                amount=10,
                date=when,
                category=category,
                payer_id=a.id,
                payment_type=PaymentType.DEBIT,
                installment_no=installment_no,
                split_strategy={},
                monthly_share_id=share.id,
                group_id=group.id,
            )
        )

    today = date.today()
    add(g1, "supermercado", today)
    add(g1, "comida", today - timedelta(days=5))
    add(g1, "supermercado", today - timedelta(days=100))
    add(g1, "balance", today)
    add(g2, "supermercado", today)
    add(g2, "supermercado", today, installment_no=2)
    session.commit()

    repo = SQLAlchemyExpenseRepository(session)
    since = today - timedelta(days=90)
    assert repo.count_recent_expenses_by_group(a.id, since) == {g1.id: 2, g2.id: 1}
    assert repo.count_recent_expenses_by_group(a.id, since, category="supermercado") == {g1.id: 1, g2.id: 1}
