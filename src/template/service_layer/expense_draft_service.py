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

# Raster photo and screenshot types only. Quick-capture drafts store the upload and serve it back
# with its declared type, so a vector type that can carry script (image/svg+xml) is refused.
# gif stays because the parse-image endpoint shares this check and already accepted it.
ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", "image/gif")


def normalise_mime(mime_type: str) -> str:
    """`IMAGE/JPEG; charset=x` -> `image/jpeg`."""
    return (mime_type or "").split(";", 1)[0].strip().lower()


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


def validate_image(image_bytes: bytes, mime_type: str) -> None:
    """Refuse an upload that is obviously not worth storing or sending to the model.

    Raises ValueError with a message meant for the user.
    """
    if not image_bytes:
        raise ValueError("The image is empty")
    if normalise_mime(mime_type) not in ALLOWED_IMAGE_TYPES:
        raise ValueError("Only images can be parsed")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("The image is too large — under 8 MB, please")


def build_expense_draft(image_bytes: bytes, mime_type: str) -> ExpenseDraft:
    """Parse an uploaded image into a draft expense.

    Raises ValueError with a message meant for the user when the upload is unusable or the
    model cannot read it.
    """
    validate_image(image_bytes, mime_type)

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
