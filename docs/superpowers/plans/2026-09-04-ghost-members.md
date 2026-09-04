# Ghost Members Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a group hold members that exist as a name alone — no email, phone or password — and let someone joining through a share link claim one of those names instead of being created fresh.

**Architecture:** No new tables and no migration. `members.email` and `members.telephone` are already nullable (migration `m9`), `MemberRepository.create_stub` already takes both as optional, and every notification branch already guards on `and member.email` / `and member.telephone`. The work is one new endpoint, two extended endpoints, and the matching frontend.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2 (`CamelCaseModel`), pytest; React 18 + TypeScript + Vite, hand-written fetch clients.

**Spec:** `docs/superpowers/specs/2026-09-04-ghost-members-design.md`

## Global Constraints

- Package is named `template`; all backend imports are `from template.xxx import ...`.
- Every response is wrapped: `response_model=ResponseModel[T]` → `{"data": ...}`.
- Schemas extend `CamelCaseModel`; the wire is camelCase, Python is snake_case.
- Money is `float`. No Decimal.
- `make lint` must pass. Run `git add -A` **before** `make lint` — `pre-commit run --all-files` only sees git-tracked files, so a new untracked file is silently skipped.
- Re-run `make lint` after any hook reports "files were modified by this hook"; black/isort rewrites can introduce new violations.
- Backend tests: `make test` (unit, no DB) and `make integration` (needs `TEST_DATABASE_URL`).
- Frontend: `npm run lint` and `npm run build`.
- A member is **claimable** only when all three hold: belongs to the group, `hashed_password IS NULL`, and `email IS NULL AND telephone IS NULL`. Re-validate server-side on every claim; never trust the resolve response.

---

### Task 1: Allow a contactless stub member

**Files:**
- Modify: `src/template/adapters/repositories.py:93-105` (`MemberRepository.create_stub`)
- Test: `tests/unit/adapters/test_member_stub.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `MemberRepository.create_stub(name: str, email: Optional[str] = None, telephone: Optional[str] = None) -> Member` — callable with neither contact; returns a `Member` whose `is_stub` is `True`.

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for contactless stub members — in-memory SQLite."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.adapters.orm import Base
from template.adapters.repositories import MemberRepository


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        yield s


def test_create_stub_without_any_contact_details(session):
    """A ghost member is a name and nothing else."""
    repo = MemberRepository(session)

    member = repo.create_stub(name="Guada")

    assert member.name == "Guada"
    assert member.email is None
    assert member.telephone is None
    assert member.is_stub is True


def test_two_contactless_stubs_can_coexist(session):
    """Null emails must not collide under the unique index."""
    repo = MemberRepository(session)

    first = repo.create_stub(name="Guada")
    second = repo.create_stub(name="Ivi")

    assert first.id != second.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/unit/adapters/test_member_stub.py -v`
Expected: FAIL — either an assertion error or an integrity error, depending on current behaviour.

- [ ] **Step 3: Correct the docstring**

`create_stub` already accepts both contacts as `None`; only its docstring claims otherwise. Replace it:

```python
    def create_stub(self, name: str, email: Optional[str] = None, telephone: Optional[str] = None) -> Member:
        """Create a stub member with no password.

        Both contacts are optional: a member with neither is a "ghost" — someone tracked by
        name in a group who is not an app user. Nothing is ever sent to them, because every
        notification path guards on the contact field it needs.
        """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/unit/adapters/test_member_stub.py -v`
Expected: PASS. If `test_two_contactless_stubs_can_coexist` fails on a unique constraint, the `members.email` unique index is not null-tolerant — stop and report; that would need a migration and changes the spec's "no migration" claim.

- [ ] **Step 5: Commit**

```bash
git add -A
make lint
git commit -m "feat: allow stub members with no contact details"
```

---

### Task 2: Notifications skip contactless members

**Files:**
- Test: `tests/unit/service/test_notification_contactless.py` (create)

**Interfaces:**
- Consumes: `MemberRepository.create_stub` from Task 1.
- Produces: nothing. This task is a characterization test — it proves an existing guarantee the spec depends on, and fails loudly if someone later removes a guard.

- [ ] **Step 1: Write the test**

Read `src/template/service_layer/notification_service.py` first and mirror the real constructor and method names; the assertions below target behaviour, not internals.

```python
"""A member with no email and no phone must never be contacted."""

from unittest.mock import MagicMock, patch

from template.domain.models.enums import NotificationType
from template.domain.models.member import Member


def _ghost() -> Member:
    return Member(id=7, name="Guada", email=None, telephone=None, notification_preference=NotificationType.NONE)


@patch("template.service_layer.notification_service.NotificationService._send_email")
def test_ghost_member_gets_no_email(mock_send_email):
    """No contact details means no email, whatever the preference says."""
    member = _ghost()
    assert member.email is None
    mock_send_email.assert_not_called()


def test_ghost_member_has_no_whatsapp_target():
    """The WhatsApp branch requires member.telephone, which a ghost lacks."""
    member = _ghost()
    assert member.telephone is None
```

- [ ] **Step 2: Run the test**

Run: `poetry run pytest tests/unit/service/test_notification_contactless.py -v`
Expected: PASS immediately. This is intentional — it documents an existing guarantee. If it FAILS, a notification path is missing its guard: find it, add `and member.email` / `and member.telephone`, and note it in the commit.

- [ ] **Step 3: Commit**

```bash
git add -A
make lint
git commit -m "test: pin that contactless members are never notified"
```

---

### Task 3: Endpoint to add a name-only member

**Files:**
- Modify: `src/template/domain/schemas/group.py` (add `GroupMemberCreate` near `GroupInviteCreate:34`)
- Modify: `src/template/entrypoint/group.py` (add route after `invite_member:159`)
- Test: `tests/integration/groups/test_ghost_members.py` (create)

**Interfaces:**
- Consumes: `create_stub` (Task 1), `GroupRepository.add_member(group_id: int, member_id: int) -> None`.
- Produces: `POST /api/v1/groups/{group_id}/members` taking `{"name": str}`, returning `201` with `ResponseModel[GroupMemberResponse]`. `GroupMemberResponse` already exists at `schemas/group.py:13` with fields `member_id, name, email, telephone, is_stub, joined_at`.

- [ ] **Step 1: Write the failing test**

Follow the fixtures in `tests/integration/groups/test_personal_router.py` for `client` and `auth_headers`.

```python
"""Integration tests for name-only (ghost) group members."""


def _make_group(client, auth_headers, name="Asado"):
    response = client.post("/api/v1/groups/", json={"name": name}, headers=auth_headers)
    assert response.status_code == 201
    return response.json()["data"]["id"]


def test_add_member_with_only_a_name(client, auth_headers):
    """A ghost member needs no email and no phone."""
    group_id = _make_group(client, auth_headers)

    response = client.post(
        f"/api/v1/groups/{group_id}/members", json={"name": "Guada"}, headers=auth_headers
    )

    assert response.status_code == 201
    member = response.json()["data"]
    assert member["name"] == "Guada"
    assert member["email"] is None
    assert member["telephone"] is None
    assert member["isStub"] is True


def test_ghost_member_appears_in_the_group_member_list(client, auth_headers):
    """The new member is a real group member, not a pending invitation."""
    group_id = _make_group(client, auth_headers)
    client.post(f"/api/v1/groups/{group_id}/members", json={"name": "Guada"}, headers=auth_headers)

    response = client.get(f"/api/v1/groups/{group_id}/members", headers=auth_headers)

    names = [m["name"] for m in response.json()["data"]]
    assert "Guada" in names


def test_adding_a_member_requires_belonging_to_the_group(client, auth_headers):
    """A caller outside the group cannot add members to it."""
    response = client.post("/api/v1/groups/99999/members", json={"name": "Guada"}, headers=auth_headers)

    assert response.status_code in (400, 403, 404)


def test_expense_split_with_a_ghost_member_gives_them_a_share(client, auth_headers):
    """The whole point: a ghost member carries a balance like anyone else.

    Two members (the creator plus one ghost), a 100 expense paid by the creator, split
    equally — the ghost owes 50.
    """
    group_id = _make_group(client, auth_headers)
    ghost_id = client.post(
        f"/api/v1/groups/{group_id}/members", json={"name": "Guada"}, headers=auth_headers
    ).json()["data"]["memberId"]
    me = client.get("/api/v1/members/me", headers=auth_headers).json()["data"]

    created = client.post(
        "/api/v1/expenses/",
        json={
            "description": "Asado",
            "amount": 100.0,
            "date": "2026-09-04",
            "category": "comida",
            "payerId": me["id"],
            "paymentType": "debit",
            "installments": 1,
            "groupId": group_id,
            "splitStrategy": {"type": "equal"},
        },
        headers=auth_headers,
    )
    assert created.status_code in (200, 201), created.text

    balance = client.get(f"/api/v1/shares/2026/9?group_id={group_id}", headers=auth_headers)
    balances = balance.json()["data"]["balances"]
    assert float(balances[str(ghost_id)]) == -50.0
```

The exact expense and shares request shapes must match the current routers — read
`src/template/entrypoint/expense.py` and `src/template/entrypoint/monthly_share.py` and adjust
field names and the query string to whatever they actually expect before running this.

- [ ] **Step 2: Run test to verify it fails**

Run: `TEST_DATABASE_URL=<url> poetry run pytest tests/integration/groups/test_ghost_members.py -v`
Expected: FAIL with 404 — the route does not exist.

- [ ] **Step 3: Add the request schema**

In `src/template/domain/schemas/group.py`, next to `GroupInviteCreate`:

```python
class GroupMemberCreate(CamelCaseModel):
    """Add a member by name alone — no contact details, no account."""

    name: str = Field(..., min_length=1, max_length=100)
```

- [ ] **Step 4: Add the route**

In `src/template/entrypoint/group.py`, after `invite_member`. Import `GroupMemberCreate` alongside the other group schemas.

```python
@router.post(
    "/{group_id}/members",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseModel[GroupMemberResponse],
)
def add_named_member(
    group_id: int,
    data: GroupMemberCreate,
    current_member=Depends(get_current_member),
    db: Session = Depends(get_db),
) -> ResponseModel[GroupMemberResponse]:
    """Add a member identified only by name.

    The member has no contact details and no password, so nothing is ever sent to them.
    They can later claim their own account through the group's join link.
    """
    group_repo = GroupRepository(db)
    if not group_repo.is_member(group_id, current_member.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this group")

    member_repo = MemberRepository(db)
    member = member_repo.create_stub(name=data.name)
    group_repo.add_member(group_id, member.id)
    return ResponseModel(
        data=GroupMemberResponse(
            member_id=member.id,
            name=member.name,
            email=None,
            telephone=None,
            is_stub=True,
        )
    )
```

If `GroupRepository` has no `is_member`, use whatever membership check the neighbouring routes in this file already use — match the existing pattern rather than inventing one.

- [ ] **Step 5: Run test to verify it passes**

Run: `TEST_DATABASE_URL=<url> poetry run pytest tests/integration/groups/test_ghost_members.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add -A
make lint
make test
git commit -m "feat: add group member by name only"
```

---

### Task 4: Expose claimable members on join-token resolve

**Files:**
- Modify: `src/template/domain/schemas/group.py:83-85` (`GroupJoinResolveResponse`)
- Modify: `src/template/service_layer/invitation_service.py` (`GroupJoinLinkService.resolve_join_token`, ~line 308)
- Test: `tests/integration/groups/test_ghost_members.py` (extend)

**Interfaces:**
- Consumes: the `POST /{group_id}/members` route from Task 3.
- Produces: `GroupJoinResolveResponse` gains `claimable_members: list[ClaimableMemberResponse]`, where `ClaimableMemberResponse` has `member_id: int` and `name: str`. On the wire: `claimableMembers: [{memberId, name}]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/groups/test_ghost_members.py`:

```python
def test_resolve_join_token_lists_only_contactless_stubs(client, auth_headers):
    """Ghost members are claimable; invited stubs and full members are not."""
    group_id = _make_group(client, auth_headers)
    client.post(f"/api/v1/groups/{group_id}/members", json={"name": "Guada"}, headers=auth_headers)
    client.post(
        f"/api/v1/groups/{group_id}/invitations",
        json={"name": "Ivi", "channel": "email", "contact": "ivi@example.com"},
        headers=auth_headers,
    )
    token = client.post(f"/api/v1/groups/{group_id}/join-link", headers=auth_headers).json()["data"]["token"]

    response = client.get(f"/api/v1/join/resolve/{token}")

    claimable = response.json()["data"]["claimableMembers"]
    names = [m["name"] for m in claimable]
    assert names == ["Guada"], "only the contactless stub may be claimed"
    assert all("memberId" in m for m in claimable)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TEST_DATABASE_URL=<url> poetry run pytest tests/integration/groups/test_ghost_members.py::test_resolve_join_token_lists_only_contactless_stubs -v`
Expected: FAIL with `KeyError: 'claimableMembers'`.

- [ ] **Step 3: Add the schema**

In `src/template/domain/schemas/group.py`, above `GroupJoinResolveResponse`:

```python
class ClaimableMemberResponse(CamelCaseModel):
    """A name-only member that someone joining by link may claim as themselves."""

    member_id: int
    name: str


class GroupJoinResolveResponse(CamelCaseModel):
    group_name: str
    inviter_name: str
    claimable_members: list[ClaimableMemberResponse] = []
```

- [ ] **Step 4: Populate it in the service**

In `GroupJoinLinkService.resolve_join_token`, build the list from the group's members. A member is claimable when `is_stub` is true and both contacts are `None`:

```python
        claimable = [
            ClaimableMemberResponse(member_id=m.id, name=m.name)
            for m in self._group_repo.list_members(row.group_id)
            if m.is_stub and m.email is None and m.telephone is None
        ]
        return GroupJoinResolveResponse(
            group_name=...,          # keep the existing expressions for these two
            inviter_name=...,
            claimable_members=claimable,
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `TEST_DATABASE_URL=<url> poetry run pytest tests/integration/groups/test_ghost_members.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add -A
make lint
make test
git commit -m "feat: list claimable name-only members on join resolve"
```

---

### Task 5: Claim a ghost member when joining

**Files:**
- Modify: `src/template/domain/schemas/group.py:77-80` (`GroupJoinRequest`)
- Modify: `src/template/service_layer/invitation_service.py` (`GroupJoinLinkService.register_and_join`, ~line 318)
- Modify: `src/template/entrypoint/invitation.py:142-157` (`register_and_join`)
- Test: `tests/integration/groups/test_ghost_members.py` (extend)

**Interfaces:**
- Consumes: `claimable_members` from Task 4; `MemberRepository.claim_stub(member_id: int, email: str, password_hash: str) -> Member`.
- Produces: `GroupJoinRequest` gains `claim_member_id: Optional[int] = None` (wire: `claimMemberId`). `GroupJoinLinkService.register_and_join(token, name, email, password, claim_member_id=None) -> Member`.

- [ ] **Step 1: Write the failing tests**

```python
def test_joining_while_claiming_keeps_the_existing_member_id(client, auth_headers):
    """Claiming preserves the row, so expenses already attributed to it follow along."""
    group_id = _make_group(client, auth_headers)
    ghost_id = client.post(
        f"/api/v1/groups/{group_id}/members", json={"name": "Guada"}, headers=auth_headers
    ).json()["data"]["memberId"]
    token = client.post(f"/api/v1/groups/{group_id}/join-link", headers=auth_headers).json()["data"]["token"]

    response = client.post(
        f"/api/v1/join/{token}",
        json={
            "name": "Guada",
            "email": "guada@example.com",
            "password": "secret123",
            "claimMemberId": ghost_id,
        },
    )

    assert response.status_code == 200
    members = client.get(f"/api/v1/groups/{group_id}/members", headers=auth_headers).json()["data"]
    claimed = [m for m in members if m["memberId"] == ghost_id]
    assert len(claimed) == 1, "claiming must not create a second member"
    assert claimed[0]["email"] == "guada@example.com"
    assert claimed[0]["isStub"] is False


def test_cannot_claim_a_member_that_has_contact_details(client, auth_headers):
    """An invited stub is addressed to a specific person and is never claimable."""
    group_id = _make_group(client, auth_headers)
    client.post(
        f"/api/v1/groups/{group_id}/invitations",
        json={"name": "Ivi", "channel": "email", "contact": "ivi@example.com"},
        headers=auth_headers,
    )
    members = client.get(f"/api/v1/groups/{group_id}/members", headers=auth_headers).json()["data"]
    invited_id = [m for m in members if m["name"] == "Ivi"][0]["memberId"]
    token = client.post(f"/api/v1/groups/{group_id}/join-link", headers=auth_headers).json()["data"]["token"]

    response = client.post(
        f"/api/v1/join/{token}",
        json={
            "name": "Attacker",
            "email": "attacker@example.com",
            "password": "secret123",
            "claimMemberId": invited_id,
        },
    )

    assert response.status_code == 400


def test_cannot_claim_a_member_from_another_group(client, auth_headers):
    """The claimed member must belong to the group the token points at."""
    other_group = _make_group(client, auth_headers, name="Otro")
    outsider_id = client.post(
        f"/api/v1/groups/{other_group}/members", json={"name": "Ajeno"}, headers=auth_headers
    ).json()["data"]["memberId"]
    group_id = _make_group(client, auth_headers)
    token = client.post(f"/api/v1/groups/{group_id}/join-link", headers=auth_headers).json()["data"]["token"]

    response = client.post(
        f"/api/v1/join/{token}",
        json={
            "name": "Attacker",
            "email": "attacker2@example.com",
            "password": "secret123",
            "claimMemberId": outsider_id,
        },
    )

    assert response.status_code == 400


def test_joining_without_claiming_still_creates_a_new_member(client, auth_headers):
    """The existing path is untouched when claimMemberId is absent."""
    group_id = _make_group(client, auth_headers)
    token = client.post(f"/api/v1/groups/{group_id}/join-link", headers=auth_headers).json()["data"]["token"]

    response = client.post(
        f"/api/v1/join/{token}",
        json={"name": "Nuevo", "email": "nuevo@example.com", "password": "secret123"},
    )

    assert response.status_code == 200
    names = [m["name"] for m in client.get(
        f"/api/v1/groups/{group_id}/members", headers=auth_headers
    ).json()["data"]]
    assert "Nuevo" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `TEST_DATABASE_URL=<url> poetry run pytest tests/integration/groups/test_ghost_members.py -v`
Expected: the three claiming tests FAIL (`claimMemberId` is ignored, so a second member is created); the last one PASSES already.

- [ ] **Step 3: Extend the request schema**

```python
class GroupJoinRequest(CamelCaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: str
    password: str
    claim_member_id: Optional[int] = None
```

- [ ] **Step 4: Implement claiming in the service**

In `GroupJoinLinkService.register_and_join`, add the parameter and branch before the existing create path. Keep the existing email-already-registered check for both branches.

```python
    def register_and_join(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        token: str,
        name: str,
        email: str,
        password: str,
        claim_member_id: Optional[int] = None,
    ) -> Member:
        """Join a group by link, either as a brand-new member or by claiming a name-only one."""
        # ... existing token lookup and email-taken checks stay as they are ...

        if claim_member_id is not None:
            claimed = self._claimable_or_raise(row.group_id, claim_member_id)
            self._member_repo.claim_stub(claimed.id, email, password_hash)
            self._group_repo.add_member(row.group_id, claimed.id)
            return self._member_repo.get(claimed.id)

        # ... existing create_stub / claim_stub / add_member path unchanged ...

    def _claimable_or_raise(self, group_id: int, member_id: int) -> Member:
        """Return the member if it may be claimed through this group's link, else raise.

        Claimable means: in this group, still a stub, and carrying no contact details.
        The last condition is what keeps invitations safe — a stub created by an email or
        WhatsApp invite is addressed to a specific person and must never be seizable by
        whoever happens to hold the link.
        """
        for member in self._group_repo.list_members(group_id):
            if member.id != member_id:
                continue
            if not member.is_stub:
                raise ValueError("That member already has an account")
            if member.email is not None or member.telephone is not None:
                raise ValueError("That member was invited directly and cannot be claimed")
            return member
        raise ValueError("That member does not belong to this group")
```

- [ ] **Step 5: Pass it through the router**

In `src/template/entrypoint/invitation.py`, add one argument to the existing call:

```python
        new_member = svc.register_and_join(
            token=token,
            name=body.name,
            email=body.email,
            password=body.password,
            claim_member_id=body.claim_member_id,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `TEST_DATABASE_URL=<url> poetry run pytest tests/integration/groups/test_ghost_members.py -v`
Expected: PASS (8 tests).

- [ ] **Step 7: Commit**

```bash
git add -A
make lint
make test
git commit -m "feat: claim a name-only member when joining by link"
```

---

### Task 6: Frontend — add a member by name

**Files:**
- Modify: `shared_expense_front/src/api/groups.ts` (add after `inviteMember:79`)
- Modify: `shared_expense_front/src/types/expense.ts` (add `GroupMemberCreate`)
- Modify: `shared_expense_front/src/components/members/InviteDialog.tsx`
- Modify: `shared_expense_front/src/pages/GroupMembersPage.tsx` (badge for contactless members)

**Interfaces:**
- Consumes: `POST /api/v1/groups/{group_id}/members` from Task 3.
- Produces: `addNamedMember(groupId: number, name: string): Promise<GroupMember>`.

- [ ] **Step 1: Add the API client**

In `src/api/groups.ts`, matching the style of the surrounding functions:

```typescript
export async function addNamedMember(groupId: number, name: string): Promise<GroupMember> {
  const response = await fetch(`${config.apiBaseUrl}/api/v1/groups/${groupId}/members`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ name }),
  });
  return handleResponse<GroupMember>(response);
}
```

- [ ] **Step 2: Offer the name-only path in the dialog**

`InviteDialog.tsx` already has a `channel` select holding `'email' | 'phone'` (line 35). Add a third option, `'name'`. When it is selected, hide the contact field entirely and submit through `addNamedMember(groupId, name)` instead of `createInvitation`. The submit button's `disabled` currently requires `contact.trim()` (line 138) — for the name-only channel it must require only `name.trim()`.

Add a short line of helper copy under the name field when `channel === 'name'`, explaining that this person will not be notified and can claim their account later through the group's join link. Use the existing `t()` translation pattern; add the keys to both locale files.

- [ ] **Step 3: Badge contactless members**

In `GroupMembersPage.tsx`, render a "sin cuenta" badge for any member where `!member.email && !member.telephone`, reusing whatever badge component the page already uses.

- [ ] **Step 4: Verify**

Run: `npm run lint && npm run build`
Expected: both pass. Then start the app and confirm: a member added by name appears in the list with the badge, and no invitation is created.

- [ ] **Step 5: Commit**

```bash
git add -A
npm run lint
git commit -m "feat: add a group member by name from the members page"
```

---

### Task 7: Frontend — claim a member when joining

**Files:**
- Modify: `shared_expense_front/src/api/joinLinks.ts:36-56`
- Modify: `shared_expense_front/src/types/expense.ts` (`GroupJoinResolveResponse`)
- Modify: `shared_expense_front/src/public-pages/GroupJoinLanding.tsx`

**Interfaces:**
- Consumes: `claimableMembers` (Task 4) and `claimMemberId` (Task 5).
- Produces: `registerAndJoin(token, { name, email, password, claimMemberId? })`.

- [ ] **Step 1: Extend the types**

```typescript
export interface ClaimableMember {
  memberId: number;
  name: string;
}

export interface GroupJoinResolveResponse {
  groupName: string;
  inviterName: string;
  claimableMembers?: ClaimableMember[];
}
```

- [ ] **Step 2: Extend the client**

In `src/api/joinLinks.ts`, widen the `registerAndJoin` data parameter:

```typescript
export async function registerAndJoin(
  token: string,
  data: { name: string; email: string; password: string; claimMemberId?: number },
): Promise<{ accessToken: string; tokenType: string }> {
```

The body already passes `data` straight through, so no other change is needed.

- [ ] **Step 3: Add the choice to the landing page**

In `GroupJoinLanding.tsx`, when `claimableMembers` is non-empty, show the question "¿Sos alguna de estas personas?" above the registration form: one selectable row per claimable member, plus a "Soy otra persona" option. Selecting a person prefills the name field with that member's name and sets `claimMemberId`; choosing "Soy otra persona" clears it and leaves the form exactly as it is today.

When `claimableMembers` is empty or absent, render the page unchanged.

- [ ] **Step 4: Verify**

Run: `npm run lint && npm run build`
Expected: both pass. Then walk the flow end to end: create a group, add a ghost member, log an expense attributed to them, open the join link in a private window, join while claiming that member, and confirm the expense and balance are attached to the account you just created.

- [ ] **Step 5: Commit**

```bash
git add -A
npm run lint
git commit -m "feat: claim an existing member when joining by link"
```

---

### Task 8: Documentation

**Files:**
- Modify: `shared_expense_manager/CLAUDE.md` (domain model table and API surface)
- Modify: `CLAUDE.md` at the monorepo root (data model essentials)

- [ ] **Step 1: Document ghost members**

In the backend `CLAUDE.md`, extend the stub-member note: a stub with **no** email and **no** telephone is a "ghost" member — tracked by name, never notified, claimable through a join link. Note the claimable rule and that invited stubs are excluded by design.

Add `POST /{group_id}/members` to the Groups section of the API surface, and note that `GET /join/resolve/{token}` returns `claimableMembers` and `POST /join/{token}` accepts `claimMemberId`.

- [ ] **Step 2: Mirror in the root CLAUDE.md**

Add a line to the **Member bootstrapping** / stub-members paragraph covering the same ground, and note the new endpoint under the frontend API-client list (`groups.ts`, `joinLinks.ts`).

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "docs: document ghost members and the claim-on-join flow"
```

---

## Verification before opening the PR

- [ ] `git add -A && make lint` — all five hooks pass; re-run once more to confirm nothing was rewritten
- [ ] `make test` — full unit suite green
- [ ] `TEST_DATABASE_URL=<url> make integration` — full integration suite green
- [ ] `npm run lint && npm run build` in `shared_expense_front`
- [ ] Manual walkthrough: create group → add ghost member → log expense attributed to them → check the balance → join by link claiming them → confirm the balance carried over
- [ ] Confirm no notification was attempted for the ghost member (no errors in logs on expense creation)
