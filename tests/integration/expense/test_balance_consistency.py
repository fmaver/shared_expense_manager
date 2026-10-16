"""Un mes abierto tiene un solo saldo: el que sale de sus filas.

Incidente Buzios (2026-10-14): el JSON `monthly_shares.balances` tenía un gasto aplicado dos
veces, la pantalla del grupo lo mostraba y el resumen personal — que recalcula — no. Estos tests
corrompen el JSON a mano y exigen que ninguna lectura lo use mientras el mes esté abierto.
"""

import datetime
import json
import threading

from sqlalchemy import text

from template.adapters.database import SessionLocal
from template.adapters.repositories import GroupRepository, SQLAlchemyExpenseRepository
from template.domain.models.category import Category
from template.domain.models.enums import PaymentType
from template.domain.models.expense_manager import ExpenseManager
from template.domain.models.models import Expense
from template.domain.models.split import EqualSplit

TODAY = datetime.date.today()


def _ghost(client, auth_headers, group_id) -> int:
    r = client.post(f"/api/v1/groups/{group_id}/members", json={"name": "Marian"}, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]["memberId"]


def _add(client, auth_headers, group_id, payer_id, amount, split=None):
    r = client.post(
        f"/api/v1/groups/{group_id}/expenses/",
        json={
            "description": "Pollera y pareo",
            "amount": amount,
            "date": TODAY.isoformat(),
            "category": {"name": "otros"},
            "payerId": payer_id,
            "paymentType": "debit",
            "installments": 1,
            "splitStrategy": split or {"type": "equal"},
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text


def _corrupt_stored_balances(group_id: int, balances: dict) -> None:
    with SessionLocal() as session:
        session.execute(
            text("UPDATE monthly_shares SET balances = CAST(:b AS json) WHERE group_id = :g"),
            {"b": json.dumps(balances), "g": group_id},
        )
        session.commit()


def _month_balances(client, auth_headers, group_id) -> dict:
    r = client.get(f"/api/v1/groups/{group_id}/shares/{TODAY.year}/{TODAY.month}", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_open_month_ignores_stale_stored_balances(client, auth_headers, primary_member_id, primary_group_id):
    ghost = _ghost(client, auth_headers, primary_group_id)
    split = {"type": "percentage", "percentages": {str(primary_member_id): 60.0, str(ghost): 40.0}}
    _add(client, auth_headers, primary_group_id, primary_member_id, 32182.0, split)

    # The Buzios shape: the ghost's 40% counted twice.
    _corrupt_stored_balances(primary_group_id, {str(primary_member_id): 25745.6, str(ghost): -25745.6})

    data = _month_balances(client, auth_headers, primary_group_id)
    assert data["balances"] == {str(primary_member_id): 12872.8, str(ghost): -12872.8}
    assert data["transfers"] == [{"fromMemberId": ghost, "toMemberId": primary_member_id, "amount": 12872.8}]

    r = client.get(f"/api/v1/personal/ledger/{TODAY.year}/{TODAY.month}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["groupBalances"][0]["netBalance"] == 12872.8


def test_new_expense_lands_on_derived_balances_not_stale_ones(
    client, auth_headers, primary_member_id, primary_group_id
):
    ghost = _ghost(client, auth_headers, primary_group_id)
    _add(client, auth_headers, primary_group_id, primary_member_id, 1000.0)
    _corrupt_stored_balances(primary_group_id, {str(primary_member_id): 999999.0, str(ghost): -999999.0})

    _add(client, auth_headers, primary_group_id, ghost, 400.0)

    with SessionLocal() as session:
        stored = session.execute(
            text("SELECT balances FROM monthly_shares WHERE group_id = :g"), {"g": primary_group_id}
        ).scalar_one()
    assert stored == {str(primary_member_id): 300.0, str(ghost): -300.0}


def test_settled_month_keeps_its_snapshot(client, auth_headers, primary_member_id, primary_group_id):
    ghost = _ghost(client, auth_headers, primary_group_id)
    _add(client, auth_headers, primary_group_id, primary_member_id, 1000.0)
    r = client.post(f"/api/v1/groups/{primary_group_id}/shares/settle/{TODAY.year}/{TODAY.month}", headers=auth_headers)
    assert r.status_code == 200, r.text

    snapshot = {str(primary_member_id): 0.0, str(ghost): 0.0}
    _corrupt_stored_balances(primary_group_id, snapshot | {"999999": 0.0})

    data = _month_balances(client, auth_headers, primary_group_id)
    assert data["isSettled"] is True
    assert data["balances"] == snapshot | {"999999": 0.0}


# ── Concurrency: writers on the same month take turns ─────────────────────────────────────────

WAIT = 0.5  # long enough for an unblocked thread to finish, short enough to keep the suite fast


def _manager(session, group_id):
    return ExpenseManager(SQLAlchemyExpenseRepository(session), group_id, GroupRepository(session))


def _expense(payer_id, amount, when=TODAY):
    category = Category()
    category.name = "otros"
    return Expense(
        description="x",
        amount=amount,
        date=when,
        category=category,
        payer_id=payer_id,
        payment_type=PaymentType.DEBIT,
        split_strategy=EqualSplit(),
    )


def _in_thread(fn):
    """Run fn in a thread; return (thread, outcome dict with 'result' or 'error')."""
    outcome: dict = {}

    def run():
        try:
            outcome["result"] = fn()
        except Exception as error:  # noqa: BLE001  pylint: disable=broad-exception-caught
            outcome["error"] = error

    thread = threading.Thread(target=run)
    thread.start()
    return thread, outcome


def test_a_locked_month_makes_the_next_writer_wait(client, auth_headers, primary_member_id, primary_group_id):
    _ghost(client, auth_headers, primary_group_id)
    _add(client, auth_headers, primary_group_id, primary_member_id, 1000.0)

    holder = SessionLocal()
    SQLAlchemyExpenseRepository(holder).get_monthly_share_for_update(TODAY.year, TODAY.month, primary_group_id)

    def second_writer():
        with SessionLocal() as session:
            _manager(session, primary_group_id).create_and_add_expense(_expense(primary_member_id, 500.0))

    thread, outcome = _in_thread(second_writer)
    thread.join(WAIT)
    assert thread.is_alive(), "the second writer should be blocked on the month's lock"

    holder.commit()
    holder.close()
    thread.join(5)
    assert not thread.is_alive() and "error" not in outcome, outcome


def test_two_first_expenses_of_a_new_month_do_not_collide(client, auth_headers, primary_member_id, primary_group_id):
    ghost = _ghost(client, auth_headers, primary_group_id)
    next_month = datetime.date(TODAY.year + TODAY.month // 12, TODAY.month % 12 + 1, 5)

    first = SessionLocal()
    _manager(first, primary_group_id)  # members loaded before the lock, as in a request
    repo = SQLAlchemyExpenseRepository(first)
    share = repo.get_monthly_share_for_update(next_month.year, next_month.month, primary_group_id)

    def second():
        with SessionLocal() as session:
            _manager(session, primary_group_id).create_and_add_expense(_expense(ghost, 300.0, next_month))

    thread, outcome = _in_thread(second)
    thread.join(WAIT)
    assert thread.is_alive(), "the second create should wait for the first, not fail on the unique constraint"

    share.add_expense(_expense(primary_member_id, 1000.0, next_month), _manager(first, primary_group_id).members)
    repo.save_monthly_share(share)
    first.close()
    thread.join(5)
    assert "error" not in outcome, outcome

    with SessionLocal() as session:
        rows = session.execute(
            text("SELECT id FROM monthly_shares WHERE group_id = :g AND year = :y AND month = :m"),
            {"g": primary_group_id, "y": next_month.year, "m": next_month.month},
        ).all()
        count = session.execute(
            text("SELECT count(*) FROM expenses WHERE monthly_share_id = :s"), {"s": rows[0].id}
        ).scalar_one()
    assert len(rows) == 1 and count == 2


def test_an_add_that_waits_for_a_settlement_is_refused(client, auth_headers, primary_member_id, primary_group_id):
    _ghost(client, auth_headers, primary_group_id)
    _add(client, auth_headers, primary_group_id, primary_member_id, 1000.0)

    settler = SessionLocal()
    settling = _manager(settler, primary_group_id)
    share = SQLAlchemyExpenseRepository(settler).get_monthly_share_for_update(TODAY.year, TODAY.month, primary_group_id)

    def late_add():
        with SessionLocal() as session:
            _manager(session, primary_group_id).create_and_add_expense(_expense(primary_member_id, 500.0))

    thread, outcome = _in_thread(late_add)
    thread.join(WAIT)
    assert thread.is_alive()

    # Finish the settlement the late add is waiting on (same steps as settle_monthly_share).
    share.recalculate_balances(settling.members)
    share.expenses.extend(
        settling._balancing_expenses(share.balances, TODAY.year, TODAY.month)
    )  # pylint: disable=protected-access
    share.recalculate_balances(settling.members)
    share.settle()
    SQLAlchemyExpenseRepository(settler).save_monthly_share(share)
    settler.close()

    thread.join(5)
    assert "saldado" in str(outcome.get("error")), outcome


def test_concurrent_adds_through_the_api_keep_every_row_and_the_snapshot(
    client, auth_headers, primary_member_id, primary_group_id
):
    ghost = _ghost(client, auth_headers, primary_group_id)
    _add(client, auth_headers, primary_group_id, primary_member_id, 100.0)  # the month exists

    payers = [primary_member_id, ghost] * 5
    threads = [
        threading.Thread(target=_add, args=(client, auth_headers, primary_group_id, payer, 100.0 * (i + 2)))
        for i, payer in enumerate(payers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    derived = _month_balances(client, auth_headers, primary_group_id)
    assert len(derived["expenses"]) == 11
    with SessionLocal() as session:
        stored = session.execute(
            text("SELECT balances FROM monthly_shares WHERE group_id = :g"), {"g": primary_group_id}
        ).scalar_one()
    assert stored == derived["balances"]
