"""Shortcut token profile endpoints and its isolation from JWT auth."""

URL = "/api/v1/members/me/shortcut-token"


def test_profile_flow_issue_status_revoke(client, auth_headers):
    r = client.get(URL, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["data"] == {"connected": False, "prefix": None, "createdAt": None, "lastUsedAt": None}

    r = client.post(URL, headers=auth_headers)
    assert r.status_code == 201
    issued = r.json()["data"]
    assert issued["token"].startswith("jrn_")
    assert issued["prefix"] == issued["token"][:8]

    r = client.get(URL, headers=auth_headers)
    status = r.json()["data"]
    assert status["connected"] is True
    assert status["prefix"] == issued["prefix"]
    assert "token" not in status

    second = client.post(URL, headers=auth_headers).json()["data"]
    assert second["token"] != issued["token"]

    assert client.delete(URL, headers=auth_headers).status_code == 204
    assert client.get(URL, headers=auth_headers).json()["data"]["connected"] is False


def test_shortcut_token_requires_login(client):
    assert client.get(URL).status_code == 401
    assert client.post(URL).status_code == 401


def test_shortcut_token_is_rejected_by_jwt_routes(client, auth_headers):
    token = client.post(URL, headers=auth_headers).json()["data"]["token"]
    r = client.get("/api/v1/members/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_get_shortcut_member_accepts_live_token_only(client, auth_headers, primary_member_id):
    from fastapi import Depends  # pylint: disable=import-outside-toplevel

    from template.domain.models.member import (
        Member,  # pylint: disable=import-outside-toplevel
    )
    from template.service_layer.shortcut_token_service import (  # pylint: disable=import-outside-toplevel
        get_shortcut_member,
    )

    @client.app.get("/_probe/shortcut")
    def probe(member: Member = Depends(get_shortcut_member)):
        return {"id": member.id}

    def call(headers):
        return client.get("/_probe/shortcut", headers=headers)

    old = client.post(URL, headers=auth_headers).json()["data"]["token"]
    assert call({"Authorization": f"Bearer {old}"}).json() == {"id": primary_member_id}
    assert call({}).status_code == 401
    assert call(auth_headers).status_code == 401  # a JWT is not a shortcut token
    assert call({"Authorization": "Bearer jrn_nope"}).status_code == 401

    new = client.post(URL, headers=auth_headers).json()["data"]["token"]
    stale = call({"Authorization": f"Bearer {old}"})
    assert stale.status_code == 401
    assert stale.headers["www-authenticate"] == "Bearer"
    assert call({"Authorization": f"Bearer {new}"}).status_code == 200

    client.delete(URL, headers=auth_headers)
    assert call({"Authorization": f"Bearer {new}"}).status_code == 401
