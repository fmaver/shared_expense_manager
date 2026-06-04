# Personal Finance Balance Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the personal finance projected balance to correctly account for money already paid out-of-pocket as a group payer, and redesign the balance cards to clearly show "what you have now" vs "what you'll have after settlement".

**Architecture:** Add a new `total_paid_as_payer_unsettled` metric in the ledger service (the sum of full expense amounts in unsettled groups where the owner is the payer), use it to compute a correct `current_balance`, and derive `projected_balance = current_balance + pending_settlements_total`. The frontend balance cards are simplified to show two numbers: **Current** and **Projected**.

**Tech Stack:** Python/FastAPI backend (package `template`), React/TypeScript frontend, Pydantic v2, Tailwind CSS.

---

## The Bug — Illustrated

| Scenario | Income | Direct | Paid as payer (unsettled) | Net pending | Current (correct) | Projected (correct) |
|---|---|---|---|---|---|---|
| Unsettled group, owner paid | $3,000 | $1,000 | $400 | +$300 | $1,600 | $1,900 |
| Same, after settlement | $3,000 | $1,000 | $0 | $0 | $1,900 | $1,900 |

Old formula (wrong): `projected = 3000 - 1000 + 300 = $2,300` (ignores $400 already paid)  
New formula: `current = 3000 - 1000 - 400 = $1,600` → `projected = $1,600 + $300 = $1,900`

---

## Files

### Backend

| File | Action | What changes |
|---|---|---|
| `src/template/domain/schemas/income.py` | Modify | Add `current_balance: float` and `total_paid_as_payer_unsettled: float` to `PersonalLedgerResponse` |
| `src/template/service_layer/personal_ledger_service.py` | Modify | Track payer amounts in unsettled groups; update balance formulas |
| `tests/unit/service/test_personal_ledger_service.py` | Modify | Add `current_balance` assertions; add test for owner-as-payer current balance |

### Frontend

| File | Action | What changes |
|---|---|---|
| `src/types/expense.ts` | Modify | Add `currentBalance` and `totalPaidAsPayerUnsettled` to `PersonalLedgerResponse` |
| `src/pages/PersonalDashboard.tsx` | Modify | Replace 3-card layout with 2-card layout (Current / Projected); update pending card label |

---

## Task 1 — Backend: schema additions

**Files:**
- Modify: `src/template/domain/schemas/income.py`

Read `PersonalLedgerResponse` (lines ~111-126 of the file) before editing.

- [ ] **Step 1: Add two fields to `PersonalLedgerResponse`**

In `src/template/domain/schemas/income.py`, add to `PersonalLedgerResponse`:

```python
class PersonalLedgerResponse(CamelCaseModel):
    year: int
    month: int
    total_income: float
    incomes: list[IncomeInstanceResponse]
    total_personal_expenses: float
    personal_expenses: list[ExpenseResponse]
    total_shares_pending: float
    total_shares_realized: float
    mirrored_shares: list[MirroredShareItem]
    recurring_personal_expenses: list[RecurringPersonalExpenseInstanceResponse] = []
    # Per-group net balance for the month (positive = creditor, negative = debtor)
    group_balances: list[GroupBalanceItem]
    # NEW: money already paid out-of-pocket as payer in unsettled groups
    total_paid_as_payer_unsettled: float
    projected_balance: float
    realized_balance: float
    # NEW: actual cash position right now (before pending settlements clear)
    current_balance: float
    # Net amount across all unsettled groups: positive = you'll receive, negative = you'll pay
    pending_settlements_total: float
```

- [ ] **Step 2: Run existing unit tests to confirm no breakage yet**

```bash
cd /Users/franciscomaver/Documents/shared_expenses/shared_expense_manager
make test
```
Expected: FAIL — `PersonalLedgerResponse` is missing `total_paid_as_payer_unsettled` and `current_balance` in the service layer. That's expected — the service hasn't been updated yet.

- [ ] **Step 3: Commit schema**

```bash
git add src/template/domain/schemas/income.py
git commit -m "feat(schema): add current_balance and total_paid_as_payer_unsettled to PersonalLedgerResponse"
```

---

## Task 2 — Backend: ledger service formula fix

**Files:**
- Modify: `src/template/service_layer/personal_ledger_service.py`

Read the full file before editing. Key section is Step E (the mirrored shares loop) and Step F (balance computation).

- [ ] **Step 1: Track payer amounts in Step E**

In `get_ledger`, inside the Step E loop (after `if not source_share: continue`), add tracking of payer amounts for **unsettled** groups only.

The full updated Step E section should look like:

```python
# Step E: mirrored shares + net group balances from OTHER groups
mirrored_shares: list[MirroredShareItem] = []
group_balances: list[GroupBalanceItem] = []
total_paid_as_payer_unsettled = 0.0   # ← NEW
other_groups = self._group_repo.list_for_member(owner_member_id, include_personal=False)
for source_group in other_groups:
    source_share = self._expense_repo.get_monthly_share(year, month, source_group.id)
    if not source_share:
        continue

    # Net group balance for this owner: positive = creditor, negative = debtor
    net_balance = round(source_share.balances.get(str(owner_member_id), 0.0), 2)
    group_balances.append(
        GroupBalanceItem(
            source_group_id=source_group.id,
            source_group_name=source_group.name,
            net_balance=net_balance,
            is_settled=source_share.is_settled,
        )
    )

    if not source_share.expenses:
        continue
    # Only fetch members if there are expenses to process
    members_list = self._group_repo.list_members(source_group.id)
    members_dict = {m.id: m for m in members_list}
    for expense in source_share.expenses:
        # Skip internal categories (balance/prestamo)
        if Category.is_internal_category(expense.category.name):
            continue
        # NEW: track money already paid out-of-pocket in unsettled groups
        if not source_share.is_settled and expense.payer_id == owner_member_id:
            total_paid_as_payer_unsettled += expense.amount
        # Compute this owner's share (for mirrored_shares display list)
        try:
            shares = expense.split_strategy.calculate_shares(expense.amount, list(members_dict.values()))
        except ValueError:
            continue
        owner_share = shares.get(owner_member_id, 0.0)
        if owner_share < 0.005:
            continue
        status = "realized" if source_share.is_settled else "pending"
        mirrored_shares.append(
            MirroredShareItem(
                source_group_id=source_group.id,
                source_group_name=source_group.name,
                source_expense_id=expense.id,
                description=expense.description,
                category=expense.category.name,
                date=expense.date,
                share_amount=round(owner_share, 2),
                status=status,
                installment_no=expense.installment_no,
                installments=expense.installments,
            )
        )
total_paid_as_payer_unsettled = round(total_paid_as_payer_unsettled, 2)   # ← NEW
```

- [ ] **Step 2: Update Step F with the corrected formulas**

Replace the entire Step F block with:

```python
# Step F: compute balances
# Gross shares kept for display context in mirrored shares list
total_shares_pending = round(sum(s.share_amount for s in mirrored_shares if s.status == "pending"), 2)
total_shares_realized = round(sum(s.share_amount for s in mirrored_shares if s.status == "realized"), 2)
# Net group balance across unsettled groups (signed):
# positive = you'll receive at settlement, negative = you'll pay
pending_settlements_total = round(sum(gb.net_balance for gb in group_balances if not gb.is_settled), 2)
# current_balance: actual cash in pocket right now
#   = income - direct expenses - money already paid upfront as payer (unsettled) - realized group costs
current_balance = round(
    total_income - total_personal_expenses - total_paid_as_payer_unsettled - total_shares_realized, 2
)
# projected_balance: current + what pending settlements will add/subtract
projected_balance = round(current_balance + pending_settlements_total, 2)
# realized_balance: position considering only fully settled groups (no pending)
realized_balance = round(total_income - total_personal_expenses - total_shares_realized, 2)
```

- [ ] **Step 3: Add the new fields to the returned `PersonalLedgerResponse`**

In the `return PersonalLedgerResponse(...)` call, add:

```python
return PersonalLedgerResponse(
    year=year,
    month=month,
    total_income=total_income,
    incomes=incomes_response,
    total_personal_expenses=total_personal_expenses,
    personal_expenses=personal_expenses_list,
    total_shares_pending=total_shares_pending,
    total_shares_realized=total_shares_realized,
    mirrored_shares=mirrored_shares,
    recurring_personal_expenses=recurring_exp_response,
    group_balances=group_balances,
    total_paid_as_payer_unsettled=total_paid_as_payer_unsettled,   # ← NEW
    projected_balance=projected_balance,
    realized_balance=realized_balance,
    current_balance=current_balance,                                # ← NEW
    pending_settlements_total=pending_settlements_total,
)
```

- [ ] **Step 4: Run unit tests**

```bash
make test
```
Expected: 296 passed. If tests fail due to missing `current_balance`/`total_paid_as_payer_unsettled` in test expectations, fix them in the next step.

- [ ] **Step 5: Update the unit test for owner-as-payer**

In `tests/unit/service/test_personal_ledger_service.py`, find `test_owner_payer_status_irrelevant`. That test has:
- expense $200, payer_id=1 (OWNER), owner_share=100
- mock_share.balances = `{"1": 100.0}` (owner is creditor, owed $100)
- Income = 0, direct = 0

Add these assertions at the end of the test:
```python
assert ledger.total_paid_as_payer_unsettled == 200.0   # owner paid $200 upfront
assert ledger.current_balance == -200.0                 # cash now: 0 - 0 - 200 = -200
assert ledger.projected_balance == -100.0               # -200 + 100 (net pending) = -100
```

Also add `current_balance` assertions to the existing tests where `projected_balance` is already checked:

In `test_mirrored_share_pending` (owner is NOT payer, payer_id=2):
```python
assert ledger.total_paid_as_payer_unsettled == 0.0    # owner didn't pay
assert ledger.current_balance == 0.0                   # 0 - 0 - 0 = 0
assert ledger.projected_balance == -100.0              # 0 + (-100) = -100  (unchanged)
```

In `test_empty_ledger_all_zeros`:
```python
assert ledger.total_paid_as_payer_unsettled == 0.0
assert ledger.current_balance == 0.0
```

- [ ] **Step 6: Run tests again and confirm pass**

```bash
make test
```
Expected: 296 passed.

- [ ] **Step 7: Run lint**

```bash
make lint
```
Expected: all hooks pass.

- [ ] **Step 8: Commit**

```bash
git add src/template/service_layer/personal_ledger_service.py \
        tests/unit/service/test_personal_ledger_service.py
git commit -m "fix(ledger): current_balance accounts for payer advances; projected = current + pending"
```

---

## Task 3 — Frontend: type update

**Files:**
- Modify: `src/types/expense.ts` in `shared_expense_front/`

- [ ] **Step 1: Add new fields to `PersonalLedgerResponse`**

Find the `PersonalLedgerResponse` interface and add two fields:

```typescript
export interface PersonalLedgerResponse {
  year: number;
  month: number;
  totalIncome: number;
  incomes: IncomeInstanceResponse[];
  totalPersonalExpenses: number;
  personalExpenses: ExpenseResponse[];
  totalSharesPending: number;
  totalSharesRealized: number;
  mirroredShares: MirroredShareItem[];
  recurringPersonalExpenses: RecurringPersonalExpenseInstanceResponse[];
  groupBalances: GroupBalanceItem[];
  totalPaidAsPayerUnsettled: number;   // ← NEW
  projectedBalance: number;
  realizedBalance: number;
  currentBalance: number;              // ← NEW
  pendingSettlementsTotal: number;
}
```

- [ ] **Step 2: Build to confirm no TypeScript errors**

```bash
cd /Users/franciscomaver/Documents/shared_expenses/shared_expense_front
npm run build
```
Expected: clean build.

- [ ] **Step 3: Commit**

```bash
git add src/types/expense.ts
git commit -m "feat(types): add currentBalance and totalPaidAsPayerUnsettled to PersonalLedgerResponse"
```

---

## Task 4 — Frontend: redesign balance cards

**Files:**
- Modify: `src/pages/PersonalDashboard.tsx` in `shared_expense_front/`

Read the current balance summary section (the `grid grid-cols-2 gap-3 sm:grid-cols-3` block and the settlement positions card below it) before editing.

The goal: replace the 3-card layout (total income / total expenses / projected balance) with a cleaner layout that answers the two questions the user actually cares about.

**New layout:**

```
┌─────────────────┬─────────────────┐
│ Income          │ Personal        │
│ $3,000          │ expenses $1,000 │
├─────────────────┴─────────────────┤
│ Current balance         $1,600    │  (what you have RIGHT NOW)
│ After settlement        $1,900    │  (projected — shown only if ≠ current)
└───────────────────────────────────┘
```

- [ ] **Step 1: Replace the balance summary section**

Find and replace the existing grid of 3 cards (`{ledger && ( <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">...`). Replace with:

```tsx
{ledger && (
  <div className="space-y-3">
    {/* Income + expenses row */}
    <div className="grid grid-cols-2 gap-3">
      <div className="bg-card border border-border rounded-xl p-4">
        <p className="text-xs text-muted-foreground">{t('personal.totalIncome')}</p>
        <p className="text-lg font-bold text-green-600 mt-1">{formatCurrency(ledger.totalIncome)}</p>
      </div>
      <div className="bg-card border border-border rounded-xl p-4">
        <p className="text-xs text-muted-foreground">{t('personal.totalExpenses')}</p>
        <p className="text-lg font-bold text-red-500 mt-1">{formatCurrency(ledger.totalPersonalExpenses)}</p>
      </div>
    </div>

    {/* Balance card — the main answer */}
    <div className="bg-card border border-border rounded-xl p-4 space-y-3">
      {/* Current balance: what you have right now */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-foreground">{t('personal.currentBalance')}</p>
          <p className="text-xs text-muted-foreground">{t('personal.currentBalanceDesc')}</p>
        </div>
        <p className={`text-xl font-bold ${ledger.currentBalance >= 0 ? 'text-green-600' : 'text-red-500'}`}>
          {formatCurrency(ledger.currentBalance)}
        </p>
      </div>

      {/* Projected balance — only shown when different from current (i.e. pending settlements exist) */}
      {Math.abs(ledger.pendingSettlementsTotal) > 0.01 && (
        <>
          <div className="border-t border-border/50" />
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-foreground">{t('personal.projectedBalance')}</p>
              <p className="text-xs text-muted-foreground">
                {ledger.pendingSettlementsTotal > 0
                  ? t('personal.afterReceiving', { amount: formatCurrency(ledger.pendingSettlementsTotal) })
                  : t('personal.afterPaying', { amount: formatCurrency(Math.abs(ledger.pendingSettlementsTotal)) })}
              </p>
            </div>
            <p className={`text-lg font-bold ${ledger.projectedBalance >= 0 ? 'text-green-600' : 'text-red-500'}`}>
              {formatCurrency(ledger.projectedBalance)}
            </p>
          </div>
        </>
      )}
    </div>
  </div>
)}
```

- [ ] **Step 2: Update the "Settlement positions" card**

The existing settlement positions card shows `pendingSettlementsTotal` with "to receive" / "to pay" labels. Update the bottom total row label to be clearer:

Find the `{t('personal.pendingSettlements')}` label in the settlement positions card and change it to use `{t('personal.netAtSettlement')}`.

- [ ] **Step 3: Add new i18n keys to BOTH `en.json` and `es.json`**

Add inside the `personal` section:

**English:**
```json
"currentBalance": "Current balance",
"currentBalanceDesc": "What you have right now",
"afterReceiving": "After receiving {{amount}}",
"afterPaying": "After paying {{amount}}",
"netAtSettlement": "Net at settlement"
```

**Spanish:**
```json
"currentBalance": "Balance actual",
"currentBalanceDesc": "Lo que tenés ahora mismo",
"afterReceiving": "Tras recibir {{amount}}",
"afterPaying": "Tras pagar {{amount}}",
"netAtSettlement": "Neto al liquidar"
```

- [ ] **Step 4: Build and lint**

```bash
npm run build
npm run lint
```
Expected: clean build, 0 errors.

- [ ] **Step 5: Commit**

```bash
git add src/pages/PersonalDashboard.tsx \
        src/i18n/locales/en.json \
        src/i18n/locales/es.json
git commit -m "feat(personal): redesign balance cards — current balance + projected after settlement"
```

---

## Task 5 — Push both repos

- [ ] **Step 1: Push backend**

```bash
cd /Users/franciscomaver/Documents/shared_expenses/shared_expense_manager
git push
```

- [ ] **Step 2: Push frontend**

```bash
cd /Users/franciscomaver/Documents/shared_expenses/shared_expense_front
git push
```

---

## Verification

1. Income = $3,000, no direct expenses, no groups → Current = $3,000, Projected card not shown
2. Add personal expense $1,000 → Current = $2,000
3. In an unsettled shared group: $400 expense, you paid, 4-way equal split → Current = $2,000 - $400 = $1,600 | Projected shows $1,900 with "after receiving $300"
4. Settle the group → Current = $1,900, Projected card disappears (same as current)
5. Another member is the payer of a $200 expense you owe $50 of → Current unchanged (you didn't pay upfront), Projected = Current - $50 with "after paying $50"

---

## Notes

- `total_paid_as_payer_unsettled` is computed from the same expense loop already in Step E — no new DB queries.
- The `total_shares_pending` / `total_shares_realized` fields are kept in the response for the `mirroredShares` display section (showing individual expense shares for context) but are no longer used in the main balance formula.
- `realizedBalance` is kept in the response but not prominently displayed — it equals `projectedBalance` when all groups are settled, which is the natural convergence.
