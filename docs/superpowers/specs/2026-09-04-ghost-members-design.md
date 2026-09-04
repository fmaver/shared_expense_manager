# Ghost members — design

**Date:** 2026-09-04
**Status:** awaiting review
**Scope:** feature 1 of 2. One-time (occasion) groups are a separate spec, to be written after this ships.

## Problem

Adding someone to a group today requires an email or a phone number, because the only way in
is an invitation and an invitation needs somewhere to send itself. That blocks a real use
case: a group run entirely by one person, who logs every expense and attributes it to people
who are not app users and may never be. Those people need to exist as *names* only.

A second, related gap: when someone eventually does join through a share link, they arrive as
a brand-new member. There is no way to say "I am the Guada you have been tracking," so their
history stays attached to a name nobody owns.

## Goals

1. Create a group member from a **name alone** — no email, no phone, no password.
2. Expenses can be attributed to such a member, and balances computed for them, exactly as for
   a full member.
3. Never attempt to notify a member with no contact details.
4. When someone joins **through a share link**, let them claim an existing name-only member
   instead of being created fresh.

## Non-goals

- Changing the email/WhatsApp invitation flow. An invited person already has their identity
  encoded in the invitation, so they are never asked who they are. Explicitly out of scope.
- One-time groups, credit rules, and the single-balance view — separate spec.
- Letting a ghost member log in. They have no password; claiming through a join link is the
  only path to an account.

## Existing machinery this builds on

The codebase is already most of the way there, which keeps this change small:

| Piece | State today |
|---|---|
| `MemberRepository.create_stub(name, email, telephone)` | exists; both contacts already optional in the signature |
| `members.email` / `members.telephone` | already nullable (migration `m9`) |
| `Member.is_stub` | computed as `hashed_password is None` |
| Notification dispatch | every branch already guards on `and member.email` / `and member.telephone` |
| `MemberRepository.claim_stub(member_id, email, password_hash)` | exists; used by the invitation accept flow |

**No migration is required.** The schema already permits a row with a name and nothing else.

## Design

### Creating a ghost member

New endpoint, authenticated, caller must belong to the group:

```
POST /api/v1/groups/{group_id}/members
{ "name": "Guada" }  →  201 { "data": GroupMemberResponse }
```

It calls `create_stub(name=..., email=None, telephone=None)` and adds the member to the group.
`create_stub`'s docstring currently claims "at least one of email or telephone must be
provided" — nothing enforces that, and it stops being true here; the docstring gets corrected.

Rejected: reusing `POST /{group_id}/members/invite`. That endpoint's job is to dispatch an
invitation, and a ghost member is defined by there being nothing to dispatch. Overloading it
would mean a request that looks like an invite but silently sends nothing.

### Claiming a ghost member through a join link

`GET /join/resolve/{token}` gains a `claimableMembers` list:

```json
{ "groupId": 4, "groupName": "Asado", "claimableMembers": [ { "memberId": 12, "name": "Guada" } ] }
```

`POST /join/{token}` gains an optional `claimMemberId`. When present, the service claims that
existing member rather than creating a new one — `claim_stub(member_id, email, password_hash)`
already does exactly this, so the joiner's own email and password land on the existing row and
every expense already attributed to it follows automatically.

### What makes a member claimable

A member is offered for claiming only when **all** of these hold:

- they belong to this group
- `hashed_password IS NULL` (still a stub)
- `email IS NULL` **and** `telephone IS NULL`

That last condition is the load-bearing one. Stubs created by an email or WhatsApp invitation
*do* carry a contact detail, so they are never claimable through a link — otherwise anyone
holding the link could seize an invitation addressed to someone else. This is also why the
invitation flow needs no changes: its stubs are structurally excluded.

The same three conditions are re-validated server-side on `POST /join/{token}`. The resolve
response is a convenience for the UI, never the authority.

### Accepted risk

Within a single group, anyone holding the join link can claim **any** unclaimed name-only
member, including one whose balance is large. Per the decision on 2026-09-04, claiming is free
choice with no notification to the group creator.

The consequence is worth stating plainly: the join link is a bearer token, and forwarding it
to the wrong person lets them take over a name and its balance silently. Rotating the link
(`POST /{group_id}/join-link/rotate`, already implemented) is the mitigation if a link leaks.
Revisit if groups ever grow beyond people who know each other.

### Frontend

- **Members page** — "Add member" offers a name-only path alongside the existing invite-by-
  email/WhatsApp path. Members with no contact details render with a "sin cuenta" badge so it
  is obvious who is not a real user.
- **Join page** — when `claimableMembers` is non-empty, the joiner is asked "¿Sos alguna de
  estas personas?" with the list plus a "Soy otra persona" escape that falls through to the
  existing registration. When the list is empty the page is unchanged.
- `src/api/groups.ts` and `src/api/joinLinks.ts` gain the matching client functions and types.

## Testing

Unit:
- `create_stub` with neither contact produces a member with `is_stub` true
- a contactless member is skipped by every notification branch
- claimable filter excludes: full members, stubs with an email, stubs with a phone, members of
  other groups

Integration:
- create a ghost member, log an expense attributed to them, assert they appear in the group
  balance with the right share
- resolve a join token and assert `claimableMembers` lists exactly the name-only members
- join while claiming: the existing member id is preserved and now has an email and password
- join claiming a member that carries an email → rejected
- join claiming a member from another group → rejected

## Open questions

None outstanding. The four design decisions (single-balance depth, claim safety, credit rules,
sequencing) were settled before this spec was written; only claim safety and sequencing bear on
this document.
