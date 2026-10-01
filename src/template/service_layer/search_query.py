"""Parsing of a free-text expense search: words, and an amount when the query is a number.

Pure functions, no DB. The accent mapping is shared with the SQL `translate()` in
`SearchRepository` and with `src/utils/search.ts` in the front, so the three agree on what
"cafe" matches.
"""

import re
from dataclasses import dataclass
from typing import Optional

ACCENTS_FROM = "áàâäéèêëíìîïóòôöúùûüñç"
ACCENTS_TO = "aaaaeeeeiiiioooouuuunc"
_ACCENT_TABLE = str.maketrans(ACCENTS_FROM, ACCENTS_TO)

# es-AR: dots group thousands, a comma marks decimals. A lone dot with 1-2 decimals is also read
# as a decimal point, for keyboards that only offer "." ("1.5").
_THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+(,\d{1,2})?$")
_PLAIN = re.compile(r"^\d+(,\d{1,2})?$")
_DOT_DECIMAL = re.compile(r"^\d+\.\d{1,2}$")

MIN_TEXT_LENGTH = 2


def normalize(text: str) -> str:
    """Lowercase and strip the accents that matter in Spanish."""
    return text.lower().translate(_ACCENT_TABLE)


def parse_amount(text: str) -> Optional[float]:
    """Read `text` as an amount, or None when it is not a number."""
    value = text.strip()
    if _THOUSANDS.match(value) or _PLAIN.match(value):
        return float(value.replace(".", "").replace(",", "."))
    if _DOT_DECIMAL.match(value):
        return float(value)
    return None


@dataclass(frozen=True)
class ParsedQuery:
    """Every term must match; `amount` also matches expenses of exactly that amount."""

    terms: tuple[str, ...]
    amount: Optional[float]


def parse_query(q: str) -> Optional[ParsedQuery]:
    """Split a query into normalized words. None when there is nothing worth searching."""
    stripped = q.strip()
    amount = parse_amount(stripped)
    if amount is None and len(stripped) < MIN_TEXT_LENGTH:
        return None
    terms = tuple(t for t in normalize(stripped).split() if t)
    if not terms:
        return None
    return ParsedQuery(terms=terms, amount=amount)
