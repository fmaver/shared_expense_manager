"""Group options and menu texts for the quick-capture iOS shortcut.

Pure logic, no DB access: the caller loads the candidates and this module ranks
them and builds the strings the shortcut shows.
"""

from dataclasses import dataclass

from template.domain.models.category import Category
from template.domain.models.formatters import format_amount_es, format_payment_type_es

MAX_OPTIONS = 2


@dataclass
class GroupCandidate:
    group_id: int
    name: str
    group_type: str
    member_count: int
    recent_count: int
    category_count: int


def _money(amount: float, currency: str) -> str:
    """`$2.500` / `$1.666,67` / `US$ 10`: whole amounts drop the `,00`."""
    text = format_amount_es(amount)
    if text.endswith(",00"):
        text = text[:-3]
    return f"US$ {text}" if currency == "USD" else f"${text}"


def pick_options(candidates: list[GroupCandidate], payment_type: str) -> list[GroupCandidate]:
    """Up to two groups, ranked by recent use; the suggested one goes first."""
    pool = [c for c in candidates if not (payment_type == "credit" and c.group_type == "one_time")]
    pool.sort(key=lambda c: (-c.recent_count, c.group_id))
    top = pool[:MAX_OPTIONS]
    if len(top) == 2 and top[1].category_count > top[0].category_count:
        top = [top[1], top[0]]
    return top


def option_label(candidate: GroupCandidate, amount: float, currency: str) -> str:
    """Menu label: per-person share, or "todo tuyo" for the personal group."""
    if candidate.group_type == "personal":
        return "Personal · todo tuyo"
    share = round(amount / max(candidate.member_count, 1), 2)
    return f"{candidate.name} · {_money(share, currency)} c/u"


def summary_text(  # pylint: disable=too-many-arguments
    *,
    category: str,
    description: str,
    amount: float,
    currency: str,
    payment_type: str,
    installments: int,
) -> str:
    """One-line summary of the draft shown before confirming."""
    emoji = Category.get_category_emoji(category)
    pago = format_payment_type_es(payment_type, installments)
    lead = f"{emoji} " if emoji else ""
    return f"{lead}{description} · {_money(amount, currency)} · pagaste vos · {pago}"


def similar_warning(description: str, amount: float, currency: str) -> str:
    """Warning shown when a similar expense already exists."""
    return f"⚠️ Parecido a uno que ya cargaste: {_money(amount, currency)} {description}"


def pending_push_body(drafts: list[tuple[str, float | None, str]]) -> str:
    """Body for the pending-drafts push; each draft is (description, amount, currency)."""
    count = len(drafts)
    head = "Tenés 1 gasto para revisar" if count == 1 else f"Tenés {count} gastos para revisar"
    items = []
    for description, amount, currency in drafts[:2]:
        parts = [description] if description else []
        if amount is not None:
            parts.append(_money(amount, currency))
        items.append(" ".join(parts) or "Captura sin leer")
    line = " · ".join(items)
    if count > 2:
        line += f" · y {count - 2} más"
    return f"{head}\n{line}"
