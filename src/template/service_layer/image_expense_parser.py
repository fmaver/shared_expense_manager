"""Gemini Vision-based parser for expense images (receipts, payment screenshots)."""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Verify this model ID at https://ai.google.dev/gemini-api/docs/models before deployment
GEMINI_MODEL = "gemini-2.5-flash-lite"


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


def parse_image_expense(
    image_bytes: bytes,
    mime_type: str,
    categories: List[str],
    today: Optional[date] = None,
) -> Optional[ParsedImageExpense]:
    """Parse expense details from an image using Gemini Vision.

    Returns ParsedImageExpense on success, or None if the key could not parse
    the image (missing API key, network error, amount not found, etc.).
    """
    if today is None:
        today = date.today()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set — image expense parsing disabled")
        return None

    try:
        client = genai.Client(api_key=api_key)
        prompt = _build_prompt(categories, today)

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                types.Part.from_text(text=prompt),
            ],
        )

        raw = response.text.strip() if response.text else ""
        if raw.startswith("```"):
            raw = "\n".join(line for line in raw.splitlines() if not line.startswith("```")).strip()
        if not raw:
            logger.warning("Image parsing: empty response from Gemini")
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

        installments = max(1, int(data.get("installments", 1)))

        return ParsedImageExpense(
            amount=float(data["amount"]),
            description=str(data.get("description", "Gasto")).strip() or "Gasto",
            category=category,
            expense_date=expense_date,
            payment_type=str(data.get("payment_type", "debit")),
            confidence=str(data.get("confidence", "low")),
            installments=installments,
            currency=str(data.get("currency", "ARS")),
        )

    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Image expense parsing failed: %s", exc)
        return None
