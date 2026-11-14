"""Quick-capture endpoints driven by the iOS shortcut token.

The image parser is patched everywhere: Gemini is never called from tests.
"""

import threading
from datetime import date
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import text

from template.adapters.database import SessionLocal
from template.adapters.repositories import MemberRepository
from template.service_layer.image_expense_parser import ParsedImageExpense
from template.service_layer.quick_capture_service import QuickCaptureService

PARSER = "template.service_layer.expense_draft_service.parse_image_expense"
SEND_IF_SUBSCRIBED = "template.service_layer.push_service.PushService.send_if_subscribed"
TOKEN_URL = "/api/v1/members/me/shortcut-token"
URL = "/api/v1/quick-capture"
PNG = b"\x89PNG\r\n\x1a\nfake-image-bytes"


def _parsed(**overrides) -> ParsedImageExpense:
    values = {
        "amount": 5000.0,
        "description": "Supermercado La Esquina",
        "category": "supermercado",
        "expense_date": date(2026, 11, 10),
        "payment_type": "debit",
        "confidence": "high",
        "installments": 1,
        "currency": "ARS",
    }
    values.update(overrides)
    return ParsedImageExpense(**values)


def _shortcut_headers(client, auth_headers) -> dict:
    token = client.post(TOKEN_URL, headers=auth_headers).json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


def _capture(client, headers, parsed=None, content=PNG, mime="image/png"):
    with patch(PARSER, return_value=parsed if parsed is not None else _parsed()):
        return client.post(URL, files={"file": ("shot.png", content, mime)}, headers=headers)


def _add_ghost(client, auth_headers, group_id, name="Guada"):
    r = client.post(f"/api/v1/groups/{group_id}/members", json={"name": name}, headers=auth_headers)
    assert r.status_code == 201, r.text


def _count(sql: str, **params) -> int:
    with SessionLocal() as session:
        return session.execute(text(sql), params).scalar()


def _draft_row(draft_id: int):
    with SessionLocal() as session:
        return session.execute(
            text("SELECT status, amount, image, expense_id, resolved_at FROM expense_drafts WHERE id = :id"),
            {"id": draft_id},
        ).one()


def _personal_group_id(client, auth_headers) -> int:
    return client.get("/api/v1/personal/group", headers=auth_headers).json()["data"]["id"]


def _create_expense(client, auth_headers, group_id, payer_id, description, amount, dt):
    r = client.post(
        f"/api/v1/groups/{group_id}/expenses/",
        json={
            "description": description,
            "amount": amount,
            "date": dt,
            "category": {"name": "supermercado"},
            "payerId": payer_id,
            "paymentType": "debit",
            "installments": 1,
            "splitStrategy": {"type": "equal"},
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


def test_capture_returns_summary_and_group_actions_without_creating(client, auth_headers, primary_group_id):
    _add_ghost(client, auth_headers, primary_group_id)
    headers = _shortcut_headers(client, auth_headers)

    r = _capture(client, headers)

    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "read"
    assert data["summary"] == "🛒 Supermercado La Esquina · $5.000 · pagaste vos · Débito"
    assert data["warning"] is None
    assert data["message"] is None
    personal_id = _personal_group_id(client, auth_headers)
    assert data["actions"] == [
        {"label": "Test Group · $2.500 c/u", "action": "confirm", "groupId": primary_group_id},
        {"label": "Personal · todo tuyo", "action": "confirm", "groupId": personal_id},
        {"label": "Editar en la app", "action": "keep", "groupId": None},
        {"label": "Cancelar", "action": "discard", "groupId": None},
    ]
    assert _count("SELECT count(*) FROM expenses") == 0
    row = _draft_row(data["draftId"])
    assert row.status == "pending"
    assert row.amount == 5000.0
    assert bytes(row.image) == PNG
    assert _count("SELECT suggested_group_id FROM expense_drafts WHERE id = :id", id=data["draftId"]) == (
        primary_group_id
    )


def test_capture_rejects_non_image_without_saving(client, auth_headers):
    headers = _shortcut_headers(client, auth_headers)

    with patch(PARSER) as parser:
        r = client.post(URL, files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")}, headers=headers)
        empty = client.post(URL, files={"file": ("shot.png", b"", "image/png")}, headers=headers)

    assert r.status_code == 400
    assert empty.status_code == 400
    parser.assert_not_called()
    assert _count("SELECT count(*) FROM expense_drafts") == 0


def test_unreadable_capture_keeps_draft_and_pushes(client, auth_headers, primary_group_id, primary_member_id):
    headers = _shortcut_headers(client, auth_headers)

    with patch(PARSER, return_value=None), patch(SEND_IF_SUBSCRIBED, return_value=True) as push:
        r = client.post(URL, files={"file": ("shot.png", PNG, "image/png")}, headers=headers)

    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "unreadable"
    assert data["actions"] == []
    assert data["message"] == "No pude leerla, quedó en borradores"
    row = _draft_row(data["draftId"])
    assert row.status == "pending"
    assert row.amount is None
    assert bytes(row.image) == PNG
    push.assert_called_once()
    args, kwargs = push.call_args
    assert args[:2] == (primary_member_id, "Jirens")
    assert args[3] == "/drafts"
    assert kwargs["tag"] == "drafts-pending"

    # A parser that blows up is just as unreadable, never a 500.
    with patch(PARSER, side_effect=RuntimeError("gemini down")), patch(SEND_IF_SUBSCRIBED, return_value=True):
        r = client.post(URL, files={"file": ("shot.png", PNG, "image/png")}, headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "unreadable"

    # No amount read is unreadable too, and it cannot be confirmed.
    r = _capture(client, headers, _parsed(amount=None))
    assert r.json()["data"]["status"] == "unreadable"
    confirm = client.post(
        f"{URL}/{r.json()['data']['draftId']}/confirm", json={"groupId": primary_group_id}, headers=headers
    )
    assert confirm.status_code == 400
    assert _count("SELECT count(*) FROM expenses") == 0


def test_confirm_creates_one_expense_and_second_confirm_is_409(client, auth_headers, primary_group_id):
    _add_ghost(client, auth_headers, primary_group_id)
    headers = _shortcut_headers(client, auth_headers)
    draft_id = _capture(client, headers).json()["data"]["draftId"]

    r = client.post(f"{URL}/{draft_id}/confirm", json={"groupId": primary_group_id}, headers=headers)

    assert r.status_code == 200, r.text
    assert r.json()["data"] == {"message": "Gasto creado · $5.000 · Test Group"}
    assert _count("SELECT count(*) FROM expenses WHERE group_id = :g", g=primary_group_id) == 1
    row = _draft_row(draft_id)
    assert row.status == "confirmed"
    assert row.image is None
    assert row.expense_id is not None
    assert row.resolved_at is not None

    again = client.post(f"{URL}/{draft_id}/confirm", json={"groupId": primary_group_id}, headers=headers)
    assert again.status_code == 409
    assert again.json()["detail"] == "Ese borrador ya se resolvió"
    assert _count("SELECT count(*) FROM expenses") == 1


def test_concurrent_confirms_create_one_expense(client, auth_headers, primary_group_id, primary_member_id):
    """Double tap on the shortcut: two confirms racing in two sessions land one expense."""
    headers = _shortcut_headers(client, auth_headers)
    draft_id = _capture(client, headers).json()["data"]["draftId"]
    barrier = threading.Barrier(2)
    outcomes: list = []

    def confirm():
        with SessionLocal() as session:
            member = MemberRepository(session).get(primary_member_id)
            barrier.wait()
            try:
                QuickCaptureService(session).confirm(member, draft_id, primary_group_id, BackgroundTasks())
                outcomes.append(200)
            except HTTPException as exc:
                outcomes.append(exc.status_code)

    threads = [threading.Thread(target=confirm) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == [200, 409]
    assert _count("SELECT count(*) FROM expenses") == 1


def test_confirm_into_settled_month_is_409_and_draft_stays_pending(
    client, auth_headers, primary_group_id, primary_member_id
):
    _add_ghost(client, auth_headers, primary_group_id)
    _create_expense(client, auth_headers, primary_group_id, primary_member_id, "Luz", 1000.0, "2026-09-05")
    settle = client.post(f"/api/v1/groups/{primary_group_id}/shares/settle/2026/9", headers=auth_headers)
    assert settle.status_code == 200, settle.text
    before = _count("SELECT count(*) FROM expenses")
    headers = _shortcut_headers(client, auth_headers)
    draft_id = _capture(client, headers, _parsed(expense_date=date(2026, 9, 15))).json()["data"]["draftId"]

    r = client.post(f"{URL}/{draft_id}/confirm", json={"groupId": primary_group_id}, headers=headers)

    assert r.status_code == 409
    assert "saldado" in r.json()["detail"]
    row = _draft_row(draft_id)
    assert row.status == "pending"
    assert bytes(row.image) == PNG
    assert row.expense_id is None
    assert _count("SELECT count(*) FROM expenses") == before


def test_confirm_someone_elses_draft_is_404(client, auth_headers, primary_group_id, secondary_member_id):
    headers = _shortcut_headers(client, auth_headers)
    draft_id = _capture(client, headers).json()["data"]["draftId"]
    jwt = client.post(
        "/api/v1/auth/token", data={"username": "counterparty@example.com", "password": "secret123"}
    ).json()["access_token"]
    other = _shortcut_headers(client, {"Authorization": f"Bearer {jwt}"})

    assert (
        client.post(f"{URL}/{draft_id}/confirm", json={"groupId": primary_group_id}, headers=other).status_code == 404
    )
    assert client.post(f"{URL}/{draft_id}/keep", headers=other).status_code == 404
    assert client.delete(f"{URL}/{draft_id}", headers=other).status_code == 404
    assert _draft_row(draft_id).status == "pending"


def test_confirm_into_unavailable_group_is_400(client, auth_headers, primary_group_id, secondary_member_id):
    headers = _shortcut_headers(client, auth_headers)
    draft_id = _capture(client, headers).json()["data"]["draftId"]
    jwt = client.post(
        "/api/v1/auth/token", data={"username": "counterparty@example.com", "password": "secret123"}
    ).json()["access_token"]
    foreign = client.post("/api/v1/groups/", json={"name": "Ajeno"}, headers={"Authorization": f"Bearer {jwt}"})
    foreign_id = foreign.json()["data"]["id"]

    r = client.post(f"{URL}/{draft_id}/confirm", json={"groupId": foreign_id}, headers=headers)
    assert r.status_code == 400
    assert r.json()["detail"] == "Ese grupo no está disponible"

    assert client.post(f"/api/v1/groups/{primary_group_id}/archive", headers=auth_headers).status_code == 204
    r = client.post(f"{URL}/{draft_id}/confirm", json={"groupId": primary_group_id}, headers=headers)
    assert r.status_code == 400
    assert _draft_row(draft_id).status == "pending"
    assert _count("SELECT count(*) FROM expenses") == 0


def test_confirm_in_personal_group_assigns_full_amount(client, auth_headers, primary_member_id):
    headers = _shortcut_headers(client, auth_headers)
    draft_id = _capture(client, headers).json()["data"]["draftId"]
    personal_id = _personal_group_id(client, auth_headers)

    r = client.post(f"{URL}/{draft_id}/confirm", json={"groupId": personal_id}, headers=headers)

    assert r.status_code == 200, r.text
    assert r.json()["data"]["message"] == "Gasto creado · $5.000 · Personal"
    with SessionLocal() as session:
        expense = session.execute(text("SELECT amount, payer_id, split_strategy, group_id FROM expenses")).one()
        balances = session.execute(
            text("SELECT balances FROM monthly_shares WHERE group_id = :g"), {"g": personal_id}
        ).scalar()
    assert expense.amount == 5000.0
    assert expense.payer_id == primary_member_id
    assert expense.group_id == personal_id
    assert expense.split_strategy["type"] == "equal"
    assert not expense.split_strategy.get("participant_ids")
    assert all(abs(v) < 0.01 for v in balances.values())  # sole member: owes nothing to anyone


def test_credit_capture_does_not_offer_one_time_group(client, auth_headers):
    trip = client.post("/api/v1/groups/", json={"name": "Buzios", "groupType": "one_time"}, headers=auth_headers)
    trip_id = trip.json()["data"]["id"]
    headers = _shortcut_headers(client, auth_headers)

    r = _capture(client, headers, _parsed(payment_type="credit", installments=3))

    data = r.json()["data"]
    group_ids = [a["groupId"] for a in data["actions"] if a["action"] == "confirm"]
    assert trip_id not in group_ids
    assert group_ids == [_personal_group_id(client, auth_headers)]
    assert "3 cuotas" in data["summary"]


def test_similar_expense_adds_warning(client, auth_headers, primary_group_id, primary_member_id):
    _create_expense(
        client, auth_headers, primary_group_id, primary_member_id, "Supermercado La Esquina", 5000.0, "2026-11-10"
    )
    headers = _shortcut_headers(client, auth_headers)

    r = _capture(client, headers)

    data = r.json()["data"]
    assert data["warning"] == "⚠️ Parecido a uno que ya cargaste: $5.000 Supermercado La Esquina"
    assert len([a for a in data["actions"] if a["action"] == "confirm"]) == 2  # does not block


def test_keep_pushes_and_discard_clears_image(client, auth_headers):
    headers = _shortcut_headers(client, auth_headers)
    draft_id = _capture(client, headers).json()["data"]["draftId"]

    with patch(SEND_IF_SUBSCRIBED, return_value=True) as push:
        r = client.post(f"{URL}/{draft_id}/keep", headers=headers)
    assert r.status_code == 200
    assert r.json()["data"] == {"message": "Guardado en borradores"}
    assert push.call_args.kwargs["tag"] == "drafts-pending"
    assert _draft_row(draft_id).status == "pending"

    r = client.delete(f"{URL}/{draft_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["data"] == {"message": "Descartado"}
    row = _draft_row(draft_id)
    assert row.status == "discarded"
    assert row.image is None
    assert row.resolved_at is not None


def test_revoked_token_gets_401(client, auth_headers):
    old = _shortcut_headers(client, auth_headers)
    draft_id = _capture(client, old).json()["data"]["draftId"]
    _shortcut_headers(client, auth_headers)  # regenerate: the old one is revoked

    assert _capture(client, old).status_code == 401
    assert client.post(f"{URL}/{draft_id}/confirm", json={"groupId": 1}, headers=old).status_code == 401
    assert client.post(f"{URL}/{draft_id}/keep", headers=old).status_code == 401
    assert client.delete(f"{URL}/{draft_id}", headers=old).status_code == 401
    assert _capture(client, auth_headers).status_code == 401  # a JWT is not a shortcut token
