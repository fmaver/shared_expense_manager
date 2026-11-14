"""Draft endpoints for the PWA (JWT). The image parser is always patched."""

from unittest.mock import patch

from tests.integration.quick_capture.test_quick_capture_router import (
    PARSER,
    PNG,
    SEND_IF_SUBSCRIBED,
    _capture,
    _count,
    _draft_row,
    _parsed,
    _shortcut_headers,
)

URL = "/api/v1/drafts"


def _other_jwt_headers(client) -> dict:
    jwt = client.post(
        "/api/v1/auth/token", data={"username": "counterparty@example.com", "password": "secret123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {jwt}"}


def _save_for_later(client, auth_headers, parsed=None, content=PNG, mime="image/png"):
    with patch(PARSER, return_value=parsed if parsed is not None else _parsed()):
        return client.post(URL, files={"file": ("shot.png", content, mime)}, headers=auth_headers)


def test_list_only_my_pending_drafts(client, auth_headers, primary_group_id, secondary_member_id):
    shortcut = _shortcut_headers(client, auth_headers)
    first = _capture(client, shortcut).json()["data"]["draftId"]
    second = _capture(client, shortcut).json()["data"]["draftId"]
    gone = _capture(client, shortcut).json()["data"]["draftId"]
    client.delete(f"/api/v1/quick-capture/{gone}", headers=shortcut)
    other = _other_jwt_headers(client)
    other_short = _shortcut_headers(client, other)
    _capture(client, other_short)

    r = client.get(URL, headers=auth_headers)

    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert [d["id"] for d in data] == [first, second]
    assert data[0]["amount"] == 5000.0
    assert data[0]["hasImage"] is True
    assert data[0]["suggestedGroupId"] == primary_group_id
    assert data[0]["suggestedGroupName"] == "Test Group"
    assert data[0]["createdAt"].endswith(("Z", "+00:00")), data[0]["createdAt"]
    assert len(client.get(URL, headers=other).json()["data"]) == 1


def test_image_endpoint_returns_bytes_and_404_for_others(client, auth_headers, secondary_member_id):
    draft_id = _capture(client, _shortcut_headers(client, auth_headers)).json()["data"]["draftId"]

    r = client.get(f"{URL}/{draft_id}/image", headers=auth_headers)
    assert r.status_code == 200
    assert r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "private, no-store"
    assert client.get(f"{URL}/{draft_id}/image", headers=_other_jwt_headers(client)).status_code == 404
    assert client.get(f"{URL}/99999/image", headers=auth_headers).status_code == 404


def test_save_for_later_rejects_svg_without_saving(client, auth_headers):
    with patch(PARSER) as parser:
        r = client.post(URL, files={"file": ("x.svg", b"<svg onload='x'/>", "image/svg+xml")}, headers=auth_headers)

    assert r.status_code == 400
    parser.assert_not_called()
    assert _count("SELECT count(*) FROM expense_drafts") == 0


def test_resolve_then_list_is_empty_and_image_is_cleared(client, auth_headers):
    draft_id = _capture(client, _shortcut_headers(client, auth_headers)).json()["data"]["draftId"]

    r = client.post(f"{URL}/{draft_id}/resolve", headers=auth_headers)

    assert r.status_code == 204
    assert client.get(URL, headers=auth_headers).json()["data"] == []
    row = _draft_row(draft_id)
    assert row.status == "confirmed"
    assert row.image is None
    assert row.image_mime is None
    assert row.resolved_at is not None
    assert row.expense_id is None
    assert client.get(f"{URL}/{draft_id}/image", headers=auth_headers).status_code == 404
    assert client.post(f"{URL}/{draft_id}/resolve", headers=auth_headers).status_code == 409


def test_resolve_someone_elses_draft_is_404(client, auth_headers, secondary_member_id):
    draft_id = _capture(client, _shortcut_headers(client, auth_headers)).json()["data"]["draftId"]
    other = _other_jwt_headers(client)

    assert client.post(f"{URL}/{draft_id}/resolve", headers=other).status_code == 404
    assert client.delete(f"{URL}/{draft_id}", headers=other).status_code == 404
    assert client.post(f"{URL}/{draft_id}/confirm", json={"groupId": 1}, headers=other).status_code == 404
    assert _draft_row(draft_id).status == "pending"


def test_confirm_from_pwa_creates_expense_in_suggested_group(client, auth_headers, primary_group_id):
    draft_id = _capture(client, _shortcut_headers(client, auth_headers)).json()["data"]["draftId"]
    suggested = client.get(URL, headers=auth_headers).json()["data"][0]["suggestedGroupId"]

    r = client.post(f"{URL}/{draft_id}/confirm", json={"groupId": suggested}, headers=auth_headers)

    assert r.status_code == 200, r.text
    assert r.json()["data"]["amount"] == 5000.0
    assert _count("SELECT count(*) FROM expenses WHERE group_id = :g", g=suggested) == 1
    assert _draft_row(draft_id).status == "confirmed"
    assert client.get(URL, headers=auth_headers).json()["data"] == []


def test_discard_from_pwa(client, auth_headers):
    draft_id = _capture(client, _shortcut_headers(client, auth_headers)).json()["data"]["draftId"]

    assert client.delete(f"{URL}/{draft_id}", headers=auth_headers).status_code == 204
    assert _draft_row(draft_id).status == "discarded"


def test_drafts_routes_reject_shortcut_token(client, auth_headers):
    shortcut = _shortcut_headers(client, auth_headers)
    draft_id = _capture(client, shortcut).json()["data"]["draftId"]

    assert client.get(URL, headers=shortcut).status_code == 401
    assert client.get(f"{URL}/{draft_id}/image", headers=shortcut).status_code == 401
    assert client.post(f"{URL}/{draft_id}/resolve", headers=shortcut).status_code == 401
    assert client.delete(f"{URL}/{draft_id}", headers=shortcut).status_code == 401


def test_save_for_later_reads_and_appears_in_list(client, auth_headers, primary_group_id):
    with patch(SEND_IF_SUBSCRIBED) as push:
        r = _save_for_later(client, auth_headers)

    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["amount"] == 5000.0
    assert data["hasImage"] is True
    assert data["suggestedGroupId"] == primary_group_id
    push.assert_not_called()
    assert _count("SELECT count(*) FROM expenses") == 0
    listed = client.get(URL, headers=auth_headers).json()["data"]
    assert [d["id"] for d in listed] == [data["id"]]
    assert listed[0]["amount"] == 5000.0
    assert listed[0]["suggestedGroupId"] == primary_group_id


def test_save_for_later_unreadable_is_saved_without_push(client, auth_headers):
    with patch(PARSER, return_value=None), patch(SEND_IF_SUBSCRIBED) as push:
        r = client.post(URL, files={"file": ("shot.png", PNG, "image/png")}, headers=auth_headers)

    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["amount"] is None
    assert data["suggestedGroupId"] is None
    assert data["suggestedGroupName"] is None
    push.assert_not_called()
    assert _draft_row(data["id"]).status == "pending"


def test_save_for_later_rejects_non_image(client, auth_headers):
    with patch(PARSER) as parser:
        r = client.post(URL, files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")}, headers=auth_headers)

    assert r.status_code == 400
    parser.assert_not_called()
    assert _count("SELECT count(*) FROM expense_drafts") == 0
