# Archiving groups — design

**Date:** 2026-09-05
**Status:** awaiting review

## Problem

A group that is finished still sits in the groups list forever. Deleting it is wrong — the
history matters — so people need a way to put it away and get it back.

## Decisions (settled with the user)

| Question | Choice |
|---|---|
| Scope | **Per member.** You archive it for yourself; everyone else keeps using the group unchanged |
| Notifications | Silent for what does not concern you; still notified when something changes **your** balance |
| Auto-unarchive | Yes — a group comes back when your balance stops being zero |
| Precondition | Balance must be zero, same rule as leaving |

Per-member is the decision everything else follows from. It also avoids duplicating something
that already exists: `GroupStatus.CLOSED` is a group-wide "close", is already implemented, and
is **not wired into the UI at all** — a group-wide archive would be that feature again under a
new name.

## Data

One nullable column, `group_memberships.archived_at`. Archiving is a property of the
*membership*, not the group, which is exactly what lets two people see the same group
differently.

Migration `m15_archive_group_memberships`, `down_revision = m14_add_currency`. The chain line
in both `CLAUDE.md` files must be updated. Nullable with no default, so existing rows are
untouched and every current membership reads as not archived.

## Rules

**Archiving requires a zero balance.** Reuses the rule `leave_group` already applies
(`entrypoint/group.py:296`): the largest absolute balance across all **unsettled** months must
be under 0.01. Settled months are excluded because they are already resolved. That logic moves
into a helper both endpoints call, rather than being copied.

**Auto-unarchive** happens when a member's balance in the group becomes non-zero. It runs after
an expense is created, updated or deleted — the only moments a balance can change — and clears
`archived_at` for any archived member whose balance is no longer zero. A member the expense does
not involve stays archived.

This is what makes silence safe: you cannot accumulate debt behind an archived group, because
acquiring debt is precisely what brings it back.

**Notifications.** `notify_expense_created` already skips members not involved in an expense
(`_is_involved_in_expense`), so an archived member who *is* involved is notified — the desired
behaviour, for free. The group-wide notifications (monthly balance, settlement) must skip
archived members, since those are the noise archiving exists to stop.

## API

| Method | Path | Notes |
|---|---|---|
| `POST` | `/groups/{group_id}/archive` | 400 with a clear message when the balance is not zero |
| `POST` | `/groups/{group_id}/unarchive` | always allowed |
| `GET` | `/groups/?archived=true` | archived groups for the current member; default `false` keeps today's response |

`list_for_member` currently filters `GroupModel.status == "active"`; it gains an
`archived` filter on the membership join. Personal groups can never be archived — they are the
member's own ledger — and that is asserted, not assumed.

## Frontend

- Groups page: an "Archivados" entry point; the main list excludes them.
- Archived view: each group with an **Unarchive** action, and a badge when it has a non-zero
  balance (which should not happen given auto-unarchive, so it is a visible inconsistency rather
  than a silent one).
- Group settings: an "Archivar" action, disabled with an explanation when the balance is not
  zero — mirroring how leaving already behaves.

## Testing

SQLite unit tests, where the local RED-GREEN cycle lives:
- archiving with a zero balance succeeds; with an outstanding balance is rejected
- an archived membership disappears from `list_for_member` and appears in the archived list
- **another member is unaffected** — the core property of per-member archiving
- an expense that changes an archived member's balance clears `archived_at`
- an expense that does not involve them leaves it set
- a personal group cannot be archived

Integration tests for the endpoint shapes, verified in CI.

## Out of scope

- Archiving on behalf of someone else.
- Bulk archive.
- Any change to `GroupStatus`; `CLOSED`/`DELETED` are left exactly as they are.
