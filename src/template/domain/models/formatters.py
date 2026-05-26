"""Shared formatting helpers for amounts, dates, categories, and payment types.

Used by both the WhatsApp chatbot (whatsapp_service.py) and the PDF generator
(pdf_builder.py) so the two outputs stay in sync.
"""

from datetime import datetime
from typing import Any

from template.domain.models.category import Category

SPANISH_MONTHS = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}


def format_amount_es(amount: float) -> str:
    """Format a monetary amount in Argentine style: 1.234,56."""
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_date_es(iso: str) -> str:
    """Convert a YYYY-MM-DD ISO string to DD/MM/YYYY for display."""
    try:
        d = datetime.strptime(iso, "%Y-%m-%d").date()
        return d.strftime("%d/%m/%Y")
    except ValueError:
        return iso


def format_payment_type_es(payment_type: str, installments: int) -> str:
    """Render payment type in Spanish."""
    if payment_type in ("credito", "crédito", "credit"):
        if installments <= 1:
            return "Crédito (1 cuota)"
        return f"Crédito ({installments} cuotas)"
    return "Débito"


def format_category_es(name: str) -> str:
    """Render category name with its emoji."""
    if name == "prestamo":
        return "Préstamo 💰"
    emoji = Category.get_category_emoji(name)
    label = name.capitalize()
    return f"{label} {emoji}" if emoji else label


def format_member_name_es(member_id: Any, member_service: Any) -> str:
    """Return member name; falls back to 'Desconocido' on missing records."""
    name = member_service.get_member_name_by_id(member_id)
    return name if name else "Desconocido"


def month_name_es(month: int) -> str:
    """Return the Spanish month name for a numeric month (1-12)."""
    return SPANISH_MONTHS.get(month, str(month))
