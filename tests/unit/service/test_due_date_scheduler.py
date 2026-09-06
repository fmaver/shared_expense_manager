"""El loop duerme hasta el próximo :00, no una hora fija.

Con sleep(3600) la hora de envío depende de cuándo arrancó el proceso, así que cambia después
de cada deploy y "¿a qué hora avisa?" deja de tener respuesta.
"""

from datetime import datetime

import pytest

from template.service_layer.due_date_scheduler import seconds_until_next_hour


@pytest.mark.parametrize(
    "now,expected",
    [
        (datetime(2026, 10, 17, 8, 0, 0), 3600.0),
        (datetime(2026, 10, 17, 8, 59, 0), 60.0),
        (datetime(2026, 10, 17, 8, 30, 30), 1770.0),
        (datetime(2026, 10, 17, 23, 59, 59), 1.0),
    ],
)
def test_it_sleeps_until_the_top_of_the_hour(now, expected):
    assert seconds_until_next_hour(now) == expected


def test_it_never_returns_zero():
    """Devolver 0 en el :00 exacto haría girar el loop sin pausa."""
    assert seconds_until_next_hour(datetime(2026, 10, 17, 8, 0, 0)) > 0
