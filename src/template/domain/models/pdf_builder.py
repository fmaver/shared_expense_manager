"""PDF report generator for monthly expense balances.

Uses fpdf2 with FiraSans (Latin/Spanish accents) + NotoEmoji fallback (emoji).
Fonts are vendored under src/template/domain/models/fonts/.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fpdf import FPDF, XPos, YPos

from template.domain.models.category import Category
from template.domain.models.formatters import (
    format_amount_es,
    format_payment_type_es,
    month_name_es,
)
from template.domain.schemas.expense import ExpenseResponse, SplitStrategySchema

# Suppress cosmetic fpdf2/fontTools warnings: emoji glyphs render correctly
# via the NotoEmoji fallback font even though FiraSansBold doesn't contain them.
logging.getLogger("fpdf.output").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)

_FONTS_DIR = Path(__file__).parent / "fonts"

# Colour palette (R, G, B)
_SLATE_700 = (51, 65, 85)
_SLATE_50 = (248, 250, 252)
_WHITE = (255, 255, 255)
_BLACK = (0, 0, 0)
_GREEN_100 = (209, 250, 229)
_GREEN_800 = (22, 101, 52)
_RED_100 = (254, 226, 226)
_RED_800 = (153, 27, 27)
_AMBER_100 = (254, 243, 199)
_AMBER_800 = (146, 64, 14)
_GRAY_100 = (241, 245, 249)
_GRAY_500 = (107, 114, 128)
_GRAY_800 = (31, 41, 55)


def _hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _split_summary(strategy: SplitStrategySchema, member_names: Dict[int, str]) -> str:
    """One-line human-readable split description."""
    if strategy.type == "equal":
        if strategy.participant_ids:
            names = [member_names.get(mid, str(mid)) for mid in strategy.participant_ids]
            return "Partes iguales: " + ", ".join(names)
        return "Partes iguales"
    if strategy.type == "percentage" and strategy.percentages:
        parts = [f"{member_names.get(int(k), k)}: {v:.0f}%" for k, v in strategy.percentages.items()]
        return " | ".join(parts)
    if strategy.type == "exact" and strategy.amounts:
        parts = [f"{member_names.get(int(k), k)}: ${format_amount_es(v)}" for k, v in strategy.amounts.items()]
        return " | ".join(parts)
    return strategy.type.capitalize()


class _ReportPDF(FPDF):
    """Internal FPDF subclass; do not instantiate directly — use `build()`."""

    def __init__(self) -> None:
        super().__init__(unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=15)
        # Register fonts
        self.add_font("Fira", "", str(_FONTS_DIR / "FiraSans-Regular.ttf"))
        self.add_font("Fira", "B", str(_FONTS_DIR / "FiraSans-Bold.ttf"))
        self.add_font("Emoji", "", str(_FONTS_DIR / "NotoEmoji-Regular.ttf"))
        self.set_fallback_fonts(["Emoji"])

    # ------------------------------------------------------------------
    # FPDF hooks
    # ------------------------------------------------------------------

    def header(self) -> None:
        pass  # drawn manually in build() so we control position precisely

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Fira", "", 8)
        self.set_text_color(*_GRAY_500)
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        self.cell(0, 5, f"Generado el {now}", align="L", new_x=XPos.LEFT)
        self.cell(0, 5, f"Página {self.page_no()}/{{nb}}", align="R")
        self.set_text_color(*_BLACK)

    # ------------------------------------------------------------------
    # Primitive drawing helpers
    # ------------------------------------------------------------------

    def _fill_rect(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, x: float, y: float, w: float, h: float, color: tuple
    ) -> None:
        self.set_fill_color(*color)
        self.rect(x, y, w, h, "F")

    def _section_title(self, title: str, y_gap: float = 4) -> None:
        self.ln(y_gap)
        self.set_font("Fira", "B", 13)
        self.set_text_color(*_SLATE_700)
        self.cell(0, 8, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        # thin underline
        self.set_draw_color(*_SLATE_700)
        lm = self.l_margin
        self.line(lm, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)
        self.set_text_color(*_BLACK)

    # ------------------------------------------------------------------
    # Header band
    # ------------------------------------------------------------------

    def _draw_header(self, year: int, month: int, is_settled: bool) -> None:
        band_h = 22
        self._fill_rect(0, 0, self.w, band_h, _SLATE_700)
        self.set_text_color(*_WHITE)

        # Left: title
        self.set_font("Fira", "B", 15)
        self.set_xy(self.l_margin, 6)
        self.cell(100, 10, "📊 Reporte Mensual de Gastos", align="L")

        # Right: month/year
        month_label = f"{month_name_es(month)} {year}"
        self.set_font("Fira", "", 12)
        self.set_xy(self.w - self.r_margin - 50, 6)
        self.cell(50, 10, month_label, align="R")

        # Status pill
        pill_text = "✅ Cerrado" if is_settled else "🟡 Abierto"
        pill_bg = _GREEN_100 if is_settled else _AMBER_100
        pill_fg = _GREEN_800 if is_settled else _AMBER_800
        pill_w = 28
        pill_x = self.w - self.r_margin - pill_w
        pill_y = band_h + 3
        self._fill_rect(pill_x, pill_y, pill_w, 8, pill_bg)
        self.set_text_color(*pill_fg)
        self.set_font("Fira", "B", 8)
        self.set_xy(pill_x, pill_y)
        self.cell(pill_w, 8, pill_text, align="C")

        self.set_text_color(*_BLACK)
        self.set_y(band_h + 14)

    # ------------------------------------------------------------------
    # Summary cards
    # ------------------------------------------------------------------

    def _draw_summary_cards(self, total: float, member_count: int) -> None:
        card_h = 16
        margin = self.l_margin
        usable_w = self.w - 2 * margin
        card_w = (usable_w - 8) / 2  # two cards, 8mm gap

        cards = [
            ("💰 Total gastado", f"${format_amount_es(total)}", _SLATE_50, _SLATE_700),
            ("👥 Miembros", str(member_count), _SLATE_50, _SLATE_700),
        ]

        y = self.get_y()
        for i, (label, value, bg, fg) in enumerate(cards):
            x = margin + i * (card_w + 8)
            self._fill_rect(x, y, card_w, card_h, bg)
            self.set_draw_color(*_GRAY_500)
            self.rect(x, y, card_w, card_h, "D")
            # label
            self.set_font("Fira", "", 7)
            self.set_text_color(*_GRAY_500)
            self.set_xy(x, y + 2)
            self.cell(card_w, 4, label, align="C")
            # value
            self.set_font("Fira", "B", 11)
            self.set_text_color(*fg)
            self.set_xy(x, y + 7)
            self.cell(card_w, 6, value, align="C")

        self.set_text_color(*_BLACK)
        self.set_y(y + card_h + 2)

    # ------------------------------------------------------------------
    # Balances table
    # ------------------------------------------------------------------

    def _draw_balances(self, balances: Dict[str, float], member_names: Dict[int, str]) -> None:
        self._section_title("📈 Balances")

        col_name_w = 90
        col_bal_w = 40
        row_h = 8
        margin = self.l_margin

        # Header
        self._fill_rect(margin, self.get_y(), col_name_w + col_bal_w, row_h, _SLATE_700)
        self.set_text_color(*_WHITE)
        self.set_font("Fira", "B", 9)
        self.set_xy(margin, self.get_y())
        self.cell(col_name_w, row_h, "Miembro", border=0, align="L")
        self.cell(col_bal_w, row_h, "Balance", border=0, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*_BLACK)

        for member_id_str, balance in sorted(balances.items(), key=lambda x: float(x[1]), reverse=True):
            member_name = member_names.get(int(member_id_str), f"Miembro {member_id_str}")
            if balance > 0.005:
                row_bg = _GREEN_100
                bal_color = _GREEN_800
                bal_text = f"+${format_amount_es(balance)}"
            elif balance < -0.005:
                row_bg = _RED_100
                bal_color = _RED_800
                bal_text = f"-${format_amount_es(abs(balance))}"
            else:
                row_bg = _GRAY_100
                bal_color = _GRAY_500
                bal_text = "$0,00"

            y = self.get_y()
            self._fill_rect(margin, y, col_name_w + col_bal_w, row_h, row_bg)
            self.set_font("Fira", "", 9)
            self.set_text_color(*_GRAY_800)
            self.set_xy(margin, y)
            self.cell(col_name_w, row_h, f"  {member_name}", border=0, align="L")
            self.set_text_color(*bal_color)
            self.set_font("Fira", "B", 9)
            self.cell(col_bal_w, row_h, bal_text, border=0, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_text_color(*_BLACK)

    # ------------------------------------------------------------------
    # Expenses table
    # ------------------------------------------------------------------

    def _draw_expenses(  # pylint: disable=too-many-locals
        self, expenses: List[ExpenseResponse], member_names: Dict[int, str]
    ) -> None:
        self._section_title("🧾 Gastos del mes")

        margin = self.l_margin
        # Use 180 mm — leaves a comfortable 10 mm safety margin on A4 (usable = 190 mm)
        # so that slight font-metric differences never push the last column off the page.
        usable = 180.0

        # Column widths (total = 180 mm)
        # Tipo needs room for "Crédito (12 cuotas)" = 18 chars at 7 pt ≈ 30 mm.
        cols = [
            ("Fecha", 20, "C"),
            ("Descripción", 44, "L"),
            ("Categoría", 26, "L"),
            ("Pagador", 22, "L"),
            ("Tipo", 32, "L"),
            ("División", 16, "L"),
            ("Monto", 20, "R"),
        ]

        row_h = 7

        # Table header row
        self._fill_rect(margin, self.get_y(), usable, row_h, _SLATE_700)
        self.set_text_color(*_WHITE)
        self.set_font("Fira", "B", 7)
        self.set_xy(margin, self.get_y())
        for col_label, col_w, col_align in cols:
            self.cell(col_w, row_h, col_label, border=0, align=col_align)
        self.ln(row_h)
        self.set_text_color(*_BLACK)

        # Sort ascending by date
        sorted_expenses = sorted(expenses, key=lambda e: e.date)

        for idx, expense in enumerate(sorted_expenses):
            if self.get_y() > self.h - self.b_margin - row_h:
                self.add_page()

            row_bg = _SLATE_50 if idx % 2 == 0 else _WHITE
            y = self.get_y()
            self._fill_rect(margin, y, usable, row_h, row_bg)

            category_label = f"{expense.category.capitalize()} {Category.get_category_emoji(expense.category)}"
            payer_name = member_names.get(expense.payer_id, str(expense.payer_id))
            tipo = format_payment_type_es(expense.payment_type, expense.installments)
            division = _split_summary(expense.split_strategy, member_names)
            date_str = expense.date.strftime("%d/%m/%Y")
            amount_str = f"${format_amount_es(expense.amount)}"

            row_data = [
                (date_str, 20, "C"),
                (expense.description, 44, "L"),
                (category_label, 26, "L"),
                (payer_name, 22, "L"),
                (tipo, 32, "L"),
                (division, 16, "L"),
                (amount_str, 20, "R"),
            ]

            self.set_font("Fira", "", 7)
            self.set_text_color(*_GRAY_800)
            self.set_xy(margin, y)
            for text, w, align in row_data:
                # Estimate max chars at 7 pt: ~1.8 mm per character average
                max_chars = int(w / 1.8)
                display = text if len(text) <= max_chars else text[: max_chars - 1] + "…"
                self.cell(w, row_h, display, border=0, align=align)
            self.ln(row_h)

        self.set_text_color(*_BLACK)

        # Separator + total
        self.ln(1)
        self.set_draw_color(*_SLATE_700)
        self.line(margin, self.get_y(), margin + usable, self.get_y())
        self.ln(2)

        total = sum(e.amount for e in expenses)
        self.set_font("Fira", "B", 10)
        self.set_text_color(*_SLATE_700)
        self.cell(0, 6, f"Total del mes: ${format_amount_es(total)}", align="R")
        self.set_text_color(*_BLACK)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_monthly_report(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    expenses: List[ExpenseResponse],
    balances: Dict[str, float],
    member_names: Dict[int, str],
    year: int,
    month: int,
    is_settled: bool = False,
) -> bytes:
    """Generate the monthly PDF report and return it as raw bytes."""
    pdf = _ReportPDF()
    pdf.alias_nb_pages()
    pdf.add_page()

    pdf._draw_header(year, month, is_settled)  # pylint: disable=protected-access

    total = sum(e.amount for e in expenses)
    pdf._draw_summary_cards(total, len(member_names))  # pylint: disable=protected-access

    pdf._draw_balances(balances, member_names)  # pylint: disable=protected-access

    pdf.ln(4)
    pdf._draw_expenses(expenses, member_names)  # pylint: disable=protected-access

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Legacy / chatbot shim — keeps the old call site in whatsapp_service.py working
# ---------------------------------------------------------------------------


class ExpensePDF:
    """Thin wrapper that preserves the original generate_expense_report() call signature.

    The chatbot constructs ``ExpensePDF(storage_path=...)`` and calls
    ``generate_expense_report(expenses, balances, filename, member_names)``
    which writes a PDF to disk and returns the file path.
    """

    def __init__(self, storage_path: str = "/tmp/storage") -> None:
        self.storage_path = storage_path
        os.makedirs(self.storage_path, exist_ok=True)

    def generate_expense_report(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        expenses: List[ExpenseResponse],
        monthly_balance_dict: Dict[str, float],
        filename: str,
        membars_names_dict: Dict[int, str],
        year: Optional[int] = None,
        month: Optional[int] = None,
        is_settled: bool = False,
    ) -> str:
        """Generate a PDF and write it to ``storage_path/filename``. Returns the file path."""
        # Infer year/month from the first expense date when not supplied
        if year is None or month is None:
            if expenses:
                year = expenses[0].date.year
                month = expenses[0].date.month
            else:
                now = datetime.now()
                year, month = now.year, now.month

        assert year is not None and month is not None
        pdf_bytes = build_monthly_report(
            expenses=expenses,
            balances=monthly_balance_dict,
            member_names=membars_names_dict,
            year=year,
            month=month,
            is_settled=is_settled,
        )

        file_path = os.path.join(self.storage_path, filename)
        with open(file_path, "wb") as f:
            f.write(pdf_bytes)
        return file_path
