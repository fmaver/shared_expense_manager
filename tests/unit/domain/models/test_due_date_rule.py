"""La aritmética de vencimientos, que es donde están todos los casos borde."""

from datetime import date

import pytest

from template.domain.models.due_date import DueDateRule


def _monthly(day: int) -> DueDateRule:
    return DueDateRule(day_of_month=day, every_n_months=1, anchor_year=2026, anchor_month=1)


class TestOccurrenceOn:
    def test_a_normal_day_is_that_day(self):
        assert _monthly(20).occurrence_on(2026, 10) == date(2026, 10, 20)

    @pytest.mark.parametrize(
        "year,month,expected_day",
        [(2026, 11, 30), (2026, 2, 28), (2028, 2, 29), (2026, 12, 31)],
    )
    def test_day_31_clamps_to_the_last_day_of_a_short_month(self, year, month, expected_day):
        """Un vencimiento cargado el 31 no se saltea noviembre ni febrero."""
        assert _monthly(31).occurrence_on(year, month) == date(year, month, expected_day)


class TestOccursIn:
    def test_monthly_occurs_every_month(self):
        rule = _monthly(20)
        assert all(rule.occurs_in(2026, m) for m in range(1, 13))

    def test_bimonthly_alternates_from_its_anchor(self):
        """Gas bimestral arrancando en octubre: oct sí, nov no, dic sí."""
        rule = DueDateRule(day_of_month=15, every_n_months=2, anchor_year=2026, anchor_month=10)
        assert rule.occurs_in(2026, 10) is True
        assert rule.occurs_in(2026, 11) is False
        assert rule.occurs_in(2026, 12) is True
        assert rule.occurs_in(2027, 2) is True

    def test_nothing_occurs_before_the_anchor(self):
        rule = DueDateRule(day_of_month=15, every_n_months=2, anchor_year=2026, anchor_month=10)
        assert rule.occurs_in(2026, 8) is False

    def test_yearly_repeats_the_same_month(self):
        rule = DueDateRule(day_of_month=5, every_n_months=12, anchor_year=2026, anchor_month=3)
        assert rule.occurs_in(2027, 3) is True
        assert rule.occurs_in(2027, 4) is False


class TestNoWeekendShift:
    def test_a_due_date_on_a_sunday_stays_on_the_sunday(self):
        """Decisión del spec: si la boleta dice 20, la app dice 20 aunque sea domingo.

        Este test existe para que la decisión no se "arregle" sin querer más adelante.
        """
        assert _monthly(20).occurrence_on(2026, 9) == date(2026, 9, 20)
        assert date(2026, 9, 20).weekday() == 6, "el 20/09/2026 es domingo"


class TestNextOccurrence:
    def test_today_counts_as_the_next_occurrence(self):
        """Con notify_days_before = 0 el aviso sale el mismo día, así que hoy debe contar."""
        assert _monthly(20).next_occurrence(date(2026, 10, 20)) == date(2026, 10, 20)

    def test_after_the_day_it_rolls_to_the_following_month(self):
        assert _monthly(20).next_occurrence(date(2026, 10, 21)) == date(2026, 11, 20)

    def test_bimonthly_skips_the_month_in_between(self):
        rule = DueDateRule(day_of_month=15, every_n_months=2, anchor_year=2026, anchor_month=10)
        assert rule.next_occurrence(date(2026, 10, 16)) == date(2026, 12, 15)

    def test_before_the_anchor_it_returns_the_anchor_month(self):
        rule = DueDateRule(day_of_month=15, every_n_months=2, anchor_year=2026, anchor_month=10)
        assert rule.next_occurrence(date(2026, 7, 1)) == date(2026, 10, 15)
