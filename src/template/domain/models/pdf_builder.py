"""PDF Builder"""
import os
from typing import Dict, List

from fpdf import FPDF

from template.domain.schemas.expense import ExpenseResponse


# Clase para manejar el PDF y generar el reporte
class ExpensePDF(FPDF):
    def __init__(self, storage_path: str = "/app/storage"):
        super().__init__()
        self.storage_path = storage_path
        os.makedirs(self.storage_path, exist_ok=True)

    def header(self):
        self.set_font("Arial", "B", 12)
        self.cell(0, 10, "Reporte de Expensas", border=False, ln=True, align="C")
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.cell(0, 10, f"Pagina {self.page_no()}", align="C")

    # pylint: disable=too-many-locals
    def generate_expense_report(
        self,
        expenses: List[ExpenseResponse],
        monthly_balance_dict: Dict[str, float],
        filename: str,
        membars_names_dict: Dict[int, str],
    ):
        """generate expense report"""
        file_path = os.path.join(self.storage_path, filename)

        self.set_auto_page_break(auto=True, margin=15)
        self.add_page()

        # Título
        self.set_font("Arial", "B", 14)
        self.cell(0, 10, "Detalles de Expensas", ln=True, align="L")
        self.ln(5)

        # Tabla de Expensas
        self.set_font("Arial", "", 11)
        # Ancho de las columnas
        col_widths = [50, 23, 22, 25, 18, 17, 30]
        headers = ["Descripción", "Monto", "Fecha", "Categoría", "Pagador", "Pago", "Estrategia"]

        # Render headers -> Encabezados
        for i, header in enumerate(headers):
            self.cell(col_widths[i], 10, header, border=1, align="C")
        self.ln()

        # Render rows -> Filas
        for expense in expenses:
            member_name = membars_names_dict[expense.payer_id]
            strategy: str = expense.split_strategy.type
            strategy_dict = None
            if expense.split_strategy.percentages:
                strategy_dict = {membars_names_dict[k]: v for k, v in expense.split_strategy.percentages.items()}
            strategy = strategy + " " + str(strategy_dict) if strategy_dict else strategy
            strategy = strategy.replace("{", " ").replace("}", " ").replace(",", " ").replace("'", "")

            # Contenidos de las celdas
            row_data = [
                expense.description,
                f"${expense.amount:.2f}",
                expense.date.strftime("%Y-%m-%d"),
                expense.category,
                member_name,
                expense.payment_type,
                strategy,
            ]
            # Calculate maximum row height
            line_heights = [self.get_string_width(row_data[i]) // col_widths[i] + 1 for i in range(len(row_data))]
            max_height = int(max(line_heights)) ** 2 + 3

            # Draw cells
            x_start = self.get_x()
            y_start = self.get_y()

            for i, content in enumerate(row_data):
                if self.get_string_width(row_data[i]) > col_widths[i]:
                    self.multi_cell(col_widths[i], max_height / line_heights[i], content, border=1, align="C")
                    x_current = x_start + col_widths[i]  # Position for next cell
                    self.set_xy(x_current, y_start)
                else:
                    self.cell(col_widths[i], max_height, content, border=1, align="C")

            # Move to next row
            self.ln(max_height)

        # Balance Final
        self.ln(10)
        self.set_font("Arial", "B", 14)
        self.cell(0, 10, "Balance Mensual Final", ln=True, align="L")
        self.ln(5)
        self.set_font("Arial", "", 12)
        for member, balance in monthly_balance_dict.items():
            member_name = membars_names_dict[int(member)]
            self.cell(0, 10, f"{member_name}: ${balance:.2f}", ln=True)

        self.output(file_path)
        return file_path
