# One-time (occasion) groups — design and plan

**Date:** 2026-09-04
**Status:** approved, in progress

Spec and plan combined in one document: the decisions were settled in conversation before
writing, and the task list is short enough that splitting them would add ceremony without
adding clarity.

## Problem

Every group today is an ongoing arrangement: expenses live in a monthly share, balances are
per-month, and settlement closes a month. That is right for a shared household, and wrong for a
trip or a dinner — occasions that have no notion of "this month", and where credit installments
would scatter a single evening's spending across future months.

## Decisions (settled with the user)

| Decision | Choice |
|---|---|
| Depth | Keep monthly shares **internally**; the API and UI present **one** balance across all months, with a single settle |
| Credit | **Blocked** in one-time groups, enforced server-side |
| Type mutability | **Immutable** after creation |
| Scope | Everything in one piece of work, not split |

Keeping monthly shares internally is what avoids schema surgery: `expenses.monthly_share_id`
stays non-nullable and all the balance and transfer math is reused unchanged.

`groups.group_type` is `String(20)` (`adapters/orm.py:57`), not a native Postgres enum, so
adding a value needs **no migration**.

## Design

### Backend

1. `GroupType.ONE_TIME = "one_time"` in `domain/models/group.py`.
2. `GroupCreate` gains `group_type: Literal["regular", "one_time"] = "regular"`. `personal` is
   deliberately not accepted — personal groups are created only by
   `get_or_create_personal_group`, and letting the API mint one would produce a second personal
   group for a member.
3. `GroupService.create(name, creator_member_id, group_type=REGULAR)` passes it through to
   `GroupRepository.create`, which already accepts a `group_type`.
4. **Credit is rejected** for one-time groups in `ExpenseService`, where every create and update
   path converges — not in the router, and not only in the form. A hidden UI control is not a
   rule.
5. **Aggregate endpoints** on the shares router, declared **before** `/{year}/{month}`: the
   existing `/trend` route sits there for exactly this reason, and a `/all` declared after a
   two-segment path is still fine, but keeping the literal routes together makes the constraint
   visible.
   - `GET /shares/all/{group_id}` → `AggregateBalanceResponse`: every expense in the group
     across all months, one merged `balances` map, computed `transfers`, and `is_settled` true
     only when **every** month with expenses is settled.
   - `POST /shares/settle-all/{group_id}` → settles every unsettled month that has expenses,
     then returns the same aggregate shape.

   Balances merge by summing per member across months. This is sound because balances are
   already stored in ARS (USD converted at recalculation), so no currency conversion happens at
   aggregation time.

### Frontend

6. `CreateGroupDialog` becomes a two-step flow: choose the type — each with a one-line
   explanation of what it does — then name it.
7. Group cards on `GroupSelectorPage` carry a badge for one-time groups; `DynamicIsland` shows
   the same label inside the group.
8. The group dashboard hides `MonthPicker` for a one-time group and reads the aggregate endpoint
   instead of the monthly one; "Settle up" calls settle-all.
9. `AddExpenseDialog` hides the credit option for one-time groups, mirroring the server rule.

## Testing

SQLite unit tests, which is where the local RED-GREEN cycle lives:

- creating a group with each type; `personal` rejected through the API schema
- a credit expense in a one-time group is rejected; the same expense in a regular group succeeds
- aggregate balances sum per member across two months
- `is_settled` is false when any month with expenses is unsettled
- settle-all leaves every month settled and the aggregate balanced

Integration tests for the endpoint shapes, verified in CI (no Postgres locally).

## Out of scope

- Converting a group between types (immutable by decision).
- Recurring group expenses in a one-time group: they make no sense there, but they are created
  from a separate flow and are not blocked in this pass. Noted as a follow-up rather than
  silently half-handled.
