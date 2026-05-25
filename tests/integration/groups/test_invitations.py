"""Integration tests for group invitation endpoints."""

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register(client, name, email, telephone, password="secret123"):
    r = client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "telephone": telephone, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _token_headers(client, email, password="secret123"):
    r = client.post("/api/v1/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_group(client, headers, name="Test Group"):
    r = client.post("/api/v1/groups/", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


# ---------------------------------------------------------------------------
# Email-channel invitation
# ---------------------------------------------------------------------------


class TestEmailInvitation:
    def test_invite_unknown_email_creates_stub_and_pending_invitation(self, client, auth_headers, primary_group_id):
        r = client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Bob", "channel": "email", "contact": "bob@example.com"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        assert data["status"] == "pending"
        assert data["shareUrl"] is not None
        assert "bob@example.com" in data["target"]

    def test_stub_appears_in_group_member_list(self, client, auth_headers, primary_group_id):
        client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Carol", "channel": "email", "contact": "carol@example.com"},
            headers=auth_headers,
        )
        r = client.get(f"/api/v1/groups/{primary_group_id}/members", headers=auth_headers)
        names = [m["name"] for m in r.json()["data"]]
        assert "Carol" in names

    def test_stub_is_marked_pending(self, client, auth_headers, primary_group_id):
        client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Dave", "channel": "email", "contact": "dave@example.com"},
            headers=auth_headers,
        )
        r = client.get(f"/api/v1/groups/{primary_group_id}/members", headers=auth_headers)
        dave = next(m for m in r.json()["data"] if m["name"] == "Dave")
        assert dave["isStub"] is True

    def test_existing_member_already_in_group_returns_400(self, client, auth_headers, primary_group_id):
        r = client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Tester", "channel": "email", "contact": "tester@example.com"},
            headers=auth_headers,
        )
        assert r.status_code == 400
        assert "already a member" in r.json()["detail"]

    def test_list_invitations_returns_pending(self, client, auth_headers, primary_group_id):
        client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Eve", "channel": "email", "contact": "eve@example.com"},
            headers=auth_headers,
        )
        r = client.get(f"/api/v1/groups/{primary_group_id}/invitations", headers=auth_headers)
        assert r.status_code == 200
        inv_list = r.json()["data"]
        assert len(inv_list) >= 1
        assert inv_list[0]["status"] == "pending"

    def test_revoke_invitation_removes_stub_from_group(self, client, auth_headers, primary_group_id):
        r = client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Frank", "channel": "email", "contact": "frank@example.com"},
            headers=auth_headers,
        )
        token = r.json()["data"]["shareUrl"].split("/")[-1]

        r = client.delete(
            f"/api/v1/groups/{primary_group_id}/invitations/{token}",
            headers=auth_headers,
        )
        assert r.status_code == 204

        r = client.get(f"/api/v1/groups/{primary_group_id}/members", headers=auth_headers)
        names = [m["name"] for m in r.json()["data"]]
        assert "Frank" not in names

    def test_resolve_pending_token_returns_correct_fields(self, client, auth_headers, primary_group_id):
        r = client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Grace", "channel": "email", "contact": "grace@example.com"},
            headers=auth_headers,
        )
        token = r.json()["data"]["shareUrl"].split("/")[-1]

        r = client.get(f"/api/v1/invitations/resolve/{token}")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["status"] == "pending"
        assert data["requiresPassword"] is True
        assert data["requiresEmail"] is False
        assert data["knownEmail"] == "grace@example.com"

    def test_accept_invitation_creates_real_account_and_returns_token(self, client, auth_headers, primary_group_id):
        r = client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Heidi", "channel": "email", "contact": "heidi@example.com"},
            headers=auth_headers,
        )
        inv_token = r.json()["data"]["shareUrl"].split("/")[-1]

        r = client.post(
            f"/api/v1/invitations/{inv_token}/accept",
            json={"password": "newpass123"},
        )
        assert r.status_code == 200, r.text
        assert "accessToken" in r.json()["data"]

    def test_accepted_member_can_list_groups(self, client, auth_headers, primary_group_id):
        r = client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Ivan", "channel": "email", "contact": "ivan@example.com"},
            headers=auth_headers,
        )
        inv_token = r.json()["data"]["shareUrl"].split("/")[-1]

        accept_r = client.post(
            f"/api/v1/invitations/{inv_token}/accept",
            json={"password": "newpass123"},
        )
        ivan_token = accept_r.json()["data"]["accessToken"]
        ivan_headers = {"Authorization": f"Bearer {ivan_token}"}

        r = client.get("/api/v1/groups/", headers=ivan_headers)
        assert r.status_code == 200
        group_ids = [g["id"] for g in r.json()["data"]]
        assert primary_group_id in group_ids


# ---------------------------------------------------------------------------
# Phone-channel invitation
# ---------------------------------------------------------------------------


class TestPhoneInvitation:
    def test_invite_by_phone_creates_stub_with_null_email(self, client, auth_headers, primary_group_id):
        r = client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Juan", "channel": "phone", "contact": "541138718498"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        assert r.json()["data"]["status"] == "pending"

    def test_resolve_phone_invite_requires_email(self, client, auth_headers, primary_group_id):
        r = client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Maria", "channel": "phone", "contact": "541155550000"},
            headers=auth_headers,
        )
        inv_token = r.json()["data"]["shareUrl"].split("/")[-1]

        r = client.get(f"/api/v1/invitations/resolve/{inv_token}")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["requiresEmail"] is True
        assert data["requiresPassword"] is True

    def test_accept_phone_invite_with_email_and_password(self, client, auth_headers, primary_group_id):
        r = client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Pedro", "channel": "phone", "contact": "541166660000"},
            headers=auth_headers,
        )
        inv_token = r.json()["data"]["shareUrl"].split("/")[-1]

        r = client.post(
            f"/api/v1/invitations/{inv_token}/accept",
            json={"email": "pedro@example.com", "password": "pass9999"},
        )
        assert r.status_code == 200, r.text
        assert "accessToken" in r.json()["data"]

    def test_phone_normalisation_strips_extra_9(self, client, auth_headers, primary_group_id):
        """Inviting 5491138718498 should store as 541138718498 and de-duplicate correctly."""
        r = client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Ana", "channel": "phone", "contact": "5491138718498"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        assert data["target"] == "541138718498"


# ---------------------------------------------------------------------------
# Shareable join link
# ---------------------------------------------------------------------------


class TestJoinLink:
    def test_get_join_link_returns_url(self, client, auth_headers, primary_group_id):
        r = client.post(f"/api/v1/groups/{primary_group_id}/join-link", headers=auth_headers)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert "token" in data
        assert "url" in data

    def test_get_join_link_is_idempotent(self, client, auth_headers, primary_group_id):
        r1 = client.post(f"/api/v1/groups/{primary_group_id}/join-link", headers=auth_headers)
        r2 = client.post(f"/api/v1/groups/{primary_group_id}/join-link", headers=auth_headers)
        assert r1.json()["data"]["token"] == r2.json()["data"]["token"]

    def test_rotate_changes_token(self, client, auth_headers, primary_group_id):
        r1 = client.post(f"/api/v1/groups/{primary_group_id}/join-link", headers=auth_headers)
        old_token = r1.json()["data"]["token"]
        r2 = client.post(f"/api/v1/groups/{primary_group_id}/join-link/rotate", headers=auth_headers)
        assert r2.json()["data"]["token"] != old_token

    def test_resolve_join_token_returns_group_name(self, client, auth_headers, primary_group_id):
        r = client.post(f"/api/v1/groups/{primary_group_id}/join-link", headers=auth_headers)
        token = r.json()["data"]["token"]

        r = client.get(f"/api/v1/join/resolve/{token}")
        assert r.status_code == 200
        assert r.json()["data"]["groupName"] == "Test Group"

    def test_register_and_join_creates_member_in_group(self, client, auth_headers, primary_group_id):
        r = client.post(f"/api/v1/groups/{primary_group_id}/join-link", headers=auth_headers)
        token = r.json()["data"]["token"]

        r = client.post(
            f"/api/v1/join/{token}",
            json={"name": "Newcomer", "email": "newcomer@example.com", "password": "pass1234"},
        )
        assert r.status_code == 200, r.text
        new_token = r.json()["data"]["accessToken"]
        new_headers = {"Authorization": f"Bearer {new_token}"}

        r = client.get("/api/v1/groups/", headers=new_headers)
        group_ids = [g["id"] for g in r.json()["data"]]
        assert primary_group_id in group_ids

    def test_register_and_join_existing_email_returns_400(self, client, auth_headers, primary_group_id):
        r = client.post(f"/api/v1/groups/{primary_group_id}/join-link", headers=auth_headers)
        token = r.json()["data"]["token"]

        r = client.post(
            f"/api/v1/join/{token}",
            json={"name": "Dup", "email": "tester@example.com", "password": "pass1234"},
        )
        assert r.status_code == 400

    def test_non_member_cannot_get_join_link(self, client, primary_group_id):
        _register(client, "Outsider", "outsider@example.com", "541177770000")
        outsider_headers = _token_headers(client, "outsider@example.com")

        r = client.post(f"/api/v1/groups/{primary_group_id}/join-link", headers=outsider_headers)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Stub appears in expense splits
# ---------------------------------------------------------------------------


class TestStubInExpenses:
    def test_stub_member_has_share_in_equal_expense(self, client, auth_headers, primary_group_id):
        """Stub appears in the monthly balance even before accepting the invitation."""
        client.post(
            f"/api/v1/groups/{primary_group_id}/invitations",
            json={"name": "Zara", "channel": "email", "contact": "zara@example.com"},
            headers=auth_headers,
        )

        # Get members to find Zara's id
        r = client.get(f"/api/v1/groups/{primary_group_id}/members", headers=auth_headers)
        zara = next(m for m in r.json()["data"] if m["name"] == "Zara")
        zara_id = zara["memberId"]

        # Create an equal expense
        r = client.get("/api/v1/members/me", headers=auth_headers)
        my_id = r.json()["data"]["id"]
        client.post(
            f"/api/v1/groups/{primary_group_id}/expenses/",
            json={
                "description": "Groceries",
                "amount": 100.0,
                "date": "2025-06-01",
                "category": {"name": "comida"},
                "payerId": my_id,
                "paymentType": "debit",
                "installments": 1,
                "splitStrategy": {"type": "equal"},
            },
            headers=auth_headers,
        )

        r = client.get(f"/api/v1/groups/{primary_group_id}/shares/2025/6", headers=auth_headers)
        balances = r.json()["data"]["balances"]
        assert str(zara_id) in balances
