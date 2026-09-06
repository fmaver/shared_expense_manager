"""El disparo manual del job.

Existe para poder probar el feature sin esperar un día, y como salida de emergencia si el loop
interno falla. No usa JWT porque no hay usuario detrás: lo protege un secreto compartido.
"""

import os
from unittest.mock import patch


def test_without_a_configured_secret_the_endpoint_does_not_exist(client):
    """404 y no 401: un endpoint sin proteger no debe anunciar que está ahí."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TASK_SECRET", None)
        response = client.post("/api/v1/tasks/due-date-reminders")
    assert response.status_code == 404


def test_the_wrong_secret_is_rejected(client):
    with patch.dict(os.environ, {"TASK_SECRET": "correcto"}):
        response = client.post("/api/v1/tasks/due-date-reminders", headers={"X-Task-Secret": "incorrecto"})
    assert response.status_code == 401


def test_the_right_secret_runs_the_job(client):
    with patch.dict(os.environ, {"TASK_SECRET": "correcto"}):
        response = client.post("/api/v1/tasks/due-date-reminders", headers={"X-Task-Secret": "correcto"})
    assert response.status_code == 200
    assert "sent" in response.json()["data"]
