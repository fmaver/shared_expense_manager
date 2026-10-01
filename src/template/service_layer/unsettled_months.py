"""Which past months of a group were left unsettled.

A month counts when it is before the current month, not settled, and someone still has a
balance. The current month is open by definition and future months exist only because of
installments, so neither is something that "slipped through".
"""

from datetime import date
from typing import Iterable

from template.domain.models.models import MonthlyShare

BALANCE_EPSILON = 0.01


def _is_unsettled_past_month(share: MonthlyShare, current: tuple[int, int]) -> bool:
    """True if this share is before `current`, unsettled, and someone still has a balance."""
    if (share.year, share.month) >= current or share.is_settled:
        return False
    return any(abs(value) > BALANCE_EPSILON for value in (share.balances or {}).values())


def unsettled_periods(shares: Iterable[MonthlyShare], today: date) -> list[tuple[int, int]]:
    """(year, month) of every past, unsettled month with a non-zero balance, oldest first."""
    current = (today.year, today.month)
    periods = [(share.year, share.month) for share in shares if _is_unsettled_past_month(share, current)]
    return sorted(periods)
