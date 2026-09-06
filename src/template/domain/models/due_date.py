"""La regla que convierte "el 20, cada 2 meses, desde octubre" en fechas concretas.

Vive sola y sin dependencias porque es la parte con más casos borde del feature: el día 31 en
meses que no lo tienen, los ciclos que no son mensuales, y el mes desde el que se cuenta.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DueDateRule:
    """Un vencimiento recurrente: día del mes, cada cuántos meses, y desde qué mes.

    `every_n_months = 1` es el caso mensual, así que no hay dos patrones: hay una fórmula.
    El ancla solo importa cuando N > 1, donde distingue "bimestral desde octubre" de
    "bimestral desde noviembre".
    """

    day_of_month: int
    every_n_months: int
    anchor_year: int
    anchor_month: int

    def occurs_in(self, year: int, month: int) -> bool:
        """True si el ciclo cae en este mes. Nada ocurre antes del mes ancla."""
        offset = (year * 12 + month) - (self.anchor_year * 12 + self.anchor_month)
        if offset < 0:
            return False
        return offset % self.every_n_months == 0

    def occurrence_on(self, year: int, month: int) -> date:
        """La fecha concreta en ese mes, sin preguntar si el ciclo cae ahí.

        El día se recorta al último del mes: un vencimiento cargado el 31 cae el 30 en
        noviembre y el 28 en febrero, en lugar de saltearse esos meses.

        No se corre por fin de semana ni feriado: si la boleta dice 20, la app dice 20.
        Mover la fecha haría que la app muestre un número distinto al del papel.
        """
        last_day = monthrange(year, month)[1]
        return date(year, month, min(self.day_of_month, last_day))

    def next_occurrence(self, on_or_after: date) -> date:
        """La primera ocurrencia en o después de esa fecha.

        "En o después" y no "después": con notify_days_before = 0 el aviso sale el mismo día
        del vencimiento, y ese caso tiene que encontrarse a sí mismo.
        """
        year, month = on_or_after.year, on_or_after.month
        # 14 meses cubre cualquier ciclo de hasta un año más el mes en curso.
        for _ in range(14 + self.every_n_months):
            if self.occurs_in(year, month):
                candidate = self.occurrence_on(year, month)
                if candidate >= on_or_after:
                    return candidate
            month += 1
            if month == 13:
                year, month = year + 1, 1
        raise ValueError(f"No occurrence found after {on_or_after} for {self}")
