"""El loop duerme hasta el próximo :00, no una hora fija.

Con sleep(3600) la hora de envío depende de cuándo arrancó el proceso, así que cambia después
de cada deploy y "¿a qué hora avisa?" deja de tener respuesta.
"""

from datetime import datetime
from unittest.mock import patch

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


class TestRunsOnStartup:
    """Arrancar tiene que disparar una corrida, no esperar a la hora en punto siguiente.

    Dormir primero deja el feature inservible en cualquier servicio que se apague: arranca,
    duerme una hora, y lo apagan antes de que el loop haya hecho nada. Correr al arranque
    convierte la dependencia de "el proceso tiene que estar vivo justo a las 9" en "tiene que
    estar vivo en algún momento de la ventana". Es seguro porque el job es idempotente.
    """

    def test_the_first_pass_happens_before_the_first_sleep(self):
        import asyncio

        from template.service_layer import due_date_scheduler as scheduler

        calls = []

        async def fake_run():
            calls.append("run")

        async def fake_sleep(_seconds):
            calls.append("sleep")
            raise asyncio.CancelledError

        with (
            patch.object(scheduler, "_run_once", fake_run),
            patch.object(scheduler.asyncio, "sleep", fake_sleep),
        ):
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(scheduler._loop())

        assert calls == ["run", "sleep"], "corre, después duerme"
