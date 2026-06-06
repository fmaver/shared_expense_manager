"""LLM-based natural language parser for quick expense messages and loans."""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ParsedExpense:  # pylint: disable=too-many-instance-attributes
    amount: float
    description: str
    category: str
    payer_id: int
    expense_date: date
    payment_type: str  # "debit" or "credit"
    installments: int
    is_loan: bool = field(default=False)
    recipient_id: Optional[int] = field(default=None)
    split_strategy: Optional[Dict[str, Any]] = field(default=None)
    is_recurring: bool = field(default=False)


def _build_prompt(
    text: str,
    members: List[Dict[str, Any]],
    categories: List[str],
    current_member_id: int,
    today: date,
) -> str:
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

Your job: decide whether the message is an expense, a loan, or neither.

--- EXPENSE RULES ---
Triggered by: "gasté", "pagué", "compré", "fui a", "salí", or a named member paying.
- "gasté/pagué/compré/fui/salí" → payer is the current user (id={current_member_id})
- "pagó <name>", "<name> pagó/gastó/compró" → payer is the named member
- If no date mentioned → use today ({today.isoformat()})
- "ayer" → use yesterday ({yesterday.isoformat()})
- "el lunes/martes/miércoles/jueves/viernes" → most recent past occurrence of that weekday
- Description: short noun phrase, 2-4 words max.
- Category inference (ONLY use categories from the list above):
  supermercado → groceries: coto, dia, carrefour, jumbo, verdulería, panadería, pollería, almacén, super
  salidas      → eating out / delivery: restaurant, resto, bar, pizzería, sushi, delivery, pedidos ya, rappi
  auto         → car & transport: nafta, peaje, estacionamiento, mecánico, uber, taxi, remis, seguro auto
  casa         → home: luz, gas, internet, agua, expensas, alquiler, seguro hogar, ferretería, limpieza
  entretenimiento → leisure: cine, teatro, streaming, spotify, netflix, recital, juego, cancha
  shopping     → clothes & goods: ropa, zapatillas, zara, mercadolibre, amazon, electrónica, electrodoméstico
  viajes       → travel: hotel, vuelo, airbnb, excursión, viaje, hospedaje
  salud        → health: farmacia, médico, doctor, dentista, hospital, óptica, kinesiología
  mascota      → pets: veterinario, pet shop, alimento mascota, baño mascota
  otros        → fallback for anything not covered above

--- PAYMENT TYPE RULES ---
- Default → "debit"
- Any mention of installments (cuotas) implies credit even without the word "crédito":
  "tarjeta", "crédito", "credito", "cuotas", "en cuotas", "X cuotas", "pague en X" → "credit"
- "en X cuotas" → installments = X; "en cuotas" with no number → installments = 1; default → 1

--- RECURRING EXPENSE RULES ---
If the message mentions that the expense repeats every month (words like "todos los meses",
"mensualmente", "cada mes", "siempre pago", "todos los meses pago", "pago todos los meses"),
set "is_recurring": true in the result. Otherwise omit it or set it to false.

--- SPLIT STRATEGY RULES ---
- If no split is mentioned → omit "split_strategy" from the JSON (the app defaults to equal among all)
- If a split IS explicitly stated, include a "split_strategy" object:
  * Equal among all:    "a partes iguales", "mitad y mitad", "dividimos", "entre todos"
    → {{"type": "equal"}}
  * Equal among subset: "entre X e Y" when only naming a subset of members
    → {{"type": "equal", "participant_ids": [id1, id2]}}
  * Percentage split:   "me corresponde el X%", "X% para mí, Y% para Z"
    → {{"type": "percentage", "percentages": {{"<id1>": pct1, "<id2>": pct2}}}}  (must sum to 100)
  * Exact amounts:      "me corresponden X y a Z Y", "yo pago X y Z paga Y"
    → {{"type": "exact", "amounts": {{"<id1>": amt1, "<id2>": amt2}}}}  (must sum to total)
  * "yo"/"me"/"mi" = current user (id={current_member_id})
  * Use member IDs as string keys in percentages/amounts dicts (JSON requires string keys)

--- LOAN RULES ---
Triggered by: "presté", "le presté", "prestó", "me prestó", "le prestó".
- "le presté a X" / "presté X pesos a X" → lender = current user, borrower = X
- "<name> le prestó a <name2>" / "<name> prestó a <name2>" → lender = name, borrower = name2
- "<name> me prestó" → lender = name, borrower = current user
- Match names case-insensitively against the member list.
- Date rules same as expenses ("ayer", weekday names, default today).
- Description: "préstamo a <borrower name>"

Respond with ONLY a JSON object. No markdown, no explanation.

If the message is a regular EXPENSE:
{{
  "is_expense": true,
  "is_loan": false,
  "amount": <number>,
  "description": "<short description>",
  "category": "<one of: {category_list}>",
  "payer_id": <integer>,
  "date": "<YYYY-MM-DD>",
  "payment_type": "debit" or "credit",
  "installments": <integer, default 1>,
  "split_strategy": <object or omit if default equal>,
  "is_recurring": false
}}

If the message is a LOAN:
{{
  "is_expense": true,
  "is_loan": true,
  "amount": <number>,
  "description": "<e.g. préstamo a Guadi>",
  "payer_id": <lender member id>,
  "recipient_id": <borrower member id>,
  "date": "<YYYY-MM-DD>"
}}

If the message is NOT an expense or loan (greeting, question, unrelated):
{{"is_expense": false}}"""


def parse_quick_expense(
    text: str,
    members: List[Dict[str, Any]],
    categories: List[str],
    current_member_id: int,
    today: Optional[date] = None,
) -> Optional[ParsedExpense]:
    """Parse a free-form expense or loan message using Claude Haiku.

    Returns a ParsedExpense on success, or None if the message is neither an
    expense nor a loan, or if parsing fails (missing API key, network error, etc.).
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
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()  # type: ignore[union-attr]
        if raw.startswith("```"):
            raw = "\n".join(line for line in raw.splitlines() if not line.startswith("```")).strip()
        if not raw:
            logger.warning("Quick expense parsing failed: empty response from LLM")
            return None

        data: Dict[str, Any] = json.loads(raw)

        if not data.get("is_expense"):
            return None

        expense_date = date.fromisoformat(str(data["date"]))

        if data.get("is_loan"):
            return ParsedExpense(
                amount=float(data["amount"]),
                description=str(data.get("description", "préstamo")),
                category="prestamo",
                payer_id=int(data["payer_id"]),
                expense_date=expense_date,
                payment_type="debito",
                installments=1,
                is_loan=True,
                recipient_id=int(data["recipient_id"]) if data.get("recipient_id") is not None else None,
            )

        raw_strategy = data.get("split_strategy") or None
        return ParsedExpense(
            amount=float(data["amount"]),
            description=str(data["description"]),
            category=str(data["category"]),
            payer_id=int(data["payer_id"]),
            expense_date=expense_date,
            payment_type=str(data.get("payment_type", "debit")),
            installments=int(data.get("installments", 1)),
            split_strategy=raw_strategy,
            is_recurring=bool(data.get("is_recurring", False)),
        )

    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Quick expense parsing failed: %s", exc)
        return None
