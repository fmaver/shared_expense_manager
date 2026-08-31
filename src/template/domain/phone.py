"""Phone-number normalization.

WhatsApp/Meta represents Argentine mobile numbers with an extra ``9`` after the
country code (``549XXXXXXXXXX``), but the system must store them WITHOUT it
(``54XXXXXXXXXX``) so that inbound webhook lookups and outbound sends agree.
Normalize at every write point so storage is always canonical regardless of how
the user typed the number.
"""

import re
from typing import Optional


def normalize_ar_phone(raw: Optional[str]) -> Optional[str]:
    """Normalize loose phone input to the canonical stored format ``54XXXXXXXXXX``.

    Accepts ``+``, spaces, dashes, parentheses, an international ``00`` prefix, a
    trunk ``0``, and numbers with or without the ``54`` country code. Drops the
    Argentine mobile ``9`` that follows the country code. Returns ``None`` when
    the input has no digits (the phone field is optional).
    """
    if raw is None:
        return None

    digits = re.sub(r"\D", "", raw)  # drop +, spaces, dashes, parentheses
    if not digits:
        return None

    if digits.startswith("00"):  # international access prefix
        digits = digits[2:]

    if digits.startswith("54"):
        rest = digits[2:]
    else:
        # Local input without a country code — drop the trunk 0 if present.
        rest = digits[1:] if digits.startswith("0") else digits

    # Drop the mobile "9" that sits right after the country code.
    if rest.startswith("9"):
        rest = rest[1:]

    return "54" + rest
