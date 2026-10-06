from template.domain.models.pdf_builder import _split_breakdown
from template.domain.schemas.expense import SplitStrategySchema


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
