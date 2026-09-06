"""El envoltorio `{"data": ...}` tiene que llevar realmente el contenido.

`ResponseModel` declara `data: S | list[S]` con S acotado a `CamelCaseModel`. Parametrizarlo
con un tipo que no cumpla esa cota —un `dict`, por ejemplo— no falla en ningún lado: FastAPI
valida el contenido contra `CamelCaseModel`, que no tiene campos, y responde `{"data": []}`
con un 200. El endpoint "anda", devuelve el código correcto, y el cuerpo está vacío.

Se prueba acá, en la suite unitaria, y no solo en integración: este bug se descubrió recién en
CI porque la única cobertura estaba en un test que necesita Postgres.
"""

import ast
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from template.domain.schema_model import ResponseModel
from template.domain.schemas.due_date import DueDateReminderRunResponse

ENTRYPOINTS = pathlib.Path(__file__).resolve().parents[2].parent / "src" / "template" / "entrypoint"


def _serialize(model: ResponseModel) -> dict:
    """Lo que el cliente recibe de verdad, pasando por la validación de FastAPI."""
    app = FastAPI()

    @app.get("/probe", response_model=ResponseModel[DueDateReminderRunResponse])
    def probe():  # pragma: no cover - lo ejecuta el TestClient
        return model

    return TestClient(app).get("/probe").json()


class TestTaskRunResponse:
    def test_the_count_survives_serialization(self):
        assert _serialize(ResponseModel(data=DueDateReminderRunResponse(sent=3))) == {"data": {"sent": 3}}

    def test_zero_is_not_dropped(self):
        """El `sent: 0` de la segunda corrida es la prueba de idempotencia: no puede perderse.

        `CamelCaseModel.model_dump` usa exclude_unset y exclude_none por defecto, que es
        exactamente el tipo de configuración que se come un cero.
        """
        assert _serialize(ResponseModel(data=DueDateReminderRunResponse(sent=0))) == {"data": {"sent": 0}}


def _response_model_args():
    """Cada `ResponseModel[...]` que aparece en los routers, con el texto de su parámetro."""
    for path in sorted(ENTRYPOINTS.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript):
                continue
            if isinstance(node.value, ast.Name) and node.value.id == "ResponseModel":
                yield path.name, node.lineno, ast.unparse(node.slice)


@pytest.mark.parametrize("site", list(_response_model_args()), ids=lambda s: f"{s[0]}:{s[1]}:{s[2]}")
def test_no_router_parameterises_the_envelope_with_a_bare_container(site):
    """`ResponseModel[dict]` y `ResponseModel[list]` devuelven 200 con el cuerpo vacío."""
    filename, lineno, argument = site
    assert argument not in {"dict", "list", "Dict", "Any"}, (
        f"{filename}:{lineno} usa ResponseModel[{argument}]. S está acotado a CamelCaseModel; "
        f"con un contenedor pelado FastAPI responde 200 con data vacía. Definí un esquema."
    )
