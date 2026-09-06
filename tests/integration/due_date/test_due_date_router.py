"""CRUD de vencimientos, incluida la puerta de acceso al grupo."""


def _payload(**overrides):
    data = {
        "label": "Luz",
        "dayOfMonth": 20,
        "everyNMonths": 1,
        "anchorYear": 2026,
        "anchorMonth": 10,
        "notifyDaysBefore": 3,
    }
    data.update(overrides)
    return data


def _create_group(client, auth_headers, name="Depto"):
    response = client.post("/api/v1/groups/", json={"name": name}, headers=auth_headers)
    assert response.status_code in (200, 201)
    return response.json()["data"]["id"]


def test_create_and_list(client, auth_headers):
    group_id = _create_group(client, auth_headers)

    created = client.post(f"/api/v1/groups/{group_id}/due-dates/", json=_payload(), headers=auth_headers)
    assert created.status_code == 201
    assert created.json()["data"]["label"] == "Luz"
    assert created.json()["data"]["notifyDaysBefore"] == 3

    listed = client.get(f"/api/v1/groups/{group_id}/due-dates/", headers=auth_headers)
    assert listed.status_code == 200
    assert [d["label"] for d in listed.json()["data"]] == ["Luz"]


def test_update_is_partial(client, auth_headers):
    group_id = _create_group(client, auth_headers)
    created = client.post(f"/api/v1/groups/{group_id}/due-dates/", json=_payload(), headers=auth_headers).json()["data"]

    updated = client.put(
        f"/api/v1/groups/{group_id}/due-dates/{created['id']}",
        json={"notifyDaysBefore": 7},
        headers=auth_headers,
    )

    assert updated.status_code == 200
    assert updated.json()["data"]["notifyDaysBefore"] == 7
    assert updated.json()["data"]["dayOfMonth"] == 20


def test_delete(client, auth_headers):
    group_id = _create_group(client, auth_headers)
    created = client.post(f"/api/v1/groups/{group_id}/due-dates/", json=_payload(), headers=auth_headers).json()["data"]

    deleted = client.delete(f"/api/v1/groups/{group_id}/due-dates/{created['id']}", headers=auth_headers)
    assert deleted.status_code in (200, 204)
    assert client.get(f"/api/v1/groups/{group_id}/due-dates/", headers=auth_headers).json()["data"] == []


def test_a_non_member_cannot_read_or_write(client, auth_headers):
    group_id = _create_group(client, auth_headers)

    client.post(
        "/api/v1/auth/register",
        json={"name": "Otro", "email": "otro@example.com", "password": "secret123", "telephone": "5411999999"},
    )
    token = client.post("/api/v1/auth/token", data={"username": "otro@example.com", "password": "secret123"}).json()[
        "access_token"
    ]
    other = {"Authorization": f"Bearer {token}"}

    assert client.get(f"/api/v1/groups/{group_id}/due-dates/", headers=other).status_code == 403
    assert client.post(f"/api/v1/groups/{group_id}/due-dates/", json=_payload(), headers=other).status_code == 403


def test_editing_a_due_date_from_another_group_is_not_found(client, auth_headers):
    """Pasar el group_id propio no debe habilitar el vencimiento de otro grupo."""
    mine = _create_group(client, auth_headers, name="Mío")
    theirs = _create_group(client, auth_headers, name="Otro")
    created = client.post(f"/api/v1/groups/{theirs}/due-dates/", json=_payload(), headers=auth_headers).json()["data"]

    response = client.put(
        f"/api/v1/groups/{mine}/due-dates/{created['id']}",
        json={"notifyDaysBefore": 7},
        headers=auth_headers,
    )

    assert response.status_code == 404


def test_day_32_is_rejected(client, auth_headers):
    group_id = _create_group(client, auth_headers)
    response = client.post(f"/api/v1/groups/{group_id}/due-dates/", json=_payload(dayOfMonth=32), headers=auth_headers)
    assert response.status_code == 422
