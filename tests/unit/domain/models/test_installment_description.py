"""A one-cuota credit purchase is not "1 of 1": the "(k/N)" suffix only appears from 2 cuotas."""

from template.domain.models.expense_manager import installment_description


def test_single_installment_has_no_suffix():
    assert installment_description("Santander", 1, 1) == "Santander"


def test_multiple_installments_are_numbered():
    assert installment_description("Heladera", 2, 6) == "Heladera (2/6)"
