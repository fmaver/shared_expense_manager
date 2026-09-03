"""One-off repair for recurring instances whose currency was dropped at materialization.

Before the currency-propagation fix, materializing a recurring template into a monthly
instance never passed `currency`, so the column fell back to its 'ARS' default. A USD
salary of 4000 was therefore stored — and displayed, and summed — as 4000 ARS in every
month after the template's start month.

This script re-derives each instance's currency from its parent template. Amounts are
never touched; only the currency label is corrected.

Usage:
    DATABASE_URL=<url> poetry run python scripts/backfill_recurring_currency.py            # dry run
    DATABASE_URL=<url> poetry run python scripts/backfill_recurring_currency.py --apply    # write

Dry run is the default and prints every row that would change.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """One instance table and the template table its currency should come from."""

    name: str
    select_sql: str
    update_sql: str
    touches_balances: bool = False


TARGETS = [
    Target(
        name="income_instances",
        select_sql="""
            SELECT i.id, i.year, i.month, i.label, i.amount, i.currency AS current, r.currency AS correct
            FROM income_instances i
            JOIN recurring_incomes r ON i.recurring_income_id = r.id
            WHERE i.source = 'recurring' AND i.currency IS DISTINCT FROM r.currency
            ORDER BY i.year, i.month, i.id
        """,
        update_sql="""
            UPDATE income_instances i
            SET currency = r.currency
            FROM recurring_incomes r
            WHERE i.recurring_income_id = r.id
              AND i.source = 'recurring'
              AND i.currency IS DISTINCT FROM r.currency
        """,
    ),
    Target(
        name="recurring_personal_expense_instances",
        select_sql="""
            SELECT i.id, i.year, i.month, i.label, i.amount, i.currency AS current, r.currency AS correct
            FROM recurring_personal_expense_instances i
            JOIN recurring_personal_expenses r ON i.recurring_expense_id = r.id
            WHERE i.currency IS DISTINCT FROM r.currency
            ORDER BY i.year, i.month, i.id
        """,
        update_sql="""
            UPDATE recurring_personal_expense_instances i
            SET currency = r.currency
            FROM recurring_personal_expenses r
            WHERE i.recurring_expense_id = r.id
              AND i.currency IS DISTINCT FROM r.currency
        """,
    ),
    Target(
        name="expenses (from recurring group templates)",
        select_sql="""
            SELECT e.id,
                   EXTRACT(YEAR FROM e.date)::int  AS year,
                   EXTRACT(MONTH FROM e.date)::int AS month,
                   e.description AS label,
                   e.amount,
                   e.currency AS current,
                   r.currency AS correct,
                   COALESCE(ms.is_settled, false) AS is_settled
            FROM expenses e
            JOIN recurring_group_expenses r ON e.recurring_template_id = r.id
            LEFT JOIN monthly_shares ms ON e.monthly_share_id = ms.id
            WHERE e.currency IS DISTINCT FROM r.currency
            ORDER BY e.date, e.id
        """,
        update_sql="""
            UPDATE expenses e
            SET currency = r.currency
            FROM recurring_group_expenses r
            WHERE e.recurring_template_id = r.id
              AND e.currency IS DISTINCT FROM r.currency
        """,
        touches_balances=True,
    ),
]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _report(conn: Connection, target: Target) -> tuple[int, int]:
    """Print the rows that would change. Returns (rows_affected, settled_rows_affected)."""
    rows = conn.execute(text(target.select_sql)).mappings().all()
    print(f"\n=== {target.name} — {len(rows)} row(s) to correct ===")
    if not rows:
        return 0, 0

    settled = 0
    for row in rows:
        marker = ""
        if target.touches_balances and row.get("is_settled"):
            marker = "  <-- SETTLED MONTH, balances would change"
            settled += 1
        print(
            f"  id={row['id']:<6} {row['year']}-{row['month']:02d}  "
            f"{str(row['label'])[:28]:<28} {row['amount']:>12,.2f}  "
            f"{row['current']} -> {row['correct']}{marker}"
        )
    return len(rows), settled


def main() -> int:
    """Run the backfill, dry by default."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes (default is dry run)")
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL"),
        help="database URL (defaults to $DATABASE_URL)",
    )
    parser.add_argument(
        "--allow-settled",
        action="store_true",
        help="also correct rows in settled months (changes already-settled group balances)",
    )
    args = parser.parse_args()

    if not args.db_url:
        print("error: no database URL. Pass --db-url or set DATABASE_URL.", file=sys.stderr)
        return 2

    engine = create_engine(args.db_url)
    total = 0
    total_settled = 0

    with engine.connect() as conn:
        for target in TARGETS:
            affected, settled = _report(conn, target)
            total += affected
            total_settled += settled

        print(f"\n{'=' * 60}\nTotal rows to correct: {total}")
        if total_settled:
            print(f"Of those, {total_settled} sit in SETTLED months (group balances would change).")

        if not args.apply:
            print("\nDry run — nothing written. Re-run with --apply to commit.")
            return 0

        if total_settled and not args.allow_settled:
            print(
                "\nRefusing to write: some rows are in settled months, which would retroactively "
                "change settled balances. Re-run with --allow-settled if that is intended.",
                file=sys.stderr,
            )
            return 1

        for target in TARGETS:
            result = conn.execute(text(target.update_sql))
            print(f"updated {result.rowcount} row(s) in {target.name}")
        conn.commit()
        print("\nDone.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
