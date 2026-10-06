from datetime import date

from template.domain.models.enums import PaymentType
from template.domain.models.pdf_builder import (
    _currency_symbol,
    _format_multi_currency_total,
    _split_breakdown,
)
from template.domain.schemas.expense import ExpenseResponse, SplitStrategySchema


class TestSplitBreakdown:
    """`_split_breakdown` drives the PDF's "División" column — the per-member cash amounts that
    stop a percentage/exact split from being misread as an even split (a $300 expense split
    200/100 must never look like two $150 halves).
    """

    MEMBER_NAMES = {1: "Fran", 2: "Mama"}

    def test_equal_split_over_all_members(self):
        strategy = SplitStrategySchema(type="equal")
        text = _split_breakdown(strategy, 300.0, self.MEMBER_NAMES)
        assert text == "Fran $150,00 · Mama $150,00"

    def test_equal_split_over_a_participant_subset_excludes_everyone_else(self):
        member_names = {1: "Fran", 2: "Mama", 3: "Tio"}
        strategy = SplitStrategySchema(type="equal", participant_ids=[1, 2])
        text = _split_breakdown(strategy, 300.0, member_names)
        assert text == "Fran $150,00 · Mama $150,00"
        assert "Tio" not in text

    def test_percentage_split_shows_cash_not_percent(self):
        strategy = SplitStrategySchema(type="percentage", percentages={1: 60, 2: 40})
        text = _split_breakdown(strategy, 100000.0, self.MEMBER_NAMES)
        assert text == "Fran $60.000,00 · Mama $40.000,00"
        assert "%" not in text

    def test_uneven_percentage_split_never_looks_like_an_equal_half(self):
        """The reported bug: a $300 expense split 200/100 must not render as two $150 halves."""
        strategy = SplitStrategySchema(type="percentage", percentages={1: 66.666667, 2: 33.333333})
        text = _split_breakdown(strategy, 300.0, self.MEMBER_NAMES)
        assert text == "Fran $200,00 · Mama $100,00"

    def test_exact_split_uses_the_given_amounts(self):
        strategy = SplitStrategySchema(type="exact", amounts={1: 20000, 2: 28000})
        text = _split_breakdown(strategy, 48000.0, self.MEMBER_NAMES)
        assert text == "Fran $20.000,00 · Mama $28.000,00"

    def test_a_split_id_outside_the_current_roster_is_silently_excluded(self):
        """Matches `calculate_shares` itself: a member_id absent from `members` never gets a
        share assigned (orphan data from a member who left the group, say) — the breakdown
        must not invent a figure that the balance math doesn't actually use."""
        strategy = SplitStrategySchema(type="exact", amounts={1: 20000, 99: 28000})
        text = _split_breakdown(strategy, 48000.0, self.MEMBER_NAMES)
        assert "99" not in text
        assert text == "Fran $20.000,00"

    def test_no_members_returns_empty_string(self):
        strategy = SplitStrategySchema(type="equal")
        assert _split_breakdown(strategy, 100.0, {}) == ""

    def test_usd_split_uses_the_us_dollar_prefix_not_pesos(self):
        """A USD expense must never read like pesos — "$" and "US$" are different units and
        the figure is never converted, only labelled with the expense's own currency."""
        strategy = SplitStrategySchema(type="equal")
        text = _split_breakdown(strategy, 200.0, self.MEMBER_NAMES, currency="USD")
        assert text == "Fran US$100,00 · Mama US$100,00"

    def test_ars_split_defaults_to_the_peso_prefix(self):
        strategy = SplitStrategySchema(type="equal")
        text = _split_breakdown(strategy, 200.0, self.MEMBER_NAMES)
        assert text == "Fran $100,00 · Mama $100,00"


class TestCurrencySymbol:
    def test_usd_maps_to_us_dollar_sign(self):
        assert _currency_symbol("USD") == "US$"

    def test_ars_maps_to_peso_sign(self):
        assert _currency_symbol("ARS") == "$"

    def test_unknown_or_missing_currency_defaults_to_peso_sign(self):
        assert _currency_symbol(None) == "$"
        assert _currency_symbol("") == "$"


class TestFormatMultiCurrencyTotal:
    """The month total must never add ARS and USD face values together — that would print a
    number that means nothing and would look like plain pesos to whoever reads the report.
    """

    @staticmethod
    def _expense(amount: float, currency: str = "ARS") -> ExpenseResponse:
        return ExpenseResponse(
            description="x",
            amount=amount,
            date=date(2026, 10, 1),
            category="otros",
            payer_id=1,
            payment_type=PaymentType.DEBIT,
            installments=1,
            installment_no=1,
            split_strategy=SplitStrategySchema(type="equal"),
            currency=currency,
        )

    def test_ars_only_renders_a_single_figure(self):
        expenses = [self._expense(100.0), self._expense(200.0)]
        assert _format_multi_currency_total(expenses) == "$300,00"

    def test_usd_only_renders_with_the_us_dollar_prefix(self):
        expenses = [self._expense(100.0, "USD"), self._expense(50.0, "USD")]
        assert _format_multi_currency_total(expenses) == "US$150,00"

    def test_mixed_currencies_are_shown_separately_never_summed(self):
        expenses = [self._expense(238000.0, "ARS"), self._expense(200.0, "USD")]
        text = _format_multi_currency_total(expenses)
        assert text == "$238.000,00 + US$200,00"
        # The two units must never be added into one number.
        assert "238200" not in text.replace(".", "").replace(",00", "")

    def test_no_expenses_renders_zero_pesos(self):
        assert _format_multi_currency_total([]) == "$0,00"
