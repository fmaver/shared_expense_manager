from template.service_layer.quick_capture_text import (
    GroupCandidate,
    option_label,
    pending_push_body,
    pick_options,
    similar_warning,
    summary_text,
)


def _g(gid, name="G", gtype="regular", members=2, recent=0, cats=0):
    return GroupCandidate(gid, name, gtype, members, recent, cats)


def test_labels_two_members_and_personal():
    pair = _g(1, "Fran y Guada", members=2)
    personal = _g(2, "Personal", "personal", members=1)
    assert option_label(pair, 5000, "ARS") == "Fran y Guada · $2.500 c/u"
    assert option_label(personal, 5000, "ARS") == "Personal · todo tuyo"


def test_label_three_members_and_usd():
    trio = _g(1, "Trio", members=3)
    assert option_label(trio, 5000, "ARS") == "Trio · $1.666,67 c/u"
    assert option_label(trio, 30, "USD") == "Trio · US$ 10 c/u"


def test_credit_drops_one_time():
    cands = [
        _g(1, gtype="one_time", recent=9),
        _g(2, recent=5),
        _g(3, recent=1),
    ]
    assert [c.group_id for c in pick_options(cands, "credit")] == [2, 3]
    assert [c.group_id for c in pick_options(cands, "debit")] == [1, 2]


def test_ranking_tie_by_group_id():
    cands = [_g(5, recent=2), _g(3, recent=2), _g(4, recent=2)]
    assert [c.group_id for c in pick_options(cands, "debit")] == [3, 4]


def test_suggested_by_category_wins_over_recent():
    cands = [_g(1, recent=10, cats=0), _g(2, recent=5, cats=3)]
    assert pick_options(cands, "debit")[0].group_id == 2


def test_category_tie_keeps_recent_order():
    cands = [_g(1, recent=10, cats=2), _g(2, recent=5, cats=2)]
    assert pick_options(cands, "debit")[0].group_id == 1


def test_single_group_one_option():
    assert len(pick_options([_g(1)], "debit")) == 1


def test_summary_and_warning():
    summary = summary_text(
        category="supermercado",
        description="Pizza",
        amount=2500,
        currency="ARS",
        payment_type="debit",
        installments=1,
    )
    assert summary == "🛒 Pizza · $2.500 · pagaste vos · débito"
    warning = similar_warning("Pizza", 2500.5, "ARS")
    assert warning == "⚠️ Parecido a uno que ya cargaste: $2.500,50 Pizza"


def test_summary_payment_wording_is_lowercase():
    def pago(payment_type: str, installments: int) -> str:
        text = summary_text(
            category="otros",
            description="Nafta",
            amount=100,
            currency="ARS",
            payment_type=payment_type,
            installments=installments,
        )
        return text.split("pagaste vos · ", 1)[1]

    assert pago("debit", 1) == "débito"
    assert pago("credit", 1) == "crédito"
    assert pago("credit", 3) == "crédito · 3 cuotas"


def test_push_body():
    drafts = [
        ("Supermercado", 5000.0, "x"),
        ("Nafta", 42300.0, "x"),
        ("Otro", 1.0, "x"),
    ]
    assert pending_push_body(drafts) == ("Tenés 3 gastos para revisar\nSupermercado $5.000 · Nafta $42.300 · y 1 más")
    assert pending_push_body([("Nafta", None, "x")]) == ("Tenés 1 gasto para revisar\nNafta")
    assert pending_push_body([("", None, "x")]).endswith("Captura sin leer")
