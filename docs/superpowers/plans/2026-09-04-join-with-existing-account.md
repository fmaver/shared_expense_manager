# Join With an Existing Account Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let someone with an existing account join a group from a join link, and claim a ghost member as themselves by absorbing that ghost's history into their account.

**Architecture:** No schema change. `POST /join/{token}` gains optional auth via `_get_optional_member` (mirroring `accept_invitation`). Claiming as an existing account becomes a `MemberMergeService` that repoints every reference to the ghost — FK columns plus member-id keys inside `split_strategy` and `balances` JSON — inside one transaction, then deletes the ghost.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2 (`CamelCaseModel`), pytest; React 18 + TypeScript + Vite.

**Spec:** `docs/superpowers/specs/2026-09-04-join-with-existing-account-design.md`

## Global Constraints

- Backend imports are `from template.xxx import ...`; responses wrapped in `ResponseModel[T]`; schemas extend `CamelCaseModel` (camelCase wire).
- Money is `float`. **A merge must not change any amount** — only which member an amount belongs to.
- `git fetch origin --prune` before branching and before reporting branch state.
- `git add -A` **before** `make lint` — `pre-commit --all-files` skips untracked files. Re-run lint after any hook rewrites files.
- `make integration` cannot run locally (no Docker/Postgres) and must never point at staging (`clean_tables` truncates). Drive logic with in-memory SQLite unit tests, per `tests/unit/adapters/test_income_currency_update.py`. Integration tests are written and confirmed collected, then **verified in CI** — never claimed to pass locally.
- `@pytest.mark.asyncio` silently SKIPS tests here (no pytest-asyncio). Use `asyncio.run()` in a sync test.
- A merge target must be a ghost: stub, `email IS NULL`, `telephone IS NULL`. Re-validate server-side.

---

### Task 1: MemberMergeService — the merge itself

**Files:**
- Create: `src/template/service_layer/member_merge_service.py`
- Test: `tests/unit/service/test_member_merge.py`

**Interfaces:**
- Produces: `MemberMergeService(session).merge(ghost_id: int, survivor_id: int, group_id: int) -> None`, raising `ValueError` when the ghost is not mergeable.

- [ ] **Step 1: Write the failing tests**

Build a group with a survivor (full account) and a ghost, expenses using both, and assert the rewrite. Use the SQLite session fixture pattern from `tests/unit/service/test_ghost_member_claiming.py`.

```python
def test_merge_repoints_expense_payer(populated_session):
    """An expense the ghost paid becomes an expense the survivor paid."""
    # ghost pays 100, equal split
    ...
    MemberMergeService(populated_session).merge(GHOST_ID, SURVIVOR_ID, GROUP_ID)
    assert expense_row(populated_session).payer_id == SURVIVOR_ID


def test_merge_rewrites_participant_ids(populated_session):
    """EqualSplit participant_ids list entries are remapped."""
    ...
    assert strategy["participant_ids"] == [SURVIVOR_ID]


def test_merge_rewrites_percentage_and_exact_keys(populated_session):
    """percentages/amounts are keyed by member id — the keys move, the values do not."""
    ...
    assert strategy["percentages"] == {str(SURVIVOR_ID): 50.0, str(OTHER_ID): 50.0}


def test_merge_repoints_recurring_group_expense(populated_session):
    """Templates carry their own payer_id and split_strategy."""
    ...


def test_merge_rewrites_balances_in_a_settled_month(populated_session):
    """recalculate_balances returns early when settled, so the keys must be remapped."""
    ...


def test_merge_preserves_the_balance_total(populated_session):
    """The invariant that proves no money moved."""
    before = sum(balances(populated_session).values())
    MemberMergeService(populated_session).merge(GHOST_ID, SURVIVOR_ID, GROUP_ID)
    assert sum(balances(populated_session).values()) == pytest.approx(before)


def test_merge_collapses_duplicate_membership(populated_session):
    """If both rows are in the group, one membership survives, not a constraint violation."""
    ...


@pytest.mark.parametrize("field,value", [("email", "x@example.com"), ("telephone", "5411999"), ("hashed_password", "h")])
def test_merge_rejects_a_non_ghost(populated_session, field, value):
    """Only a contactless stub may be absorbed."""
    with pytest.raises(ValueError):
        MemberMergeService(populated_session).merge(NOT_A_GHOST_ID, SURVIVOR_ID, GROUP_ID)


def test_merge_deletes_the_ghost(populated_session):
    ...
```

- [ ] **Step 2: Run to verify they fail**

Run: `poetry run pytest tests/unit/service/test_member_merge.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the service**

Order matters: validate, assert the ghost owns nothing personal, rewrite, then delete.

```python
class MemberMergeService:
    """Absorb a ghost member into an existing account.

    A merge relabels identity and changes no amounts. That is what makes rewriting even
    settled months correct: the arithmetic is identical, only the owner changes.
    """

    def __init__(self, session: Session):
        self.session = session

    def merge(self, ghost_id: int, survivor_id: int, group_id: int) -> None:
        ghost = self._ghost_or_raise(ghost_id)
        self._assert_owns_nothing_personal(ghost_id)
        self._repoint_expenses(ghost_id, survivor_id, group_id)
        self._repoint_recurring_group_expenses(ghost_id, survivor_id, group_id)
        self._rewrite_balances(ghost_id, survivor_id, group_id)
        self._repoint_invitations(ghost_id, survivor_id)
        self._move_membership(ghost_id, survivor_id, group_id)
        self.session.delete(ghost)
        self.session.commit()
```

`_assert_owns_nothing_personal` raises if the ghost appears in `groups.owner_member_id`,
`recurring_incomes`, `income_instances`, `recurring_personal_expenses`, or
`group_join_links.created_by_member_id` — a ghost cannot, so a hit means this is not a ghost and
the merge must abort rather than half-apply.

`_remap_strategy(strategy: dict, ghost_id, survivor_id) -> dict` is a pure function handling all
three shapes: `participant_ids` list, and the string keys of `percentages` / `amounts`. Merge
values by addition if both ids are present in the same dict (the ghost and survivor both
participating in one expense), so the total is preserved.

- [ ] **Step 4: Run to verify they pass**

Run: `poetry run pytest tests/unit/service/test_member_merge.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && make lint && make test
git commit -m "feat: MemberMergeService absorbs a ghost member into an existing account"
```

---

### Task 2: Optional auth on POST /join/{token}

**Files:**
- Modify: `src/template/domain/schemas/group.py` (`GroupJoinRequest`)
- Modify: `src/template/service_layer/invitation_service.py` (`GroupJoinLinkService.register_and_join`)
- Modify: `src/template/entrypoint/invitation.py` (`register_and_join`, `resolve_join_token`)
- Test: `tests/unit/service/test_member_merge.py` (extend), `tests/integration/groups/test_join_existing_account.py` (create, CI)

**Interfaces:**
- Produces: `register_and_join(token, name=None, email=None, password=None, claim_member_id=None, current_member=None) -> Member`. `GroupJoinRequest.name/email/password` become `Optional`. `GroupJoinResolveResponse` gains `already_member: bool = False`.

- [ ] **Step 1: Write the failing tests**

Cover the four combinations from the spec at service level (SQLite), and the same matrix at router level for CI:

```python
def test_authenticated_join_without_claim_adds_the_caller(populated_session): ...
def test_authenticated_join_with_claim_merges(populated_session): ...
def test_anonymous_join_still_requires_a_password(populated_session): ...
def test_authenticated_join_is_idempotent_when_already_a_member(populated_session): ...
```

- [ ] **Step 2: Run to verify they fail**

Run: `poetry run pytest tests/unit/service/test_member_merge.py -v`
Expected: FAIL — `register_and_join` takes no `current_member`.

- [ ] **Step 3: Implement**

Make the schema fields optional; branch in the service on `current_member`:

```python
if current_member is not None:
    if claim_member_id is not None:
        MemberMergeService(self._session).merge(claim_member_id, current_member.id, row.group_id)
    self._group_repo.add_member(row.group_id, current_member.id)  # idempotent
    return self._member_repo.get(current_member.id)

if not (name and email and password):
    raise ValueError("name, email and password are required when joining without an account")
```

Then wire `current_member: Optional[Any] = Depends(_get_optional_member)` into the router and
pass it through, exactly as `accept_invitation` does. Add `already_member` to the resolve
response, computed only when a JWT is present.

- [ ] **Step 4: Run to verify they pass, then confirm the integration file collects**

Run: `poetry run pytest tests/unit -q` then
`poetry run pytest tests/integration/groups/test_join_existing_account.py --collect-only -q`

- [ ] **Step 5: Commit**

```bash
git add -A && make lint && make test
git commit -m "feat: join by link with an existing account"
```

---

### Task 3: Frontend — login return URL

**Files:**
- Modify: `shared_expense_front/src/pages/LoginPage.tsx`

**Interfaces:**
- Produces: `/login?next=<path>` navigates to `next` on success.

- [ ] **Step 1: Read `LoginPage.tsx`** and find every post-login `navigate(...)` call. It currently has no notion of where the user came from.

- [ ] **Step 2: Add `next` handling**

```tsx
const [searchParams] = useSearchParams();
const next = searchParams.get('next');
// on success:
navigate(next && next.startsWith('/') ? next : '/groups');
```

The `startsWith('/')` check is not decoration — without it, `?next=https://evil.example` turns
the login page into an open redirect.

- [ ] **Step 3: Verify** — `npm run lint && npm run build`, then log in with `?next=/personal` and confirm the destination.

- [ ] **Step 4: Commit**

```bash
git add -A && npm run lint
git commit -m "feat: honour a ?next= return path after login"
```

---

### Task 4: Frontend — the three join states

**Files:**
- Modify: `shared_expense_front/src/api/joinLinks.ts`
- Modify: `shared_expense_front/src/types/expense.ts`
- Modify: `shared_expense_front/src/public-pages/GroupJoinLanding.tsx`

**Interfaces:**
- Consumes: optional auth and `alreadyMember` from Task 2; `?next=` from Task 3.
- Produces: `registerAndJoin` sends the bearer token when present and accepts a body with no `name`/`email`/`password`.

- [ ] **Step 1: Send auth and allow an empty body**

`resolveJoinToken` and `registerAndJoin` currently send no `Authorization` header — add it when
a token exists, following the `authHeaders()` pattern already in this file. Widen the data
parameter so all three credential fields are optional.

- [ ] **Step 2: Branch the page on auth state**

Three states:
- **logged in** → "Join as `<name>`" button, plus the claim picker when ghosts exist; no form
- **logged out** → today's form, plus "I already have an account" linking to
  `/login?next=/join/<token>` — appending `?claim=<memberId>` when a ghost is selected, so the
  choice survives the round trip
- **`alreadyMember`** → a message and a link into the group

On mount, read `?claim=` from the URL and preselect that ghost.

- [ ] **Step 3: Verify** — `npm run lint && npm run build`, then walk it: create a group, add a ghost, log an expense for them, open the link in a second browser logged in as another account, claim the ghost, and confirm the expense and balance moved to that account.

- [ ] **Step 4: Commit**

```bash
git add -A && npm run lint
git commit -m "feat: join a group with an existing account from the join link"
```

---

### Task 5: Documentation

- [ ] Document the merge in `shared_expense_manager/CLAUDE.md` (domain notes + API surface) and the root `CLAUDE.md`: what a merge rewrites, the ghost-only precondition, and why settled months are rewritten rather than skipped.
- [ ] Commit.

---

## Verification before opening the PR

- [ ] `git add -A && make lint` twice — stable, nothing rewritten
- [ ] `make test` green; the balance-total invariant test present and passing
- [ ] Integration tests collected (`--collect-only`), left for CI
- [ ] `npm run lint && npm run build`
- [ ] Manual: ghost with expenses in a **settled** month merged into an existing account — balances unchanged in total, attributed to the survivor
