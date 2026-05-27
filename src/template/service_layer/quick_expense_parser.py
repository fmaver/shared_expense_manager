"""LLM-based natural language parser for quick expense messages."""

import json
import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ParsedExpense:
    amount: float
    description: str
    category: str
    payer_id: int
    expense_date: date
    payment_type: str  # "debit" or "credit"
    installments: int


def _build_prompt(
    text: str,
    members: List[Dict[str, Any]],
    categories: List[str],
    current_member_id: int,
    today: date,
) -> str:
    from datetime import timedelta  # pylint: disable=import-outside-toplevel

    yesterday = today - timedelta(days=1)
    member_lines = "\n".join(f"  - id={m['id']}, name={m['name']}" for m in members)
    category_list = ", ".join(categories)
    return f"""You are a parser for an Argentine Spanish expense-tracking WhatsApp bot.

The user just sent this message:
"{text}"

Today is {today.isoformat()}.
Yesterday was {yesterday.isoformat()}.
The user sending the message has member_id={current_member_id}.

Group members:
{member_lines}

Available categories: {category_list}

Your job: decide whether this message describes an expense, and if so extract its fields.

Rules:
- "gasté", "pagué", "compré", "fui a", "salí" → payer is the current user (id={current_member_id})
- "pagó <name>", "<name> pagó", "<name> gastó" → payer is the named member; match name case-insensitively
- If no date is mentioned → use today ({today.isoformat()})
- "ayer" → use yesterday ({yesterday.isoformat()})
- "el lunes/martes/..." → most recent past occurrence of that weekday
- If no payment type is mentioned → "debit"
- "con tarjeta", "tarjeta", "crédito", "credito" → "credit"
- If no installments info → 1
- "en X cuotas" → installments = X
- Infer the category from the description using common sense (Argentine context).
  The ONLY valid categories are: {category_list}
  Mapping guide:
  supermercado → groceries: coto, dia, carrefour, jumbo, super, verdulería, panadería, pollería, almacén
  salidas      → eating out or food delivery: restaurant, resto, bar, pizzería, sushi, delivery, pedidos ya, rappi
  auto         → car & transport: nafta, peaje, estacionamiento, mecánico, uber, taxi, remis, seguro auto
  casa         → home expenses: luz, gas, internet, agua, expensas, alquiler, seguro hogar, ferretería
  entretenimiento → leisure: cine, teatro, streaming, spotify, netflix, recital, juego
  shopping     → clothes & goods: ropa, zapatillas, zara, mercadolibre, amazon, electrónica
  viajes       → travel: hotel, vuelo, airbnb, excursión, viaje
  salud        → health: farmacia, médico, doctor, dentista, hospital, óptica
  mascota      → pets: veterinario, pet shop, alimento mascota
  otros        → anything that doesn't fit the above
- The description should be a short noun phrase (2-4 words max), not a full sentence.

Respond with ONLY a JSON object. No markdown, no explanation.

If the message IS an expense:
{{
  "is_expense": true,
  "amount": <number>,
  "description": "<short description>",
  "category": "<one of the available categories>",
  "payer_id": <member id as integer>,
  "date": "<YYYY-MM-DD>",
  "payment_type": "debit" or "credit",
  "installments": <integer, default 1>
}}

If the message is NOT an expense (it's a question, greeting, or unrelated text):
{{"is_expense": false}}"""


def parse_quick_expense(
    text: str,
    members: List[Dict[str, Any]],
    categories: List[str],
    current_member_id: int,
    today: Optional[date] = None,
) -> Optional[ParsedExpense]:
    """Parse a free-form expense message using Claude Haiku.

    Returns a ParsedExpense on success, or None if the message is not an expense
    or if parsing fails for any reason (missing API key, network error, etc.).
    """
    if today is None:
        today = date.today()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — quick expense parsing disabled")
        return None

    try:
        import anthropic  # pylint: disable=import-outside-toplevel

        client = anthropic.Anthropic(api_key=api_key)
        prompt = _build_prompt(text, members, categories, current_member_id, today)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()  # type: ignore[union-attr]
        # Strip markdown code fences the model sometimes adds despite the prompt
        if raw.startswith("```"):
            raw = "\n".join(line for line in raw.splitlines() if not line.startswith("```")).strip()
        if not raw:
            logger.warning("Quick expense parsing failed: empty response from LLM")
            return None
        data: Dict[str, Any] = json.loads(raw)

        if not data.get("is_expense"):
            return None

        return ParsedExpense(
            amount=float(data["amount"]),
            description=str(data["description"]),
            category=str(data["category"]),
            payer_id=int(data["payer_id"]),
            expense_date=date.fromisoformat(str(data["date"])),
            payment_type=str(data.get("payment_type", "debit")),
            installments=int(data.get("installments", 1)),
        )

    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Quick expense parsing failed: %s", exc)
        return None
