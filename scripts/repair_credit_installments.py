"""One-off repair for multi-installment credit expenses scrambled by an edit.

Before the reindex fix, `ExpenseManager.update_credit_expense` did two things wrong when
a credit expense was edited: it never reassigned any row to a new monthly share (so a date
change left every cuota in its original month), and it stamped `installment_no` from the
position of a row in `get_child_expenses()`, which has no ORDER BY. The result is a random
permutation of cuota numbers over unchanged months.

This script finds every multi-installment credit family whose rows disagree with what the
parent implies, and repairs them by replaying the *fixed* update path — so the repair uses
the same code the application now uses, rather than a second implementation that could
drift from it.

A family is correct when, for the parent's purchase date D and installment count N:
    cuota k lives in the monthly share for month(D) + k, for k = 1..N
with the parent being cuota 1, and each description ending in "(k/N)".

Usage:
    DATABASE_URL=<url> poetry run python scripts/repair_credit_installments.py           # dry run
    DATABASE_URL=<url> poetry run python scripts/repair_credit_installments.py --apply   # write

Dry run is the default. Families in settled months are reported but skipped unless
--allow-settled is passed, because rebuilding them changes balances already settled.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import date

from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------

FAMILIES_SQL = """
    SELECT p.id            AS parent_id,
           p.description   AS description,
           p.date          AS purchase_date,
           p.installments  AS installments,
           p.amount        AS amount_per_installment,
           p.group_id      AS group_id
    FROM expenses p
    WHERE p.parent_expense_id IS NULL
      AND p.installment_no = 1
      AND p.payment_type = 'CREDIT'
      AND p.installments > 1
    ORDER BY p.date, p.id
"""

ROWS_SQL = """
    SELECT e.id, e.description, e.installment_no, e.amount,
           ms.year AS share_year, ms.month AS share_month, ms.is_settled
    FROM expenses e
    JOIN monthly_shares ms ON e.monthly_share_id = ms.id
    WHERE e.id = :parent_id OR e.parent_expense_id = :parent_id
    ORDER BY e.id
"""


@dataclass
class Family:
    """One credit expense and every installment row belonging to it."""

    parent_id: int
    description: str
    purchase_date: date
    installments: int
    amount_per_installment: float
    group_id: int
    rows: list = field(default_factory=list)

    @property
    def total_amount(self) -> float:
        """The original purchase total, which the update path expects as its `amount`."""
        return self.amount_per_installment * self.installments

    def expected_period(self, installment_no: int) -> tuple[int, int]:
        """The (year, month) share that a given cuota belongs in."""
        share_date = self.purchase_date + relativedelta(months=installment_no)
        return share_date.year, share_date.month

    @property
    def is_unlinked(self) -> bool:
        """True when this family's rows were never linked by parent_expense_id.

        Older expenses stored each installment as a standalone row with no parent. Such a
        family cannot be rebuilt: its siblings still exist as separate rows, so recreating
        cuotas 2..N would duplicate them — and duplicate their amounts. Report, never touch.
        """
        return len(self.rows) != self.installments

    def problems(self) -> list[str]:
        """Describe every way this family disagrees with what its parent implies."""
        issues = []
        if self.is_unlinked:
            issues.append(
                f"only {len(self.rows)} of {self.installments} rows are linked to this parent "
                "(legacy unlinked installments — NOT auto-repairable)"
            )
            return issues

        seen_numbers = sorted(row.installment_no for row in self.rows)
        if seen_numbers != list(range(1, len(self.rows) + 1)):
            issues.append(f"installment numbers are {seen_numbers}")

        for row in self.rows:
            expected = self.expected_period(row.installment_no)
            actual = (row.share_year, row.share_month)
            if actual != expected:
                issues.append(
                    f"cuota {row.installment_no} sits in {actual[0]}-{actual[1]:02d}, "
                    f"expected {expected[0]}-{expected[1]:02d}"
                )
            suffix = f"({row.installment_no}/{self.installments})"
            if not row.description.endswith(suffix):
                issues.append(f"row {row.id} description does not end in {suffix}")
        return issues

    def touches_settled(self) -> bool:
        """True if any row currently sits in a settled month."""
        return any(row.is_settled for row in self.rows)


def load_families(session: Session) -> list[Family]:
    """Read every multi-installment credit family with its rows."""
    families = []
    for record in session.execute(text(FAMILIES_SQL)).mappings().all():
        family = Family(
            parent_id=record["parent_id"],
            description=record["description"],
            purchase_date=record["purchase_date"],
            installments=record["installments"],
            amount_per_installment=record["amount_per_installment"],
            group_id=record["group_id"],
        )
        family.rows = session.execute(text(ROWS_SQL), {"parent_id": family.parent_id}).mappings().all()
        families.append(family)
    return families


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------


def repair(session: Session, family: Family) -> None:
    """Rebuild one family by replaying the fixed update path."""
    # pylint: disable=import-outside-toplevel
    from template.adapters.repositories import GroupRepository, SQLAlchemyExpenseRepository
    from template.domain.models.expense_manager import ExpenseManager

    # pylint: enable=import-outside-toplevel

    expense_repo = SQLAlchemyExpenseRepository(session)
    group_repo = GroupRepository(session)
    manager = ExpenseManager(expense_repo, family.group_id, group_repo)

    parent = expense_repo.get_expense(family.parent_id)
    if parent is None:
        raise ValueError(f"parent expense {family.parent_id} vanished mid-repair")

    # update_credit_expense expects the purchase total, not the per-installment amount.
    parent.amount = family.total_amount
    parent.installments = family.installments
    manager.update_credit_expense(parent)


def main() -> int:
    """Report, and optionally repair, every scrambled credit family."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the repairs (default is dry run)")
    parser.add_argument("--all", action="store_true", help="also list families that are already correct")
    parser.add_argument("--family", type=int, help="dump every row of one family by parent id, then exit")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL"), help="defaults to $DATABASE_URL")
    parser.add_argument(
        "--allow-settled",
        action="store_true",
        help="also repair families sitting in settled months (changes settled balances)",
    )
    args = parser.parse_args()

    if not args.db_url:
        print("error: no database URL. Pass --db-url or set DATABASE_URL.", file=sys.stderr)
        return 2

    os.environ["DATABASE_URL"] = args.db_url
    os.environ.setdefault("DATABASE_ENV", "PROD")

    # Imported after DATABASE_URL is set: database.py builds its engine at import time.
    from template.adapters.database import SessionLocal  # pylint: disable=import-outside-toplevel

    broken: list[Family] = []
    settled_blocked: list[Family] = []
    unlinked: list[Family] = []

    if args.family:
        with SessionLocal() as session:
            for family in load_families(session):
                if family.parent_id != args.family:
                    continue
                print(f"#{family.parent_id} {family.description!r}")
                print(f"  purchase date : {family.purchase_date}")
                print(f"  installments  : {family.installments}")
                print(f"  per cuota     : {family.amount_per_installment}")
                print("  rows:")
                for row in family.rows:
                    expected = family.expected_period(row.installment_no)
                    print(
                        f"    id={row.id:<6} cuota {row.installment_no}/{family.installments}  "
                        f"share {row.share_year}-{row.share_month:02d}  "
                        f"expected {expected[0]}-{expected[1]:02d}  "
                        f"settled={row.is_settled}  {row.description!r}"
                    )
                print(f"  problems: {family.problems() or 'none'}")
        return 0

    with SessionLocal() as session:
        families = load_families(session)
        print(f"Scanned {len(families)} multi-installment credit expense(s).\n")

        for family in families:
            issues = family.problems()
            if not issues:
                if args.all:
                    print(f"OK     #{family.parent_id} {family.description[:40]!r} ({family.installments} cuotas)")
                continue
            label = f"#{family.parent_id} {family.description[:40]!r} " f"({family.installments} cuotas)"
            if family.is_unlinked:
                unlinked.append(family)
                print(f"LEGACY {label}")
            elif family.touches_settled() and not args.allow_settled:
                settled_blocked.append(family)
                print(f"SKIP (settled) {label}")
            else:
                broken.append(family)
                print(f"BROKEN {label}")
            for issue in issues:
                print(f"    - {issue}")
            print()

        print("=" * 60)
        print(f"Families needing repair: {len(broken)}")
        if unlinked:
            print(
                f"Legacy unlinked families (reported only, never rebuilt): {len(unlinked)} — "
                "their installments exist as standalone rows"
            )
        if settled_blocked:
            print(f"Skipped because they sit in settled months: {len(settled_blocked)} (use --allow-settled)")

        if not args.apply:
            print("\nDry run — nothing written. Re-run with --apply to commit.")
            return 0

        for family in broken:
            print(f"repairing #{family.parent_id} {family.description[:40]!r}...")
            repair(session, family)
        print(f"\nRepaired {len(broken)} family(ies).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
