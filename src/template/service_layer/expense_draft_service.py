"""Turn an uploaded screenshot into an expense draft.

The image is read by an LLM (Gemini Vision, via `image_expense_parser`), and that shapes the
whole design:

- **It returns a draft, never a saved expense.** The model is sometimes wrong, and this is
  money. A person confirms before anything is written.
- **Obvious rejects happen before the call.** Each call is paid for and takes seconds, so a
  PDF, an empty body or a 20 MB photo is refused here rather than after a round trip.
- **Low confidence is passed through, not smoothed over.** The UI needs to know when to be
  sceptical.

The same parser already backs the WhatsApp photo flow; this only makes it reachable from the
web app.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from template.domain.models.category import Category
from template.service_layer.image_expense_parser import parse_image_expense

# Comfortably above a phone screenshot, well below anything worth paying an LLM call for.
MAX_IMAGE_BYTES = 8 * 1024 * 1024

_ALLOWED_MIME_PREFIX = "image/"


@dataclass
class ExpenseDraft:  # pylint: disable=too-many-instance-attributes
    """What the model read off the image. Every field is a suggestion, not a decision."""

    amount: Optional[float]
    description: str
    category: str
    date: date
    payment_type: str
    installments: int
    currency: str
    confidence: str


def build_expense_draft(image_bytes: bytes, mime_type: str) -> ExpenseDraft:
    """Parse an uploaded image into a draft expense.

    Raises ValueError with a message meant for the user when the upload is unusable or the
    model cannot read it.
    """
    if not image_bytes:
        raise ValueError("The image is empty")
    if not mime_type or not mime_type.startswith(_ALLOWED_MIME_PREFIX):
        raise ValueError("Only images can be parsed")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("The image is too large — under 8 MB, please")

    # Internal categories (balance, prestamo) are never offered: the model can only pick from
    # what it is given, and those two must never be chosen for a user-entered expense.
    parsed = parse_image_expense(image_bytes, mime_type, Category.get_user_categories())
    if parsed is None:
        raise ValueError("Could not read an expense from that image")

    return ExpenseDraft(
        amount=parsed.amount,
        description=parsed.description,
        category=parsed.category,
        date=parsed.expense_date,
        payment_type=parsed.payment_type,
        installments=parsed.installments,
        currency=parsed.currency,
        confidence=parsed.confidence,
    )
