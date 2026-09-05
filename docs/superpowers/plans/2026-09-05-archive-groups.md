# Archiving Groups Implementation Plan

**Goal:** Let each member archive a group for themselves once they owe nothing, find it again under "Archivados", and have it come back automatically if their balance stops being zero.

**Architecture:** `group_memberships.archived_at` — archiving is a property of the membership, not the group, so two people can see the same group differently. Migration `m15`. No change to `GroupStatus`.

**Spec:** `docs/superpowers/specs/2026-09-05-archive-groups-design.md`

## Global Constraints

- Backend imports `from template.xxx import ...`; responses wrapped in `ResponseModel[T]`; schemas are `CamelCaseModel` (camelCase wire).
- **Verify with explicit exit codes.** `make lint >/dev/null; echo $?` — a chained `&& echo PASS` silently prints nothing on failure, which is how a lint failure reached CI on 2026-09-05. Run lint **twice**: a hook that rewrites files fails the first pass.
- `git add -A` before `make lint` — pre-commit skips untracked files.
- Frontend: type-check with **`npx tsc -b`**. `vite build` does not check types and `tsc --noEmit` checks nothing here. CI runs `npm run typecheck:ratchet`.
- `make integration` cannot run locally and must never point at staging. Drive logic with in-memory SQLite unit tests; integration tests are written, confirmed collected, and **verified in CI** — never claimed to pass locally.
- Migration `m15_archive_group_memberships`, `down_revision = "m14_add_currency"`. Update the chain line in **both** CLAUDE.md files. Run against staging Neon before merge.

---

### Task 1 — Column and migration

- `archived_at: Mapped[datetime | None]` on `GroupMembershipModel`, nullable, no default.
- `migrations/versions/m15_archive_group_memberships.py` using `ADD COLUMN IF NOT EXISTS`, matching how `m14` guards against `create_all` having already made it.
- Unit test: an existing membership reads `archived_at is None`.

### Task 2 — Repository

- `archive(group_id, member_id)` / `unarchive(group_id, member_id)` set and clear the timestamp.
- `list_for_member(member_id, include_personal=False, archived=False)` filters on the membership join. Default `archived=False` preserves today's behaviour for every existing caller.
- Unit tests: archiving hides it from the default list and shows it in the archived list; **another member's view is unchanged** — the property the whole design rests on.

### Task 3 — Service rules

- `outstanding_balance(group_id, member_id, expense_repo) -> float` extracted from `leave_group` (`entrypoint/group.py:296`) so archive and leave share one rule instead of copying it.
- `GroupService.archive(...)` rejects a non-zero balance and rejects personal groups.
- Unit tests: zero balance succeeds; outstanding rejected; personal rejected; settled months excluded from the check.

### Task 4 — Auto-unarchive

- `refresh_archived_state(group_id)`: for each archived membership, unarchive when that member's balance is no longer zero.
- Called after an expense is created, updated or deleted — the only moments a balance changes.
- Unit tests: an expense involving an archived member clears `archived_at`; one that does not involve them leaves it set.

### Task 5 — Notifications

- Group-wide notifications (monthly balance, settlement) skip archived members.
- `notify_expense_created` needs no change: it already skips members not involved, so an archived member who *is* involved is still notified — which is the intended behaviour.
- Unit test pinning both halves.

### Task 6 — Endpoints

- `POST /groups/{id}/archive`, `POST /groups/{id}/unarchive`, `GET /groups/?archived=true`.
- Integration tests for the matrix, verified in CI.

### Task 7 — Frontend

- `archiveGroup` / `unarchiveGroup` / `getMyGroups({archived})` in `src/api/groups.ts`.
- Groups page: "Archivados" entry point; main list unchanged.
- Archived view with an Unarchive action.
- Group settings: "Archivar", disabled with the reason when the balance is not zero, mirroring leave.

### Task 8 — Docs

- Both `CLAUDE.md` files: the new endpoints, the per-member semantics, the auto-unarchive rule, and the migration chain now ending at `m15`.

## Verification before the PR

- [ ] `git add -A && make lint`, exit code checked, run twice
- [ ] `make test` green
- [ ] Integration tests collected
- [ ] `npx tsc -b` shows no new errors; `npm run lint`, `npm run build`
- [ ] Migration applied against staging Neon
- [ ] Manual: two accounts, one archives, the other still sees the group; an expense involving the archiver brings it back
