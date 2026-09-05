"""Gemini Vision-based parser for expense images (receipts, payment screenshots)."""

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, cast

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Verify this model ID at https://ai.google.dev/gemini-api/docs/models before deployment
GEMINI_MODEL = "gemini-2.5-flash-lite"
# Backup reader for when Gemini is at capacity. Reuses the key the WhatsApp text parser
# already uses, so no new configuration is needed in Render.
CLAUDE_IMAGE_MODEL = "claude-opus-5"
# Claude accepts only these four. Gemini is more permissive — an iPhone photo can arrive as
# image/heic — so a fallback is not always possible, and saying so beats sending a type the
# API will reject.
CLAUDE_SUPPORTED_MEDIA_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")


@dataclass
class ParsedImageExpense:  # pylint: disable=too-many-instance-attributes
    amount: Optional[float]
    description: str
    category: str
    expense_date: date
    payment_type: str  # "debit" | "credit"
    confidence: str = field(default="low")  # "high" | "low"
    installments: int = field(default=1)  # number of cuotas; 1 = single payment
    currency: str = field(default="ARS")  # "ARS" or "USD"


def _build_prompt(categories: List[str], today: date) -> str:
    category_list = ", ".join(categories)
    return f"""You are parsing an expense from a WhatsApp image. The image may be:
- A supermarket or store receipt
- A restaurant bill
- A bank payment notification screenshot (e.g. Mercado Pago, Santander, Galicia, BBVA, Naranja, MODO)
- A purchase confirmation screenshot

Today is {today.isoformat()}. Currency is Argentine Pesos (ARS).

Extract these fields:
- amount: the total amount paid (float). Look for "Total", "TOTAL", "Monto", "Importe". Required.
- description: the REAL merchant or payee name, max 4 words. Strip payment-platform prefixes/noise
  and surface the underlying merchant. Examples:
    "MercPago*Shell" or "MP*Shell" → "Shell" (category: transporte)
    "MercPago*Netflix" → "Netflix" (category: entretenimiento)
    "MercPago*McDonalds" → "McDonald's" (category: comida)
    Transfer to a person or store via Mercado Pago → use the person/store name, not "Mercado Pago"
    CVU/alias transfers → use the recognizable destination name if possible
  General rule: strip payment platform prefixes (MercPago*, MP*) to find the real merchant or payee,
  then use that name to improve category inference too.
- date: transaction date in YYYY-MM-DD format. Use today ({today.isoformat()}) if not visible.
- category: one of {category_list}
- payment_type: "credit" if the image shows installments (cuotas) or a credit card charge; "debit" otherwise
- installments: integer number of cuotas shown in the image (e.g. "9 cuotas sin interés" → 9,
  "en 3 cuotas" → 3). Default 1 if no installments are shown or payment_type is "debit".
- confidence: "high" if amount and merchant are clearly visible; "low" if you guessed any key field
- currency: "USD" if the receipt/screenshot clearly shows amounts in US dollars; "ARS" otherwise (default)

Respond ONLY with a JSON object, no markdown fences, no explanation:
{{
  "amount": <number or null>,
  "description": "<string>",
  "date": "<YYYY-MM-DD>",
  "category": "<category>",
  "payment_type": "debit" or "credit",
  "installments": <integer>,
  "confidence": "high" or "low",
  "currency": "ARS" or "USD"
}}"""


# Gemini answers 503 UNAVAILABLE when the model is busy, and 429 when quota is exhausted.
# google-genai raises these as plain exceptions rather than typed ones, so detection is on the
# message. Kept deliberately narrow: only capacity, never "this image is unreadable".
_CAPACITY_MARKERS = ("503", "unavailable", "overloaded", "high demand", "429", "resource_exhausted")


def _is_capacity_error(exc: Exception) -> bool:
    """True when the provider was too busy, as opposed to the request being wrong."""
    message = str(exc).lower()
    return any(marker in message for marker in _CAPACITY_MARKERS)


def parse_image_expense(
    image_bytes: bytes,
    mime_type: str,
    categories: List[str],
    today: Optional[date] = None,
) -> Optional[ParsedImageExpense]:
    """Parse expense details from an image, with Claude as a backup for Gemini outages.

    Gemini is tried first. If it answers 503/429 — a transient capacity problem rather than
    anything wrong with the picture — the same image is retried on Claude. Every other
    outcome is taken at face value: a missing key, an unreadable image or "no amount here"
    are answers, and paying a second model to reach the same one would be waste.

    Returns None when neither model could read an expense. Never raises: callers show a
    friendly message.
    """
    if today is None:
        today = date.today()

    try:
        return _parse_with_gemini(image_bytes, mime_type, categories, today)
    except Exception as exc:  # pylint: disable=broad-except
        if not _is_capacity_error(exc):
            logger.warning("Image expense parsing failed: %s", exc)
            return None
        logger.warning("Gemini unavailable (%s) — retrying this image on Claude", exc)

    try:
        return _parse_with_claude(image_bytes, mime_type, categories, today)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Claude image fallback also failed: %s", exc)
        return None


def _parse_with_gemini(
    image_bytes: bytes,
    mime_type: str,
    categories: List[str],
    today: date,
) -> Optional[ParsedImageExpense]:
    """Read the image with Gemini Vision.

    Deliberately does not catch: the caller decides whether a failure is a capacity blip worth
    retrying on another model, or a real problem with the image.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set — image expense parsing disabled")
        return None

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            types.Part.from_text(text=_build_prompt(categories, today)),
        ],
    )

    return _to_parsed_expense(response.text.strip() if response.text else "", categories, today)


def _parse_with_claude(
    image_bytes: bytes,
    mime_type: str,
    categories: List[str],
    today: date,
) -> Optional[ParsedImageExpense]:
    """Read the image with Claude when Gemini is unavailable.

    Reuses ANTHROPIC_API_KEY, already configured for the WhatsApp text parser, and the same
    prompt as Gemini so both models are answering exactly the same question.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — no fallback available for image parsing")
        return None

    if mime_type not in CLAUDE_SUPPORTED_MEDIA_TYPES:
        logger.warning("Cannot retry a %s image on Claude — unsupported media type", mime_type)
        return None

    import anthropic  # pylint: disable=import-outside-toplevel

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=CLAUDE_IMAGE_MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            # Narrowed above, so this is one of the four Claude accepts.
                            "media_type": cast(Any, mime_type),
                            "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
                        },
                    },
                    {"type": "text", "text": _build_prompt(categories, today)},
                ],
            }
        ],
    )

    raw = response.content[0].text.strip()  # type: ignore[union-attr]
    return _to_parsed_expense(raw, categories, today)


def _to_parsed_expense(raw: str, categories: List[str], today: date) -> Optional[ParsedImageExpense]:
    """Turn a model's JSON reply into a ParsedImageExpense.

    Shared by both providers so a screenshot cannot be interpreted differently depending on
    which model happened to be available.
    """
    if raw.startswith("```"):
        raw = "\n".join(line for line in raw.splitlines() if not line.startswith("```")).strip()
    if not raw:
        logger.warning("Image parsing: empty response from the model")
        return None

    data: Dict[str, Any] = json.loads(raw)

    if data.get("amount") is None:
        logger.info("Image parsing: amount not found in image")
        return None

    expense_date = today
    if data.get("date"):
        try:
            expense_date = date.fromisoformat(str(data["date"]))
        except ValueError:
            expense_date = today

    category = str(data.get("category", "otros"))
    if category not in categories:
        category = "otros"

    return ParsedImageExpense(
        amount=float(data["amount"]),
        description=str(data.get("description", "Gasto")).strip() or "Gasto",
        category=category,
        expense_date=expense_date,
        payment_type=str(data.get("payment_type", "debit")),
        confidence=str(data.get("confidence", "low")),
        installments=max(1, int(data.get("installments", 1))),
        currency=str(data.get("currency", "ARS")),
    )
