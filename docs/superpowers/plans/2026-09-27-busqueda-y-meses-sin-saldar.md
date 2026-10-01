# Búsqueda de gastos y meses sin saldar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Buscar gastos por texto, monto o pagador en tres alcances (todo, un grupo, un mes) y marcar en el selector de mes los meses pasados sin saldar.

**Architecture:** Backend: un endpoint de búsqueda (`GET /api/v1/search/expenses`) que filtra en SQL sobre `expenses` y `recurring_personal_expense_instances`, limitado a los grupos del usuario, y un endpoint `GET /groups/{id}/shares/unsettled` sobre `get_all_monthly_shares`. La lógica de parseo y de "mes sin saldar" son funciones puras con tests unitarios. Front: un overlay de búsqueda montado una vez en `AppShell` (se abre desde las lupas y ⌘K), la lupa del mes filtra en el cliente con una función espejo de la del backend, y `MonthPager` pide los meses sin saldar al abrirse.

**Tech Stack:** FastAPI + SQLAlchemy 2 + Pydantic v2 (backend, paquete `template`); React 18 + TypeScript + Tailwind + react-i18next (front).

**Spec:** `docs/superpowers/specs/2026-09-27-busqueda-y-meses-sin-saldar-design.md` (en este repo).

## Global Constraints

- Imports del backend: `from template.xxx import ...`. Routers nunca tocan SQLAlchemy: van por servicios con `Depends`.
- Toda respuesta: `ResponseModel[T]` → `{ "data": ... }`. Esquemas `CamelCaseModel` (camelCase en el cable).
- Money es `float`. Tolerancia de monto exacto: ±0,005.
- Categorías excluidas de la búsqueda: `balance`, `prestamo`.
- Tope: 50 resultados, `hasMore` si había más. Mínimo: 2 caracteres, salvo que sea un número.
- Mes sin saldar: anterior al mes actual, `is_settled == False`, algún `abs(saldo) > 0.01`. Sólo grupos `regular`.
- Acentos: mismo mapeo en SQL, en Python y en el front: `ACCENTS_FROM = "áàâäéèêëíìîïóòôöúùûüñç"`, `ACCENTS_TO = "aaaaeeeeiiiioooouuuunc"`, aplicado después de pasar a minúsculas.
- Las descripciones de cuotas ya vienen con el sufijo `" (k/N)"` desde la expansión: el front no lo agrega.
- Sin migración.
- Front: i18n es/en para todo texto nuevo, claro y oscuro, `tabular-nums` en montos, `npx tsc -b` vía `npm run typecheck:ratchet` y `npm run lint` por tarea.
- Commits con `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Rama backend `feature/expense-search` (ya creada); rama front `feature/expense-search` desde `origin/main` actualizado.
- **Nunca** correr `make integration` contra staging ni prod: los tests borran todas las tablas. Ver Task 4.

## Review Focus

1. **Grupo ajeno.** Un gasto de un grupo donde el usuario no está nunca aparece, ni con `groupId` de ese grupo (403). Test en Task 3.
2. **Comodines en la búsqueda.** Escribir `%` o `_` no tiene que traer todo: se escapan en el `LIKE`. Test en Task 3.
3. **Número con formato local.** `24.000` y `24000,50` se leen como 24000 y 24000,5; `1.5` como 1,5. Test en Task 1.
4. **Respuestas viejas que llegan tarde.** Tipear rápido "ca" → "cafe" no puede mostrar al final los resultados de "ca". Se prueba en Task 8 (descarte por id de pedido).
5. **Grupo archivado.** Sus gastos siguen apareciendo en la búsqueda general. Test en Task 3.

---

## Archivos

**Backend (`shared_expense_manager/`)**
- Create `src/template/service_layer/search_query.py` — `normalize`, `parse_amount`, `parse_query`, `ParsedQuery` (puro).
- Create `src/template/service_layer/unsettled_months.py` — `unsettled_periods` (puro).
- Create `src/template/domain/schemas/search.py` — `ExpenseSearchResult`, `ExpenseSearchResponse`, `UnsettledMonth`.
- Modify `src/template/adapters/repositories.py` — `SearchRepository` (nuevo, al final) y `GroupRepository.list_ids_for_member_all`.
- Create `src/template/service_layer/search_service.py` — `SearchService`.
- Modify `src/template/dependencies.py` — `get_search_service`.
- Create `src/template/entrypoint/search.py`; modify `src/template/router.py`.
- Modify `src/template/entrypoint/monthly_share.py` — ruta `/unsettled`.
- Tests: `tests/unit/service/test_search_query.py`, `tests/unit/service/test_unsettled_months.py`, `tests/integration/search/test_search_router.py`, `tests/integration/expense/test_unsettled_months_router.py`; modify `tests/integration/conftest.py` (limpiar tablas de fijos personales).
- Docs: `CLAUDE.md` (este repo y el raíz del monorepo): API surface.

**Front (`shared_expense_front/`)**
- Create `src/utils/search.ts` — `normalize`, `parseQuery`, `matchesQuery` (espejo del backend).
- Create `src/api/search.ts`; modify `src/api/shares.ts` (`getUnsettledMonths`), `src/types/expense.ts`.
- Create `src/hooks/useExpenseSearch.ts`, `src/contexts/SearchContext.tsx`, `src/components/search/SearchOverlay.tsx`, `src/components/search/SearchResultRow.tsx`.
- Modify `ExpenseListHeader.tsx` (lupa del mes), `MonthPager.tsx` (meses sin saldar), `AppShell.tsx`, `App.tsx`, `GroupLayout.tsx`, `PersonalDashboard.tsx`, `MobileHeader.tsx`, `ExpensesDashboard.tsx`, `config/features.ts`, i18n.
- Delete `src/pages/SearchPage.tsx`.

---

## Task 1: Parseo de la búsqueda (backend, puro)

**Files:**
- Create: `src/template/service_layer/search_query.py`
- Test: `tests/unit/service/test_search_query.py`

**Interfaces:**
- Produces: `ACCENTS_FROM: str`, `ACCENTS_TO: str`, `normalize(text: str) -> str`, `parse_amount(text: str) -> Optional[float]`, `@dataclass(frozen=True) ParsedQuery(terms: tuple[str, ...], amount: Optional[float])`, `parse_query(q: str) -> Optional[ParsedQuery]`.

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for the search query parser — no DB."""

import pytest

from template.service_layer.search_query import ParsedQuery, normalize, parse_amount, parse_query


def test_normalize_lowercases_and_strips_accents():
    assert normalize("Café Ñandú ÁRBOL") == "cafe nandu arbol"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("24000", 24000.0),
        ("24.000", 24000.0),
        ("24000,50", 24000.5),
        ("24.000,50", 24000.5),
        ("1.234.567", 1234567.0),
        ("1.5", 1.5),
        ("1.50", 1.5),
        ("0", 0.0),
        ("cena", None),
        ("24k", None),
        ("", None),
        ("1.2345", None),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_parse_query_splits_words_and_normalizes():
    assert parse_query("  Cena   en el Centro ") == ParsedQuery(terms=("cena", "en", "el", "centro"), amount=None)


def test_parse_query_number_keeps_text_term_and_amount():
    assert parse_query("24.000") == ParsedQuery(terms=("24.000",), amount=24000.0)


def test_parse_query_too_short_returns_none():
    assert parse_query("a") is None
    assert parse_query("   ") is None


def test_parse_query_single_digit_number_is_allowed():
    assert parse_query("5") == ParsedQuery(terms=("5",), amount=5.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/unit/service/test_search_query.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'template.service_layer.search_query'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Parsing of a free-text expense search: words, and an amount when the query is a number.

Pure functions, no DB. The accent mapping is shared with the SQL `translate()` in
`SearchRepository` and with `src/utils/search.ts` in the front, so the three agree on what
"cafe" matches.
"""

import re
from dataclasses import dataclass
from typing import Optional

ACCENTS_FROM = "áàâäéèêëíìîïóòôöúùûüñç"
ACCENTS_TO = "aaaaeeeeiiiioooouuuunc"
_ACCENT_TABLE = str.maketrans(ACCENTS_FROM, ACCENTS_TO)

# es-AR: dots group thousands, a comma marks decimals. A lone dot with 1-2 decimals is also read
# as a decimal point, for keyboards that only offer "." ("1.5").
_THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+(,\d{1,2})?$")
_PLAIN = re.compile(r"^\d+(,\d{1,2})?$")
_DOT_DECIMAL = re.compile(r"^\d+\.\d{1,2}$")

MIN_TEXT_LENGTH = 2


def normalize(text: str) -> str:
    """Lowercase and strip the accents that matter in Spanish."""
    return text.lower().translate(_ACCENT_TABLE)


def parse_amount(text: str) -> Optional[float]:
    """Read `text` as an amount, or None when it is not a number."""
    value = text.strip()
    if _THOUSANDS.match(value) or _PLAIN.match(value):
        return float(value.replace(".", "").replace(",", "."))
    if _DOT_DECIMAL.match(value):
        return float(value)
    return None


@dataclass(frozen=True)
class ParsedQuery:
    """Every term must match; `amount` also matches expenses of exactly that amount."""

    terms: tuple[str, ...]
    amount: Optional[float]


def parse_query(q: str) -> Optional[ParsedQuery]:
    """Split a query into normalized words. None when there is nothing worth searching."""
    stripped = q.strip()
    amount = parse_amount(stripped)
    if amount is None and len(stripped) < MIN_TEXT_LENGTH:
        return None
    terms = tuple(t for t in normalize(stripped).split() if t)
    if not terms:
        return None
    return ParsedQuery(terms=terms, amount=amount)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/unit/service/test_search_query.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
git add src/template/service_layer/search_query.py tests/unit/service/test_search_query.py
git commit -m "feat(search): parseo de la búsqueda — palabras, acentos y monto"
```

---

## Task 2: Meses sin saldar (backend)

**Files:**
- Create: `src/template/service_layer/unsettled_months.py`
- Create: `src/template/domain/schemas/search.py` (sólo `UnsettledMonth` en esta tarea; Task 3 agrega el resto)
- Modify: `src/template/entrypoint/monthly_share.py` (ruta nueva, antes de `/{year}/{month}`)
- Test: `tests/unit/service/test_unsettled_months.py`, `tests/integration/expense/test_unsettled_months_router.py`

**Interfaces:**
- Consumes: `GroupRepository.get(group_id) -> Optional[Group]` (`group.group_type: GroupType`), `GroupRepository.is_member(group_id, member_id) -> bool`, `SQLAlchemyExpenseRepository.get_all_monthly_shares(group_id) -> Dict[str, MonthlyShare]` (`share.year`, `share.month`, `share.is_settled`, `share.balances: Dict[str, float]`).
- Produces: `unsettled_periods(shares: Iterable[MonthlyShare], today: date) -> list[tuple[int, int]]`; `UnsettledMonth(year: int, month: int)`; `GET /api/v1/groups/{group_id}/shares/unsettled -> ResponseModel[list[UnsettledMonth]]`.

- [ ] **Step 1: Write the failing unit test**

```python
"""Unit tests for picking the past months that were left unsettled."""

from datetime import date

from template.domain.models.models import MonthlyShare
from template.service_layer.unsettled_months import unsettled_periods


def _share(year, month, balances, settled=False):
    share = MonthlyShare(year, month, group_id=1)
    share.balances = balances
    if settled:
        share.settle()
    return share


TODAY = date(2026, 9, 27)


def test_past_unsettled_month_with_balance_is_listed():
    shares = [_share(2026, 7, {"1": 500.0, "2": -500.0})]
    assert unsettled_periods(shares, TODAY) == [(2026, 7)]


def test_current_and_future_months_are_never_listed():
    shares = [_share(2026, 9, {"1": 10.0, "2": -10.0}), _share(2026, 11, {"1": 10.0, "2": -10.0})]
    assert unsettled_periods(shares, TODAY) == []


def test_settled_month_is_not_listed():
    assert unsettled_periods([_share(2026, 6, {"1": 10.0, "2": -10.0}, settled=True)], TODAY) == []


def test_all_square_month_is_not_listed():
    assert unsettled_periods([_share(2026, 5, {"1": 0.004, "2": -0.004})], TODAY) == []


def test_sorted_oldest_first_across_years():
    shares = [_share(2026, 3, {"1": 5.0}), _share(2025, 12, {"1": -5.0}), _share(2026, 8, {"2": 1.0})]
    assert unsettled_periods(shares, TODAY) == [(2025, 12), (2026, 3), (2026, 8)]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `poetry run pytest tests/unit/service/test_unsettled_months.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the pure function**

```python
"""Which past months of a group were left unsettled.

A month counts when it is before the current month, not settled, and someone still has a
balance. The current month is open by definition and future months exist only because of
installments, so neither is something that "slipped through".
"""

from datetime import date
from typing import Iterable

from template.domain.models.models import MonthlyShare

BALANCE_EPSILON = 0.01


def unsettled_periods(shares: Iterable[MonthlyShare], today: date) -> list[tuple[int, int]]:
    """(year, month) of every past, unsettled month with a non-zero balance, oldest first."""
    current = (today.year, today.month)
    periods = [
        (share.year, share.month)
        for share in shares
        if (share.year, share.month) < current
        and not share.is_settled
        and any(abs(value) > BALANCE_EPSILON for value in (share.balances or {}).values())
    ]
    return sorted(periods)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `poetry run pytest tests/unit/service/test_unsettled_months.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing integration test**

`tests/integration/expense/test_unsettled_months_router.py`:

```python
"""Integration tests for GET /groups/{id}/shares/unsettled."""

from datetime import date


def _expense(payer_id, when: date, amount=1000.0):
    return {
        "description": "super",
        "amount": amount,
        "date": when.isoformat(),
        "category": {"name": "comida"},
        "payerId": payer_id,
        "paymentType": "debit",
        "installments": 1,
        "splitStrategy": {"type": "equal"},
    }


def _add_member(client, auth_headers, group_id):
    r = client.post(f"/api/v1/groups/{group_id}/members", json={"name": "Guada"}, headers=auth_headers)
    assert r.status_code in (200, 201), r.text


def _months_ago(n: int) -> date:
    today = date.today()
    total = today.year * 12 + (today.month - 1) - n
    return date(total // 12, total % 12 + 1, 10)


def test_unsettled_lists_past_month_with_balance(client, auth_headers, primary_member_id, primary_group_id):
    _add_member(client, auth_headers, primary_group_id)
    past = _months_ago(2)
    r = client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/", json=_expense(primary_member_id, past), headers=auth_headers
    )
    assert r.status_code == 201, r.text
    # current month also has a balance, and must not be listed
    client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/",
        json=_expense(primary_member_id, date.today()),
        headers=auth_headers,
    )

    r = client.get(f"/api/v1/groups/{primary_group_id}/shares/unsettled", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"] == [{"year": past.year, "month": past.month}]


def test_unsettled_skips_settled_month(client, auth_headers, primary_member_id, primary_group_id):
    _add_member(client, auth_headers, primary_group_id)
    past = _months_ago(1)
    client.post(
        f"/api/v1/groups/{primary_group_id}/expenses/", json=_expense(primary_member_id, past), headers=auth_headers
    )
    r = client.post(
        f"/api/v1/groups/{primary_group_id}/shares/settle/{past.year}/{past.month:02d}", headers=auth_headers
    )
    assert r.status_code == 200, r.text

    r = client.get(f"/api/v1/groups/{primary_group_id}/shares/unsettled", headers=auth_headers)
    assert r.json()["data"] == []


def test_unsettled_requires_membership(client, auth_headers, primary_group_id):
    r = client.post(
        "/api/v1/auth/register",
        json={"name": "Otro", "telephone": "5499911112222", "email": "otro@example.com", "password": "secret123"},
    )
    assert r.status_code == 200, r.text
    token = client.post(
        "/api/v1/auth/token", data={"username": "otro@example.com", "password": "secret123"}
    ).json()["access_token"]

    r = client.get(
        f"/api/v1/groups/{primary_group_id}/shares/unsettled", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403
```

- [ ] **Step 6: Add the schema and the route**

In `src/template/domain/schemas/search.py`:

```python
"""Search and unsettled-month response schemas."""

from template.domain.schema_model import CamelCaseModel


class UnsettledMonth(CamelCaseModel):
    """A past month of a group that was left unsettled."""

    year: int
    month: int
```

In `src/template/entrypoint/monthly_share.py`, directly **above** the comment
`# Literal routes must be declared before /{year}/{month}...`, add (imports at the top: `from datetime import date`
is already importable via `datetime`; add `from template.domain.models.group import GroupType`,
`from template.domain.schemas.search import UnsettledMonth`,
`from template.service_layer.unsettled_months import unsettled_periods`):

```python
@router.get("/unsettled", response_model=ResponseModel[List[UnsettledMonth]])
def get_unsettled_months(
    group_id: int,
    service: ExpenseService = Depends(get_expense_service),
    group_repo: GroupRepository = Depends(get_group_repository),
    current_member=Depends(get_current_member),
) -> ResponseModel[List[UnsettledMonth]]:
    """Past months of this group left unsettled with a balance, for the month picker."""
    if not group_repo.is_member(group_id, current_member.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this group")
    group = group_repo.get(group_id)
    if group is None or group.group_type != GroupType.REGULAR:
        return ResponseModel(data=[])
    shares = service.get_all_monthly_shares().values()
    periods = unsettled_periods(shares, datetime.now().date())
    return ResponseModel(data=[UnsettledMonth(year=y, month=m) for y, m in periods])
```

Add to `ExpenseService` in `src/template/service_layer/expense_service.py` (it stores `self._repository` and
`self._group_id`; `Dict` and `MonthlyShare` are already imported there — confirm with `grep -n "^from\|^import" src/template/service_layer/expense_service.py`):

```python
    def get_all_monthly_shares(self) -> Dict[str, MonthlyShare]:
        """Every monthly share of this service's group, keyed YYYY-MM."""
        return self._repository.get_all_monthly_shares(self._group_id)
```

- [ ] **Step 7: Run unit tests and lint**

Run: `poetry run pytest tests/unit -q && git add -A && make lint`
Expected: PASS. Integration runs in Task 4.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(shares): meses pasados sin saldar de un grupo (GET /shares/unsettled)"
```

---

## Task 3: Endpoint de búsqueda (backend)

**Files:**
- Modify: `src/template/domain/schemas/search.py` (agrega `ExpenseSearchResult`, `ExpenseSearchResponse`)
- Modify: `src/template/adapters/repositories.py` (agrega `SearchRepository` al final; `GroupRepository.list_ids_for_member_all`)
- Create: `src/template/service_layer/search_service.py`
- Modify: `src/template/dependencies.py`, `src/template/router.py`
- Create: `src/template/entrypoint/search.py`
- Modify: `tests/integration/conftest.py`
- Test: `tests/integration/search/__init__.py`, `tests/integration/search/test_search_router.py`

**Interfaces:**
- Consumes: `parse_query`, `ParsedQuery`, `ACCENTS_FROM`, `ACCENTS_TO` (Task 1); `GroupRepository.is_member`, `GroupRepository.get_personal_for_owner(member_id) -> Optional[Group]`.
- Produces: `GET /api/v1/search/expenses?q=&groupId=` → `ResponseModel[ExpenseSearchResponse]`, where

```
ExpenseSearchResult { kind: "expense"|"recurring_personal", id, description, amount, currency,
  date: date|None, category, groupId, groupName, groupType, payerId, payerName,
  installmentNo, installments, periodYear, periodMonth, periodSettled: bool|None }
ExpenseSearchResponse { results: list[ExpenseSearchResult], hasMore: bool }
```

- [ ] **Step 1: Make the test DB cleanup cover personal fixed expenses**

In `tests/integration/conftest.py`, inside `_wipe_tables`, add these two lines **before** `DELETE FROM groups`:

```python
    session.execute(text("DELETE FROM recurring_personal_expense_instances"))
    session.execute(text("DELETE FROM recurring_personal_expenses"))
```

- [ ] **Step 2: Write the failing integration tests**

`tests/integration/search/__init__.py`: empty. `tests/integration/search/test_search_router.py`:

```python
"""Integration tests for GET /search/expenses."""

from datetime import date


def _expense(payer_id, description, amount=1000.0, when="2026-05-10", category="comida", **extra):
    payload = {
        "description": description,
        "amount": amount,
        "date": when,
        "category": {"name": category},
        "payerId": payer_id,
        "paymentType": "debit",
        "installments": 1,
        "splitStrategy": {"type": "equal"},
    }
    payload.update(extra)
    return payload


def _post(client, headers, group_id, payload):
    r = client.post(f"/api/v1/groups/{group_id}/expenses/", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["data"]


def _search(client, headers, q, group_id=None):
    params = {"q": q}
    if group_id is not None:
        params["groupId"] = group_id
    r = client.get("/api/v1/search/expenses", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _other_user(client):
    client.post(
        "/api/v1/auth/register",
        json={"name": "Extraño", "telephone": "5499933334444", "email": "x@example.com", "password": "secret123"},
    )
    token = client.post("/api/v1/auth/token", data={"username": "x@example.com", "password": "secret123"}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


def test_matches_every_word_in_description(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Cena en el centro"))
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Cena en casa"))
    data = _search(client, auth_headers, "cena centro")
    assert [r["description"] for r in data["results"]] == ["Cena en el centro"]
    assert data["hasMore"] is False


def test_matches_without_accents(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Café con medialunas"))
    assert len(_search(client, auth_headers, "cafe")["results"]) == 1


def test_matches_payer_name(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Luz"))
    results = _search(client, auth_headers, "tester")["results"]  # the auth_headers member is "Tester"
    assert [r["description"] for r in results] == ["Luz"]
    assert results[0]["payerName"] == "Tester"


def test_matches_exact_amount_with_local_format(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Carnicería", amount=24000.0))
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Verdulería", amount=2400.0))
    assert [r["description"] for r in _search(client, auth_headers, "24.000")["results"]] == ["Carnicería"]


def test_wildcards_are_literal(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Supermercado"))
    assert _search(client, auth_headers, "%%")["results"] == []
    assert _search(client, auth_headers, "__")["results"] == []


def test_excludes_internal_categories(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Pago a Guada", category="prestamo"))
    assert _search(client, auth_headers, "pago")["results"] == []


def test_one_row_per_installment_with_period_and_state(client, auth_headers, primary_member_id, primary_group_id):
    _post(
        client,
        auth_headers,
        primary_group_id,
        _expense(primary_member_id, "Equipo ski", amount=3000.0, paymentType="credit", installments=3),
    )
    results = _search(client, auth_headers, "ski")["results"]
    assert len(results) == 3
    assert sorted(r["installmentNo"] for r in results) == [1, 2, 3]
    assert all(r["installments"] == 3 for r in results)
    assert all(r["periodSettled"] is False for r in results)
    assert len({(r["periodYear"], r["periodMonth"]) for r in results}) == 3


def test_never_returns_expenses_from_a_group_you_are_not_in(
    client, auth_headers, primary_member_id, primary_group_id
):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Secreto"))
    stranger = _other_user(client)
    assert _search(client, stranger, "secreto")["results"] == []
    r = client.get(
        "/api/v1/search/expenses", params={"q": "secreto", "groupId": primary_group_id}, headers=stranger
    )
    assert r.status_code == 403


def test_group_scope_limits_to_that_group(client, auth_headers, primary_member_id, primary_group_id):
    other = client.post("/api/v1/groups/", json={"name": "Viaje"}, headers=auth_headers).json()["data"]["id"]
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Nafta casa"))
    _post(client, auth_headers, other, _expense(primary_member_id, "Nafta viaje"))
    results = _search(client, auth_headers, "nafta", group_id=other)["results"]
    assert [r["description"] for r in results] == ["Nafta viaje"]
    assert results[0]["groupName"] == "Viaje"


def test_archived_group_still_searchable(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Heladera", amount=10.0))
    # settle so the member carries no balance and is allowed to archive
    client.post(f"/api/v1/groups/{primary_group_id}/shares/settle/2026/05", headers=auth_headers)
    r = client.post(f"/api/v1/groups/{primary_group_id}/archive", headers=auth_headers)
    assert r.status_code in (200, 204), r.text
    assert len(_search(client, auth_headers, "heladera")["results"]) == 1


def test_includes_personal_fixed_expenses_without_date(client, auth_headers):
    today = date.today()
    client.get("/api/v1/personal/group", headers=auth_headers)
    r = client.post(
        "/api/v1/personal/expenses/recurring",
        json={"label": "Prepaga", "amount": 50000.0, "categoryName": "salud",
              "startYear": today.year, "startMonth": today.month},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    client.get(f"/api/v1/personal/ledger/{today.year}/{today.month}", headers=auth_headers)  # materializes

    results = _search(client, auth_headers, "prepaga")["results"]
    assert len(results) == 1
    assert results[0]["kind"] == "recurring_personal"
    assert results[0]["date"] is None
    assert (results[0]["periodYear"], results[0]["periodMonth"]) == (today.year, today.month)
    assert results[0]["periodSettled"] is None


def test_caps_at_fifty_with_has_more(client, auth_headers, primary_member_id, primary_group_id):
    for i in range(51):
        _post(client, auth_headers, primary_group_id, _expense(primary_member_id, f"Kiosco {i}", amount=1.0 + i))
    data = _search(client, auth_headers, "kiosco")
    assert len(data["results"]) == 50
    assert data["hasMore"] is True


def test_too_short_query_returns_empty(client, auth_headers, primary_member_id, primary_group_id):
    _post(client, auth_headers, primary_group_id, _expense(primary_member_id, "Agua"))
    assert _search(client, auth_headers, "a")["results"] == []
```

- [ ] **Step 3: Add the response schemas**

Append to `src/template/domain/schemas/search.py` (add `from datetime import date`, `from typing import Literal, Optional`):

```python
class ExpenseSearchResult(CamelCaseModel):
    """One expense row (one installment) or one personal fixed-expense month that matched."""

    kind: Literal["expense", "recurring_personal"]
    id: int
    description: str
    amount: float
    currency: str
    date: Optional[date]
    category: str
    group_id: int
    group_name: str
    group_type: str
    payer_id: Optional[int]
    payer_name: str
    installment_no: int
    installments: int
    period_year: int
    period_month: int
    period_settled: Optional[bool]


class ExpenseSearchResponse(CamelCaseModel):
    results: list[ExpenseSearchResult]
    has_more: bool
```

- [ ] **Step 4: Add the repository**

In `GroupRepository` (`src/template/adapters/repositories.py`), add:

```python
    def list_ids_for_member_all(self, member_id: int) -> list[int]:
        """Ids of every non-deleted group the member belongs to, archived and personal included."""
        rows = (
            self.session.query(GroupModel.id)
            .join(GroupMembershipModel, GroupModel.id == GroupMembershipModel.group_id)
            .filter(GroupMembershipModel.member_id == member_id, GroupModel.status != "deleted")
            .all()
        )
        ids = {row.id for row in rows}
        personal = self.get_personal_for_owner(member_id)
        if personal is not None and personal.id is not None:
            ids.add(personal.id)
        return sorted(ids)
```

At the end of the file, add (imports at the top: `from template.service_layer.search_query import ACCENTS_FROM,
ACCENTS_TO, ParsedQuery`; the SQLAlchemy ones are listed after the code):

```python
class SearchRepository:
    """Expense search across a set of groups. Matching mirrors `search_query.parse_query`."""

    EXCLUDED_CATEGORIES = ("balance", "prestamo")

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _norm(column):
        return func.translate(func.lower(column), ACCENTS_FROM, ACCENTS_TO)

    @staticmethod
    def _like(term: str) -> str:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    def _text_match(self, query: ParsedQuery, *columns):
        return and_(
            *[or_(*[self._norm(col).like(self._like(term), escape="\\") for col in columns]) for term in query.terms]
        )

    def search_expenses(self, group_ids: list[int], query: ParsedQuery, limit: int) -> list[tuple]:
        """Rows of (ExpenseModel, MonthlyShareModel, GroupModel, MemberModel), newest first."""
        match = self._text_match(query, ExpenseModel.description, MemberModel.name)
        if query.amount is not None:
            match = or_(match, func.abs(ExpenseModel.amount - query.amount) < 0.005)
        return (
            self.session.query(ExpenseModel, MonthlyShareModel, GroupModel, MemberModel)
            .join(MonthlyShareModel, ExpenseModel.monthly_share_id == MonthlyShareModel.id)
            .join(GroupModel, ExpenseModel.group_id == GroupModel.id)
            .join(MemberModel, ExpenseModel.payer_id == MemberModel.id)
            .filter(
                ExpenseModel.group_id.in_(group_ids),
                ExpenseModel.category.notin_(self.EXCLUDED_CATEGORIES),
                match,
            )
            .order_by(ExpenseModel.date.desc(), ExpenseModel.id.desc())
            .limit(limit)
            .all()
        )

    def search_personal_fixed(
        self, personal_group_id: int, owner_name: str, query: ParsedQuery, limit: int
    ) -> list[RecurringPersonalExpenseInstanceModel]:
        """Personal fixed-expense months. The owner's name counts as the payer."""
        owner = normalize_python(owner_name)
        # A term that is part of the owner's name matches every fixed expense, like a payer would.
        terms = tuple(t for t in query.terms if t not in owner)
        match = (
            self._text_match(ParsedQuery(terms=terms, amount=None), RecurringPersonalExpenseInstanceModel.label)
            if terms
            else true()  # every term was the owner's name
        )
        if query.amount is not None:
            match = or_(match, func.abs(RecurringPersonalExpenseInstanceModel.amount - query.amount) < 0.005)
        return (
            self.session.query(RecurringPersonalExpenseInstanceModel)
            .filter(RecurringPersonalExpenseInstanceModel.personal_group_id == personal_group_id, match)
            .order_by(
                RecurringPersonalExpenseInstanceModel.year.desc(),
                RecurringPersonalExpenseInstanceModel.month.desc(),
                RecurringPersonalExpenseInstanceModel.id.desc(),
            )
            .limit(limit)
            .all()
        )
```

with, at the top of the file, `from sqlalchemy import and_, func, or_, true` and
`from template.service_layer.search_query import normalize as normalize_python`.

- [ ] **Step 5: Add the service**

`src/template/service_layer/search_service.py`:

```python
"""Expense search for one member: every group they are in, or one of them."""

from datetime import date
from typing import Optional

from template.adapters.repositories import GroupRepository, SearchRepository
from template.domain.models.group import GroupType
from template.domain.models.member import Member
from template.domain.schemas.search import ExpenseSearchResponse, ExpenseSearchResult
from template.service_layer.search_query import parse_query

MAX_RESULTS = 50


class NotAMemberError(Exception):
    """The member asked to search a group they do not belong to."""


class SearchService:
    def __init__(self, groups: GroupRepository, search: SearchRepository):
        self._groups = groups
        self._search = search

    def search(self, member: Member, q: str, group_id: Optional[int] = None) -> ExpenseSearchResponse:
        query = parse_query(q)
        if query is None:
            return ExpenseSearchResponse(results=[], has_more=False)

        if group_id is not None:
            if not self._groups.is_member(group_id, member.id):
                personal = self._groups.get_personal_for_owner(member.id)
                if personal is None or personal.id != group_id:
                    raise NotAMemberError()
            group_ids = [group_id]
        else:
            group_ids = self._groups.list_ids_for_member_all(member.id)

        fetch = MAX_RESULTS + 1
        results = [self._from_expense(*row) for row in self._search.search_expenses(group_ids, query, fetch)]

        personal = self._groups.get_personal_for_owner(member.id)
        if personal is not None and personal.id in group_ids:
            fixed = self._search.search_personal_fixed(personal.id, member.name, query, fetch)
            results += [self._from_fixed(row, personal.id, personal.name, member) for row in fixed]

        results.sort(key=self._sort_key, reverse=True)
        return ExpenseSearchResponse(results=results[:MAX_RESULTS], has_more=len(results) > MAX_RESULTS)

    @staticmethod
    def _sort_key(result: ExpenseSearchResult) -> tuple:
        day = result.date or date(result.period_year, result.period_month, 1)
        return (day, result.id)

    @staticmethod
    def _from_expense(expense, share, group, payer) -> ExpenseSearchResult:
        is_personal = group.group_type == GroupType.PERSONAL.value
        return ExpenseSearchResult(
            kind="expense",
            id=expense.id,
            description=expense.description,
            amount=expense.amount,
            currency=expense.currency or "ARS",
            date=expense.date,
            category=expense.category,
            group_id=group.id,
            group_name=group.name,
            group_type=group.group_type,
            payer_id=payer.id,
            payer_name=payer.name,
            installment_no=expense.installment_no or 1,
            installments=expense.installments or 1,
            period_year=share.year,
            period_month=share.month,
            period_settled=None if is_personal else bool(share.is_settled),
        )

    @staticmethod
    def _from_fixed(row, group_id: int, group_name: str, owner: Member) -> ExpenseSearchResult:
        return ExpenseSearchResult(
            kind="recurring_personal",
            id=row.id,
            description=row.label,
            amount=row.amount,
            currency=row.currency or "ARS",
            date=None,
            category=row.category_name,
            group_id=group_id,
            group_name=group_name,
            group_type=GroupType.PERSONAL.value,
            payer_id=owner.id,
            payer_name=owner.name,
            installment_no=1,
            installments=1,
            period_year=row.year,
            period_month=row.month,
            period_settled=None,
        )
```

- [ ] **Step 6: Wire dependency, router and registration**

`src/template/dependencies.py`:

```python
def get_search_service(db: Session = Depends(get_db)) -> SearchService:
    return SearchService(GroupRepository(db), SearchRepository(db))
```

`src/template/entrypoint/search.py`:

```python
"""GET /search/expenses — find expenses by text, amount or payer."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from template.dependencies import get_search_service
from template.domain.schema_model import ResponseModel
from template.domain.schemas.search import ExpenseSearchResponse
from template.service_layer.auth_service import get_current_member
from template.service_layer.search_service import NotAMemberError, SearchService

router = APIRouter(prefix="/search", tags=["Search"])


@router.get("/expenses", response_model=ResponseModel[ExpenseSearchResponse])
def search_expenses(
    q: str = Query("", max_length=100),
    group_id: Optional[int] = Query(None, alias="groupId"),
    service: SearchService = Depends(get_search_service),
    current_member=Depends(get_current_member),
) -> ResponseModel[ExpenseSearchResponse]:
    """Every group the member is in (and their personal group), or only `groupId`."""
    try:
        return ResponseModel(data=service.search(current_member, q, group_id))
    except NotAMemberError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this group") from e
```

`src/template/router.py`: `from template.entrypoint import search` and `api_router_v1.include_router(search.router)`.

- [ ] **Step 7: Unit gate + lint, then commit**

Run: `poetry run pytest tests/unit -q && git add -A && make lint`
Expected: PASS. Also add the new router to `tests/unit/entrypoint/test_endpoints_require_auth.py` if that test enumerates routes (check with `grep -n "shares" tests/unit/entrypoint/test_endpoints_require_auth.py`).

```bash
git add -A
git commit -m "feat(search): GET /search/expenses — texto, monto y pagador en tus grupos"
```

---

## Task 4: Integración y docs del backend

**Files:**
- Modify: `CLAUDE.md` (API surface: `Search` y `GET /shares/unsettled`), `../CLAUDE.md` (monorepo, cross-cutting: la búsqueda)

- [ ] **Step 1: Run the integration suite against a disposable Postgres**

Never staging/prod. Either (a) a local throwaway DB — `brew install postgresql@15 && brew services start postgresql@15 && createdb se_test` then `TEST_DATABASE_URL=postgresql://localhost/se_test make integration` — **only if the user approved installing it**; or (b) open the PR and let CI's `postgres:15` job run it.
Expected: all green, including `tests/integration/search/` and `test_unsettled_months_router.py`.

- [ ] **Step 2: Fix whatever fails, re-run, then update docs**

In `CLAUDE.md` → API surface, add:

```
**Search** `/api/v1/search`
- `GET /expenses?q=&groupId=` — text (every word in description or payer name, accent-insensitive) or exact amount; your groups (archived included) + your personal group, or only `groupId` (403 if not a member). One row per installment with its period and `periodSettled`. Excludes `balance`/`prestamo`. Max 50, `hasMore`.
```

and under Monthly Shares: `- GET /unsettled — past months left unsettled with a non-zero balance (regular groups only). Declared before /{year}/{month}.`

- [ ] **Step 3: Commit**

```bash
git add -A && make lint && git commit -m "docs: búsqueda y meses sin saldar en CLAUDE.md"
```

---

## Task 5: Cliente, tipos y coincidencia en el front

**Files:**
- Create: `src/utils/search.ts`, `src/api/search.ts`
- Modify: `src/api/shares.ts`, `src/types/expense.ts`

**Interfaces:**
- Consumes: backend contract from Task 3 / Task 2.
- Produces: `normalize(text: string): string`, `parseQuery(q: string): { terms: string[]; amount: number | null } | null`, `matchesQuery(text: string[], amount: number, q: ReturnType<typeof parseQuery>): boolean`, `searchExpenses(q: string, groupId?: number, signal?: AbortSignal): Promise<ExpenseSearchResponse>`, `getUnsettledMonths(groupId: number): Promise<UnsettledMonth[]>`; types `ExpenseSearchResult`, `ExpenseSearchResponse`, `UnsettledMonth`.

- [ ] **Step 1: Types** (append to `src/types/expense.ts`)

```ts
export interface ExpenseSearchResult {
  kind: 'expense' | 'recurring_personal';
  id: number;
  description: string;
  amount: number;
  currency: string;
  date: string | null;
  category: string;
  groupId: number;
  groupName: string;
  groupType: GroupType;
  payerId: number | null;
  payerName: string;
  installmentNo: number;
  installments: number;
  periodYear: number;
  periodMonth: number;
  periodSettled: boolean | null;
}

export interface ExpenseSearchResponse {
  results: ExpenseSearchResult[];
  hasMore: boolean;
}

export interface UnsettledMonth {
  year: number;
  month: number;
}
```

- [ ] **Step 2: `src/utils/search.ts`** — same rules as `search_query.py`

```ts
/*
  Espejo de service_layer/search_query.py: mismas palabras, mismos acentos, mismo monto. La lupa
  del mes filtra en el cliente con esto y la general le pregunta al backend; tienen que coincidir.
*/
const ACCENTS_FROM = 'áàâäéèêëíìîïóòôöúùûüñç';
const ACCENTS_TO = 'aaaaeeeeiiiioooouuuunc';
const MIN_TEXT_LENGTH = 2;

export function normalize(text: string): string {
  let out = '';
  for (const ch of text.toLowerCase()) {
    const i = ACCENTS_FROM.indexOf(ch);
    out += i >= 0 ? ACCENTS_TO[i] : ch;
  }
  return out;
}

export function parseAmount(text: string): number | null {
  const v = text.trim();
  if (/^\d{1,3}(\.\d{3})+(,\d{1,2})?$/.test(v) || /^\d+(,\d{1,2})?$/.test(v)) {
    return Number(v.replace(/\./g, '').replace(',', '.'));
  }
  if (/^\d+\.\d{1,2}$/.test(v)) return Number(v);
  return null;
}

export interface ParsedQuery { terms: string[]; amount: number | null }

export function parseQuery(q: string): ParsedQuery | null {
  const stripped = q.trim();
  const amount = parseAmount(stripped);
  if (amount === null && stripped.length < MIN_TEXT_LENGTH) return null;
  const terms = normalize(stripped).split(/\s+/).filter(Boolean);
  return terms.length ? { terms, amount } : null;
}

/** ¿Coincide un gasto? `fields` son los textos donde buscar (descripción, pagador). */
export function matchesQuery(fields: string[], amount: number, q: ParsedQuery): boolean {
  const haystack = fields.map(normalize);
  const byText = q.terms.every(term => haystack.some(f => f.includes(term)));
  const byAmount = q.amount !== null && Math.abs(amount - q.amount) < 0.005;
  return byText || byAmount;
}
```

- [ ] **Step 3: Verify it mirrors the backend cases**

Run (esbuild ships with vite):

```bash
S=$(mktemp -d); npx esbuild src/utils/search.ts --bundle --format=cjs --platform=node --outfile=$S/s.cjs --log-level=error && node -e "
const s=require('$S/s.cjs'); const eq=(a,b)=>JSON.stringify(a)===JSON.stringify(b); let ok=true;
for (const [i,e] of [['24000',24000],['24.000',24000],['24000,50',24000.5],['24.000,50',24000.5],['1.234.567',1234567],['1.5',1.5],['cena',null],['24k',null],['1.2345',null]]) if (s.parseAmount(i)!==e){ok=false;console.log('amount',i,s.parseAmount(i))}
if (s.normalize('Café Ñandú ÁRBOL')!=='cafe nandu arbol') {ok=false;console.log('norm')}
if (s.parseQuery('a')!==null) {ok=false;console.log('short')}
if (!eq(s.parseQuery('24.000'),{terms:['24.000'],amount:24000})) {ok=false;console.log('num')}
const q=s.parseQuery('cena centro'); if(!s.matchesQuery(['Cena en el centro','Fran'],1,q)||s.matchesQuery(['Cena en casa','Fran'],1,q)){ok=false;console.log('match')}
if(!s.matchesQuery(['Carnicería','Fran'],24000,s.parseQuery('24.000'))){ok=false;console.log('amountmatch')}
if(!s.matchesQuery(['Café','Fran'],1,s.parseQuery('cafe'))){ok=false;console.log('accent')}
console.log(ok?'all ok':'FAIL')"
```

Expected: `all ok`

- [ ] **Step 4: API clients**

`src/api/search.ts`:

```ts
import { config } from '../config/env';
import type { ExpenseSearchResponse } from '../types/expense';

export async function searchExpenses(q: string, groupId?: number, signal?: AbortSignal): Promise<ExpenseSearchResponse> {
  const params = new URLSearchParams({ q });
  if (groupId !== undefined) params.set('groupId', String(groupId));
  const token = localStorage.getItem('token');
  const res = await fetch(`${config.apiBaseUrl}/api/v1/search/expenses?${params}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal,
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof json.detail === 'string' ? json.detail : 'Search failed');
  return json.data as ExpenseSearchResponse;
}
```

Append to `src/api/shares.ts` (uses its existing `authHeaders()` and `handleResponse<T>()`; confirm both exist with `grep -n "function authHeaders\|function handleResponse" src/api/shares.ts`):

```ts
export async function getUnsettledMonths(groupId: number): Promise<UnsettledMonth[]> {
  const response = await fetch(`${config.apiBaseUrl}/api/v1/groups/${groupId}/shares/unsettled`, {
    headers: authHeaders(),
  });
  return handleResponse<UnsettledMonth[]>(response);
}
```

- [ ] **Step 5: Gates and commit**

Run: `npm run typecheck:ratchet && npm run lint`
Expected: `TypeScript errors: 18, matching baseline.` and 0 errors.

```bash
git add -A && git commit -m "feat(search): cliente, tipos y la misma coincidencia que el backend"
```

---

## Task 6: Lupa del mes (sale "Sin saldar")

**Files:**
- Modify: `src/components/expenses/ExpenseListHeader.tsx`, i18n `es.json`/`en.json`

**Interfaces:**
- Consumes: `parseQuery`, `matchesQuery` (Task 5).

- [ ] **Step 1: Replace the `unsettled` filter with a query**

In `ExpenseListHeader.tsx`: `type Filter = 'mine';` (the chips list only has "Míos"); delete `INTERNAL_CATEGORIES`; add state `const [monthQuery, setMonthQuery] = useState(''); const [searchOpen, setSearchOpen] = useState(false); const inputRef = useRef<HTMLInputElement>(null);`. In the `sorted` memo, replace the `unsettled` line with:

```ts
      if (parsed && !matchesQuery([e.description, memberName(e.payerId)], e.amount, parsed)) return false;
```

with `const parsed = useMemo(() => parseQuery(monthQuery), [monthQuery]);` above, and add `parsed` to the memo deps.

- [ ] **Step 2: The expanding field in the chip row**

Before the "Míos" chip render:

```tsx
          {searchOpen ? (
            <label className="glass flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded-full pl-2.5 pr-1">
              <Search className="h-3.5 w-3.5 shrink-0 text-muted-1" aria-hidden="true" />
              <input
                ref={inputRef}
                type="search"
                enterKeyHint="search"
                value={monthQuery}
                onChange={e => setMonthQuery(e.target.value)}
                placeholder={t('search.inMonth', { month: monthLabel.toLowerCase() })}
                aria-label={t('search.inMonth', { month: monthLabel.toLowerCase() })}
                className="min-w-0 flex-1 bg-transparent text-[16px] font-medium text-foreground outline-none placeholder:text-muted-2 lg:text-[12.5px]"
              />
              <button
                type="button"
                onClick={() => { setMonthQuery(''); setSearchOpen(false); }}
                aria-label={t('search.close')}
                className="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded-full text-muted-1 hover:bg-surface-sunken"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </label>
          ) : (
            <button
              type="button"
              onClick={() => { setSearchOpen(true); requestAnimationFrame(() => inputRef.current?.focus()); }}
              aria-label={t('search.inMonth', { month: monthLabel.toLowerCase() })}
              className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-full border border-line-strong text-muted-1 hover:bg-surface-sunken"
            >
              <Search className="h-3.5 w-3.5" />
            </button>
          )}
```

(`text-[16px]` on mobile avoids iOS auto-zoom. iOS may not open the keyboard from `requestAnimationFrame`; if it doesn't in the WebKit check, render the input always and toggle its width with CSS so `focus()` runs inside the tap.)

- [ ] **Step 3: i18n** — add `search.inMonth` ("Buscar en {{month}}" / "Search {{month}}") and `search.close` ("Cerrar búsqueda" / "Close search"); delete `expenses.chipUnsettled` if nothing else uses it (`grep -rn chipUnsettled src`).

- [ ] **Step 4: Gates, browser check, commit**

`npm run typecheck:ratchet && npm run lint`; in the browser with the mock (see Task 10): type "luz" in a group month → only "Luz" stays; "54.000" → the $54.000 row; "Míos" + query combine.

```bash
git add -A && git commit -m "feat(search): lupa del mes en lugar de 'Sin saldar'"
```

---

## Task 7: Meses sin saldar en el selector de mes

**Files:**
- Modify: `src/components/expenses/MonthPager.tsx`, `src/pages/ExpensesDashboard.tsx`, `src/pages/GroupMembersPage.tsx`, `src/pages/GroupChartsPage.tsx`, `src/pages/SettleProgressPage.tsx`, i18n

**Interfaces:**
- Consumes: `getUnsettledMonths(groupId)` (Task 5).
- Produces: `MonthPager` prop `groupId?: number` (only pass it for regular groups).

- [ ] **Step 1: Fetch on open**

In `MonthPager`, add prop `groupId?: number` and:

```ts
  const [unsettled, setUnsettled] = useState<UnsettledMonth[]>([]);
  useEffect(() => {
    if (!pickerOpen || groupId === undefined) return;
    let cancelled = false;
    getUnsettledMonths(groupId).then(list => { if (!cancelled) setUnsettled(list); }).catch(() => {});
    return () => { cancelled = true; };
  }, [pickerOpen, groupId]);
  const isUnsettled = (y: number, m: number) => unsettled.some(u => u.year === y && u.month === m);
```

- [ ] **Step 2: Shortcut and dots**

At the top of the picker panel (above the year row), when `unsettled.length > 0`:

```tsx
          {unsettled.length > 0 && (
            <div className="mb-2.5 border-b border-line pb-2.5">
              <p className="mb-1.5 text-[10.5px] font-bold uppercase tracking-[0.1em] text-negative">{t('monthPager.unsettled')}</p>
              <div className="flex flex-wrap gap-1.5">
                {unsettled.map(u => (
                  <button
                    key={`${u.year}-${u.month}`}
                    type="button"
                    onClick={() => { onNavigate(u.year, u.month); setPickerOpen(false); }}
                    className="h-7 cursor-pointer rounded-full bg-negative-wash px-2.5 text-[11.5px] font-bold capitalize text-negative"
                  >
                    {`${(months[u.month - 1] ?? '').slice(0, 3)} ${u.year}`}
                  </button>
                ))}
              </div>
            </div>
          )}
```

In the month grid button, after the label: `{isUnsettled(pickerYear, i + 1) && <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-negative align-middle" aria-hidden="true" />}` and add `aria-label` suffix `t('monthPager.unsettledMonth')` when unsettled.

- [ ] **Step 3: Pass `groupId` from group pages** — only when the group is regular: `groupId={isOneTime ? undefined : groupId}` in `ExpensesDashboard`, `GroupMembersPage`, `GroupChartsPage`, `SettleProgressPage`.

- [ ] **Step 4: i18n** — `monthPager.unsettled` ("Sin saldar" / "Unsettled"), `monthPager.unsettledMonth` ("sin saldar" / "unsettled").

- [ ] **Step 5: Gates, browser check (mock `/shares/unsettled` → `[{year:2026,month:7}]`), commit**

```bash
git add -A && git commit -m "feat(shares): el selector de mes marca los meses pasados sin saldar"
```

---

## Task 8: Overlay de búsqueda (general y del grupo)

**Files:**
- Create: `src/hooks/useExpenseSearch.ts`, `src/contexts/SearchContext.tsx`, `src/components/search/SearchOverlay.tsx`, `src/components/search/SearchResultRow.tsx`
- Modify: `src/App.tsx` (provider), `src/components/layout/AppShell.tsx` (mount overlay, ⌘K), i18n

**Interfaces:**
- Consumes: `searchExpenses` (Task 5), `ExpenseSearchResult`.
- Produces: `useSearch(): { openSearch: (scope?: { groupId: number; groupName: string }) => void }`; `useExpenseSearch(q: string, groupId?: number): { results: ExpenseSearchResult[]; hasMore: boolean; loading: boolean; error: string | null; retry: () => void; active: boolean }`.

- [ ] **Step 1: `useExpenseSearch`** — debounce 250ms, drop stale responses, keep previous results while loading

```ts
import { useCallback, useEffect, useRef, useState } from 'react';
import { searchExpenses } from '@/api/search';
import { parseQuery } from '@/utils/search';
import type { ExpenseSearchResult } from '@/types/expense';

const DEBOUNCE_MS = 250;

export function useExpenseSearch(q: string, groupId?: number) {
  const [results, setResults] = useState<ExpenseSearchResult[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const requestId = useRef(0);
  const active = parseQuery(q) !== null;

  useEffect(() => {
    if (!active) { setResults([]); setHasMore(false); setError(null); setLoading(false); return; }
    const id = ++requestId.current;
    const controller = new AbortController();
    setLoading(true);
    const timer = setTimeout(() => {
      searchExpenses(q, groupId, controller.signal)
        .then(data => {
          if (id !== requestId.current) return; // una respuesta vieja que llegó tarde
          setResults(data.results); setHasMore(data.hasMore); setError(null);
        })
        .catch(err => {
          if (id !== requestId.current || controller.signal.aborted) return;
          setError(err instanceof Error ? err.message : 'Error');
        })
        .finally(() => { if (id === requestId.current) setLoading(false); });
    }, DEBOUNCE_MS);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [q, groupId, active, nonce]);

  const retry = useCallback(() => setNonce(n => n + 1), []);
  return { results, hasMore, loading, error, retry, active };
}
```

- [ ] **Step 2: `SearchContext`** — the overlay lives once in `AppShell`; openers focus its input inside the tap

```tsx
import React, { createContext, useCallback, useContext, useRef, useState } from 'react';

export interface SearchScope { groupId: number; groupName: string }
interface SearchContextValue {
  open: boolean;
  scope: SearchScope | null;
  openSearch: (scope?: SearchScope) => void;
  closeSearch: () => void;
  inputRef: React.RefObject<HTMLInputElement>;
}

const SearchContext = createContext<SearchContextValue | null>(null);

export function SearchProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<SearchScope | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const openSearch = useCallback((next?: SearchScope) => {
    setScope(next ?? null);
    setOpen(true);
    // El input ya está montado (invisible): enfocarlo acá, dentro del toque, es lo que hace que
    // iOS abra el teclado. Desde un efecto, después del render, no lo abre.
    inputRef.current?.focus();
  }, []);
  const closeSearch = useCallback(() => { setOpen(false); inputRef.current?.blur(); }, []);
  return (
    <SearchContext.Provider value={{ open, scope, openSearch, closeSearch, inputRef }}>
      {children}
    </SearchContext.Provider>
  );
}

export function useSearch(): SearchContextValue {
  const ctx = useContext(SearchContext);
  if (!ctx) throw new Error('useSearch must be used inside SearchProvider');
  return ctx;
}
```

Wrap in `App.tsx` inside the authenticated tree, next to `FabActionsProvider`.

- [ ] **Step 3: `SearchResultRow`** — one row: emoji, description, "Casa · Pagó Fran" (no group in group scope), amount via `useCurrency().formatAmount`, chips período + estado

```tsx
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { useCurrency } from '@/contexts/CurrencyContext';
import type { ExpenseSearchResult } from '@/types/expense';

export function SearchResultRow({ result, emoji, showGroup, onSelect }: {
  result: ExpenseSearchResult; emoji?: string; showGroup: boolean; onSelect: () => void;
}) {
  const { t } = useTranslation();
  const { formatAmount } = useCurrency();
  const monthsShort = t('monthsShort', { returnObjects: true }) as string[];
  const period = `${monthsShort[result.periodMonth - 1] ?? ''} ${result.periodYear}`;
  const now = new Date();
  const isPast = result.periodYear * 12 + result.periodMonth < now.getFullYear() * 12 + now.getMonth() + 1;
  const meta = [showGroup ? result.groupName : null, t('search.paidBy', { name: result.payerName })]
    .filter(Boolean).join(' · ');
  return (
    <button type="button" onClick={onSelect}
      className="flex w-full cursor-pointer items-start gap-3 border-b border-line px-4 py-3 text-left last:border-b-0 hover:bg-surface-sunken/60">
      <span className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[11px] bg-surface-sunken text-lg leading-none">
        {emoji ?? '·'}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13.5px] font-semibold text-foreground">{result.description}</span>
        <span className="mt-0.5 block truncate text-[11.5px] font-medium text-muted-1">
          {result.kind === 'recurring_personal' ? t('search.everyMonth', { period }) : meta}
        </span>
        <span className="mt-1.5 flex flex-wrap gap-1">
          <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-[10.5px] font-bold capitalize text-muted-1">{period}</span>
          {result.periodSettled !== null && (
            <span className={cn('rounded-full px-2 py-0.5 text-[10.5px] font-bold',
              result.periodSettled ? 'bg-positive-wash text-positive'
                : isPast ? 'bg-negative-wash text-negative' : 'bg-surface-sunken text-muted-1')}>
              {result.periodSettled ? t('search.settled') : t('search.unsettled')}
            </span>
          )}
        </span>
      </span>
      <span className="shrink-0 text-[13.5px] font-bold tabular-nums text-foreground">
        {formatAmount(result.amount, result.currency)}
      </span>
    </button>
  );
}
```

- [ ] **Step 4: `SearchOverlay`** — always mounted, `opacity-0 pointer-events-none` when closed; field + ✕ at the top (safe-area + 8px), results below, grouped by date (fixed personal → month header)

Full component (imports: `useEffect, useMemo, useState` from react, `useNavigate`, `useTranslation`, `Search, X`
from lucide-react, `cn`, `GlassButton`, `useSearch`, `useCategories`, `useExpenseSearch`, `SearchResultRow`,
`formatDayMonthYear`, type `ExpenseSearchResult`):

```tsx
export function SearchOverlay() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { open, scope, closeSearch, inputRef } = useSearch();
  const { data: categories = [] } = useCategories();
  const [q, setQ] = useState('');
  const { results, hasMore, loading, error, retry, active } = useExpenseSearch(q, scope?.groupId);
  const months = t('months', { returnObjects: true }) as string[];
  const monthsShort = t('monthsShort', { returnObjects: true }) as string[];

  useEffect(() => { if (!open) setQ(''); }, [open]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeSearch(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, closeSearch]);

  const groups = useMemo(() => {
    const out: { key: string; heading: string; items: ExpenseSearchResult[] }[] = [];
    for (const r of results) {
      const key = r.date ?? `${r.periodYear}-${r.periodMonth}`;
      const heading = r.date
        ? formatDayMonthYear(r.date, monthsShort)
        : `${months[r.periodMonth - 1] ?? ''} ${r.periodYear}`;
      const last = out[out.length - 1];
      if (last && last.key === key) last.items.push(r); else out.push({ key, heading, items: [r] });
    }
    return out;
  }, [results, months, monthsShort]);

  const select = (r: ExpenseSearchResult) => {
    closeSearch();
    if (r.groupType === 'personal') navigate(`/personal?year=${r.periodYear}&month=${r.periodMonth}`);
    else navigate(`/groups/${r.groupId}?year=${r.periodYear}&month=${r.periodMonth}&expense=${r.id}`);
  };
  return (
    <div
      aria-hidden={!open}
      className={cn(
        'fixed inset-0 z-[45] flex flex-col bg-background transition-opacity duration-150',
        open ? 'opacity-100' : 'pointer-events-none opacity-0',
      )}
    >
      {/* El campo que se estira: donde estaba la barra flotante, a lo ancho, con la ✕ al lado. */}
      <div className="flex items-center gap-2.5 px-4 pb-3" style={{ paddingTop: 'calc(env(safe-area-inset-top, 0px) + 8px)' }}>
        <label className="glass flex h-11 min-w-0 flex-1 items-center gap-2 rounded-full pl-3.5 pr-1.5">
          <Search className="h-[18px] w-[18px] shrink-0 text-muted-1" aria-hidden="true" />
          <input
            ref={inputRef}
            type="search"
            enterKeyHint="search"
            autoComplete="off"
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder={scope ? t('search.placeholderGroup', { group: scope.groupName }) : t('search.placeholderAll')}
            aria-label={scope ? t('search.placeholderGroup', { group: scope.groupName }) : t('search.placeholderAll')}
            className="min-w-0 flex-1 bg-transparent text-[16px] font-medium text-foreground outline-none placeholder:text-muted-2 [&::-webkit-search-cancel-button]:hidden"
          />
          {q && (
            <button
              type="button"
              onClick={() => { setQ(''); inputRef.current?.focus(); }}
              aria-label={t('search.clear')}
              className="flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-full bg-muted-3/50 text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </label>
        <GlassButton onClick={closeSearch} aria-label={t('search.close')} className="h-11 w-11">
          <X className="h-5 w-5" strokeWidth={2.4} />
        </GlassButton>
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden px-4 pb-tabbar lg:pb-6">
        <div className="mx-auto w-full max-w-lg">
          {!active && (
            <p className="mt-10 text-center text-[13px] font-medium text-muted-1">{t('search.hint')}</p>
          )}
          {active && error && (
            <div className="mt-10 flex flex-col items-center gap-3 text-center">
              <p className="text-[13px] font-medium text-muted-1">{error}</p>
              <button type="button" onClick={retry} className="h-9 cursor-pointer rounded-full bg-primary px-4 text-[12.5px] font-bold text-primary-foreground">
                {t('search.retry')}
              </button>
            </div>
          )}
          {active && !error && !loading && results.length === 0 && (
            <p className="mt-10 text-center text-[13px] font-medium text-muted-1">{t('search.empty', { q: q.trim() })}</p>
          )}
          {active && !error && groups.map(group => (
            <section key={group.key} className="mt-4">
              <h2 className="px-1 pb-2 text-[12px] font-bold text-muted-1">{group.heading}</h2>
              <div className="overflow-hidden rounded-card border border-line bg-surface">
                {group.items.map(r => (
                  <SearchResultRow
                    key={`${r.kind}-${r.id}`}
                    result={r}
                    emoji={categories.find(c => c.name === r.category)?.emoji}
                    showGroup={scope === null}
                    onSelect={() => select(r)}
                  />
                ))}
              </div>
            </section>
          ))}
          {active && hasMore && (
            <p className="mt-4 text-center text-[11.5px] font-medium text-muted-2">{t('search.capped')}</p>
          )}
        </div>
      </div>
    </div>
  );
}
```

Add `formatDayMonthYear(date, monthsShort)` to `src/utils/format.ts` ("8 jun 2026") if no equivalent exists (`grep -n "export function format" src/utils/format.ts`).

- [ ] **Step 5: Mount + ⌘K** — in `AppShell`, render `<SearchOverlay />` once; replace the ⌘K handler to call `openSearch(inGroup ? { groupId, groupName } : undefined)` (no navigation).

- [ ] **Step 6: i18n** — `search.placeholderAll` ("Buscar en todo" / "Search everything"), `search.placeholderGroup` (exists), `search.hint` ("Buscá por nombre, monto o quién pagó" / "Search by name, amount or who paid"), `search.empty` ("No encontramos nada con “{{q}}”" / "Nothing found for “{{q}}”"), `search.retry` ("Reintentar" / "Retry"), `search.clear` ("Borrar" / "Clear"), `search.capped` ("Mostramos los 50 más recientes: refiná la búsqueda" / "Showing the 50 most recent: refine your search"), `search.paidBy` ("Pagó {{name}}" / "Paid by {{name}}"), `search.everyMonth` ("Cada mes · {{period}}" / "Every month · {{period}}"), `search.settled` ("✓ Saldado" / "✓ Settled"), `search.unsettled` ("Sin saldar" / "Unsettled").

- [ ] **Step 7: Stale-response check** — with the mock delaying `q=ca` 1500ms and `q=cafe` 100ms, type "ca" then "cafe": the list must end on the "cafe" results. Gates, commit:

```bash
git add -A && git commit -m "feat(search): búsqueda que se estira, con resultados en vivo"
```

---

## Task 9: Las lupas en su lugar y limpieza

**Files:**
- Modify: `src/pages/GroupLayout.tsx`, `src/pages/PersonalDashboard.tsx`, `src/components/layout/MobileHeader.tsx`, `src/pages/ExpensesDashboard.tsx`, `src/config/features.ts`, `src/App.tsx`, `CLAUDE.md` (front), i18n
- Delete: `src/pages/SearchPage.tsx`

- [ ] **Step 1: Openers** — every search button calls `openSearch(...)` inside its click:
  - `GroupLayout` capsule: `<CapsuleSlot onClick={() => openSearch({ groupId, groupName: group?.name ?? '' })} aria-label={t('search.open')}>`, always shown (no flag).
  - `PersonalDashboard`: mobile capsule slot and desktop capsule → `openSearch()`; desktop label `t('search.inPersonal')` becomes `t('search.placeholderAll')`.
  - `MobileHeader` (only on `/groups`): a 32px glass search button left of the avatar → `openSearch()`.
  - `ExpensesDashboard` desktop ⌘K chip → `openSearch({ groupId, groupName })`.
- [ ] **Step 2: Remove the flag and the placeholder page** — delete `FEATURE_SEARCH` from `src/config/features.ts` and `vite-env.d.ts`, the `/search` route in `App.tsx`, `SearchPage.tsx`, `search.comingSoon`, `search.title` if unused (`grep -rn "search\.\(comingSoon\|title\|placeholderPersonal\|inPersonal\)" src`).
- [ ] **Step 3: Front `CLAUDE.md`** — replace the "Search and receipts have no backend yet" line with: search = `SearchOverlay` (in `AppShell`, opened via `useSearch().openSearch`), `GET /search/expenses`; month search = `matchesQuery` in `ExpenseListHeader`; receipts still behind `FEATURE_RECEIPTS`.
- [ ] **Step 4: Gates and commit** — `npm run typecheck:ratchet && npm run lint && npm run build`.

```bash
git add -A && git commit -m "feat(search): las lupas abren la búsqueda; sale la pantalla 'Pronto…'"
```

---

## Task 10: Verificación de punta a punta

- [ ] **Step 1: Browser, mocked API** — extend `.playwright-mcp/mock.js` with `/search/expenses` (filters the fixture list with the same rules, returns period/settled) and `/shares/unsettled` (`[{year:2026,month:7}]`). Check at 390px, light and dark:
  1. Grupos → lupa → teclea "luz" → resultados en vivo, chip de período y estado; ✕ vuelve.
  2. Grupo → lupa → placeholder "Buscar en Casa", sin repetir el grupo en las filas; tocar un resultado abre ese mes con el detalle.
  3. Personal → lupa → un fijo personal sale bajo el encabezado del mes, "Cada mes · sep 2026", sin chip de estado.
  4. Lupa del mes: filtra en vivo, combina con "Míos"; "Sin saldar" ya no está.
  5. Selector de mes: atajo "Sin saldar" y punto en julio; tocarlo navega.
  6. Desktop 1280px: ⌘K abre la búsqueda del grupo / general.
- [ ] **Step 2: WebKit iPhone** — la lupa abre el teclado (foco dentro del toque) y nada desborda a 320/390px (`wk.js`).
- [ ] **Step 3: Backend gates** — `git add -A && make lint && make test` (and integration per Task 4).
- [ ] **Step 4: Report** with evidence; push/PR only when the user asks.
