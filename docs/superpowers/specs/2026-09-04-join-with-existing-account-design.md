# Join with an existing account (and merge a ghost member) — design

**Date:** 2026-09-04
**Status:** awaiting review
**Follows:** `2026-09-04-ghost-members-design.md`

## Problem

The join-link flow can only create a brand-new account. Both options on the landing page —
"pick your name" and "I'm someone else" — end in a registration form. Someone who already has
an account cannot use a join link at all, and in particular cannot say "that ghost member you
have been tracking is me."

The invitation flow already solved half of this: `accept_invitation` takes
`_get_optional_member`, so a logged-in user joins with their JWT and no password. The join-link
flow never got the same treatment.

## Goals

1. A logged-in user can join a group from a join link, with no password prompt.
2. A logged-out user with an account is sent to log in and returned to the join link.
3. Either can claim a ghost member **as** their existing account, taking over its history.

## Non-goals

- Merging two *full* accounts. Only a ghost (stub, no email, no telephone) can be absorbed.
- Changing the invitation flow, which already handles logged-in users.
- Any schema change. This needs no migration.

## The hard part: claiming is a merge, not a claim

`claim_stub` writes an email and password onto the ghost's row. That works when the joiner has
no row of their own. Here they do — so the ghost must be **absorbed into** the existing member,
not upgraded.

**A merge changes no amounts.** It only relabels who an amount belongs to. That single property
is what makes the rest of this design safe, including rewriting settled months.

### Every place a ghost's id can appear

Enumerated from `adapters/orm.py`, not assumed:

| Location | Kind | Action |
|---|---|---|
| `group_memberships.member_id` | FK | repoint to the survivor; drop if that would duplicate an existing membership |
| `expenses.payer_id` | FK | repoint |
| `expenses.split_strategy` | JSON | rewrite `participant_ids` entries, and the **keys** of `percentages` / `amounts` |
| `recurring_group_expenses.payer_id` | FK | repoint — easy to miss; templates carry their own payer |
| `recurring_group_expenses.split_strategy` | JSON | same rewrite as above |
| `monthly_shares.balances` | JSON | rewrite keys (see settled months below) |
| `invitations.invitee_member_id`, `accepted_by_member_id` | FK | repoint if set; a ghost has no contact so normally none exist |
| `groups.owner_member_id` | FK | a ghost never owns a personal group — **assert none**, do not silently skip |
| `recurring_incomes` / `income_instances` / `recurring_personal_expenses`.`owner_member_id` | FK | personal-group only, so a ghost has none — **assert none** |
| `group_join_links.created_by_member_id` | FK | a ghost cannot create a link — **assert none** |

The three assertions matter: if any of them ever fires, the row being merged is not a ghost and
the merge must abort rather than half-apply.

### Settled months

`MonthlyShare.recalculate_balances` returns early when `is_settled`, so a settled month's
`balances` JSON will never self-heal. Skipping settled months would therefore leave balances
keyed to a member id that no longer exists — the genuinely broken outcome.

So settled months are rewritten too: the `balances` keys are remapped in place. Because a merge
changes no amounts, a settled month stays arithmetically identical — same numbers, attributed to
the surviving account. Unsettled months are recalculated afterwards as a consistency check;
their result should be identical to the remap.

### Transactional

The whole merge runs in one transaction. A half-merged member — expenses repointed but the
membership row still on the ghost, or the ghost deleted while a JSON blob still names it — is
worse than a failed merge.

## API

`POST /join/{token}` gains optional authentication via `_get_optional_member`, mirroring
`accept_invitation`:

| Caller | `claimMemberId` | Behaviour |
|---|---|---|
| anonymous | absent | register + join (today's behaviour, unchanged) |
| anonymous | present | claim the ghost via `claim_stub` (today's behaviour, unchanged) |
| authenticated | absent | add the caller to the group; no password needed |
| authenticated | present | **merge** the ghost into the caller, then ensure membership |

`name`, `email` and `password` become optional in `GroupJoinRequest`, since an authenticated
caller supplies none of them. They stay required for the anonymous paths, validated in the
service rather than the schema so the error message can say which path is missing what.

`GET /join/resolve/{token}` also gains `alreadyMember: bool` when called with a JWT, so the page
can say "you're already in this group" instead of offering a join that would no-op.

## Frontend

**`GroupJoinLanding`** grows three states instead of one:

- **Logged in** — shows "Join as `<name>`", plus the claim picker if ghosts exist. One tap. No
  registration form.
- **Logged out** — today's registration form, plus a new "I already have an account" link.
- **Already a member** — a message and a link into the group.

**`/login` needs a return URL, which it does not have today.** `LoginPage` uses `useNavigate`
with no notion of where the user came from. It gains a `?next=` parameter: the join page links
to `/login?next=/join/<token>`, and on success the page navigates to `next` when present,
falling back to its current destination. The claim selection is preserved by encoding it in the
return path (`/join/<token>?claim=<memberId>`) rather than in local state, which would not
survive the round trip.

## Testing

SQLite unit tests (the local RED-GREEN cycle) for the merge, since it is the risky part:

- ids repointed across `expenses.payer_id` and `recurring_group_expenses.payer_id`
- `participant_ids` rewritten; `percentages` and `amounts` keys rewritten, values untouched
- `balances` keys rewritten in a **settled** month, amounts unchanged
- duplicate membership collapses to one row rather than violating the unique constraint
- merging a member with an email, a telephone, or a password is **rejected**
- the sum of all balances is unchanged by the merge — the invariant that proves no money moved

Integration tests (CI) for the endpoint matrix: each of the four caller/`claimMemberId`
combinations above, plus a rejected merge, plus `alreadyMember`.

## Accepted risk

Unchanged from the ghost-members spec: whoever holds the join link can claim any unclaimed
ghost. Merging raises the stakes, since a wrong claim now absorbs history into a real account
and is not reversible from the UI. Link rotation remains the mitigation. Revisit if this bites.
