# Carga rápida (atajo de iOS, borradores, pegar captura) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cargar un gasto desde una captura en segundos — atajo de iOS que confirma sin abrir la app, borradores que se acumulan y se terminan en la PWA, y "Pegar captura" dentro de la app.

**Architecture:** Backend: dos tablas nuevas (`expense_drafts`, `shortcut_tokens`), un token opaco solo para los endpoints del atajo, un `QuickCaptureService` que guarda el borrador, lo lee con el parser existente y arma resumen + opciones por grupo, y confirma por el mismo camino que `POST /groups/{id}/expenses/` (extraído a una función compartida). Frontend: cliente `drafts.ts`, página `/drafts`, tarjeta de pendientes, sección "Conectar atajo" en el perfil, y el lanzador del "+" (`GroupExpenseLauncher`) reusado para revisar un borrador y para pegar.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, pytest · React 18 + TS + Vite, react-i18next, lucide-react.

**Spec:** `shared_expense_manager/docs/superpowers/specs/2026-11-13-carga-rapida-atajo-y-borradores-design.md`

## Global Constraints

- Nada se crea sin confirmación explícita; el parser LLM sugiere, la persona decide.
- Respuestas `{ "data": ... }` (`ResponseModel[T]`), camelCase en el wire (`CamelCaseModel`). Money es `float`.
- Imports `from template.xxx import ...`. Routers no tocan SQLAlchemy.
- Token del atajo: opaco, formato `jrn_` + `secrets.token_urlsafe(32)`, guardado como SHA-256 hex, prefijo visible = primeros 8 caracteres del token completo, sin vencimiento, uno activo por miembro, regenerar revoca el anterior. **No** es un JWT y `get_current_member` no lo acepta.
- Ventana de ranking de grupos: 90 días. Máximo 2 opciones de grupo. Grupos archivados por el miembro nunca se ofrecen; `one_time` no se ofrece si el borrador es `credit`.
- División al confirmar sin formulario: `equal` entre todos los miembros actuales del grupo (`participant_ids=None`); pagador = dueño del borrador.
- Imagen: tope 8 MB (`MAX_IMAGE_BYTES` existente); se pone en `NULL` al confirmar o descartar. Los borradores pendientes no vencen.
- Push de pendientes: `title="Jirens"`, `url="/drafts"`, `tag="drafts-pending"`; solo push (sin mail); se manda en `keep` y en lectura fallida.
- Migración nueva `m18_quick_capture`, `down_revision = "m17_due_dates"`.
- UI: componentes y tokens existentes; no inventar barras ni formularios nuevos (ver memoria "Mockups usan la UI real").
- Copy en español rioplatense; claves nuevas en `es.json` y `en.json`.
- Backend: `git add -A` antes de `make lint`. Frontend: `npm run lint`, `npx tsc -b`, `npm run build`.

## Review Focus

1. **Confirmar dos veces** (doble toque en el atajo, reintento de red) → un solo gasto; el segundo responde 409 sin crear nada. *Test en Task 5.*
2. **Borrador ajeno** (otro miembro adivina un `draftId`) → 404 tanto por token del atajo como por JWT. *Tests en Task 5 y Task 6.*
3. **Mes saldado** (la fecha leída cae en un mes ya saldado del grupo elegido) → 409 con el mensaje del backend, el borrador sigue `pending`. *Test en Task 5.*
4. **Token revocado o regenerado** sigue en el atajo viejo → 401 en todos los endpoints del atajo. *Test en Task 2.*
5. **Imagen que no es imagen / vacía** desde el atajo → 400 sin guardar borrador; **imagen ilegible** (parser devuelve `None` o lanza) → borrador `pending` sin monto, `status="unreadable"`, push enviado. *Tests en Task 5.*

---

## Backend — `shared_expense_manager` (rama `feat/carga-rapida`)

### Task 1: Tablas, migración y repositorios

**Files:**
- Modify: `src/template/adapters/orm.py` (al final: `ExpenseDraftModel`, `ShortcutTokenModel`)
- Create: `migrations/versions/m18_quick_capture.py`
- Modify: `src/template/adapters/repositories.py` (al final: `ExpenseDraftRepository`, `ShortcutTokenRepository`; en el repo de gastos: `count_recent_expenses_by_group`)
- Modify: `tests/integration/conftest.py` (`_wipe_tables`: borrar `expense_drafts` y `shortcut_tokens` antes de `members`)
- Modify: `CLAUDE.md` (raíz del monorepo) y `shared_expense_manager/CLAUDE.md`: línea de cadena de migraciones → `m18_quick_capture` (latest)
- Test: `tests/integration/quick_capture/test_repositories.py` (+ `__init__.py`)

**Interfaces:**
- Produces:
  - `ExpenseDraftModel`: `id`, `member_id` (FK members, CASCADE), `status: str` (`"pending"|"confirmed"|"discarded"`, default `"pending"`), `amount: float|None`, `description: str|None`, `category: str|None`, `expense_date: date|None`, `payment_type: str|None`, `installments: int|None`, `currency: str|None`, `confidence: str|None`, `suggested_group_id: int|None` (FK groups, SET NULL), `image: bytes|None` (`LargeBinary`), `image_mime: str|None`, `expense_id: int|None` (FK expenses, SET NULL), `created_at`, `resolved_at: datetime|None`.
  - `ShortcutTokenModel`: `id`, `member_id` (FK members, CASCADE), `token_hash: str` (unique, String(64)), `prefix: str` (String(12)), `created_at`, `last_used_at: datetime|None`, `revoked_at: datetime|None`.
  - `ExpenseDraftRepository(session)`: `add(model) -> ExpenseDraftModel` (flush), `get_owned(draft_id: int, member_id: int) -> ExpenseDraftModel|None`, `get_owned_for_update(draft_id: int, member_id: int) -> ExpenseDraftModel|None` (`with_for_update()`), `list_pending(member_id: int) -> list[ExpenseDraftModel]` (más viejo primero), `commit()`.
  - `ShortcutTokenRepository(session)`: `get_active(member_id) -> ShortcutTokenModel|None`, `find_active_by_hash(token_hash) -> ShortcutTokenModel|None`, `revoke_all(member_id) -> None`, `add(model)`, `touch(model) -> None` (setea `last_used_at`), `commit()`.
  - `SQLAlchemyExpenseRepository.count_recent_expenses_by_group(payer_id: int, since: date, category: str|None = None) -> dict[int, int]` — cuenta filas con `installment_no == 1`, `date >= since`, categoría no interna (`balance`, `prestamo`), filtrada por `category` si viene.

- [ ] **Step 1: Write the failing tests** — `test_pending_drafts_are_owned_and_ordered` (dos miembros, `list_pending(a)` no ve los de `b`, orden por `created_at`), `test_get_owned_hides_other_members_drafts` (`get_owned(id, otro)` → `None`), `test_only_one_active_token_after_revoke_all`, `test_count_recent_expenses_by_group_ignores_old_and_internal` (gastos de hace 100 días y categoría `balance` no cuentan; filtro por `category="supermercado"`).
- [ ] **Step 2: Run** `TEST_DATABASE_URL=<staging> poetry run pytest tests/integration/quick_capture/test_repositories.py -v` → FAIL (import error).
- [ ] **Step 3: Implement** modelos, migración (`op.create_table` ×2 con las mismas columnas, índice en `expense_drafts(member_id, status)`; `downgrade` las borra), repositorios, wipe y CLAUDE.md.
- [ ] **Step 4: Run** el mismo comando → PASS.
- [ ] **Step 5: Commit** `feat(quick-capture): tablas de borradores y tokens del atajo (m18)`.

### Task 2: Token del atajo — servicio, dependencia y endpoints de perfil

**Files:**
- Create: `src/template/service_layer/shortcut_token_service.py`
- Create: `src/template/domain/schemas/quick_capture.py` (schemas de Task 2, 5 y 6)
- Modify: `src/template/entrypoint/member.py` (3 rutas bajo `/members/me/shortcut-token`)
- Modify: `src/template/dependencies.py` (`get_shortcut_token_service`)
- Test: `tests/unit/service/test_shortcut_token_service.py`, `tests/integration/quick_capture/test_shortcut_token_router.py`

**Interfaces:**
- Consumes: `ShortcutTokenRepository` (Task 1).
- Produces:
  - `ShortcutTokenService(repo)`: `issue(member_id: int) -> tuple[str, ShortcutTokenModel]` (revoca los activos, devuelve el token en claro una vez), `status(member_id) -> ShortcutTokenModel|None`, `revoke(member_id) -> None`, `authenticate(raw: str) -> int|None` (member_id; actualiza `last_used_at`; `None` si no empieza con `jrn_`, no existe o está revocado).
  - `get_shortcut_member(authorization: str = Header(...), db=Depends(get_db)) -> Member` en `shortcut_token_service.py` — lee `Bearer jrn_...`, 401 con `WWW-Authenticate: Bearer` si falla.
  - Schemas: `ShortcutTokenStatus(connected: bool, prefix: str|None, created_at: datetime|None, last_used_at: datetime|None)`, `ShortcutTokenIssued(token: str, prefix: str, created_at: datetime)`.
  - Rutas (JWT normal): `GET /api/v1/members/me/shortcut-token` → `ShortcutTokenStatus`; `POST` → 201 `ShortcutTokenIssued`; `DELETE` → 204.

- [ ] **Step 1: Write the failing tests** — unit (repo fake en memoria): `test_issue_returns_plain_token_once_and_stores_only_hash` (`token.startswith("jrn_")`, el modelo guarda `sha256(token).hexdigest()`, `prefix == token[:8]`), `test_issue_revokes_previous`, `test_authenticate_rejects_revoked_and_non_jrn` (un JWT válido → `None`). Integración: `test_profile_flow_issue_status_revoke`, `test_shortcut_token_is_rejected_by_jwt_routes` (`GET /api/v1/members/me` con `Bearer jrn_...` → 401).
- [ ] **Step 2: Run** `poetry run pytest tests/unit/service/test_shortcut_token_service.py -v` → FAIL.
- [ ] **Step 3: Implement** servicio, dependencia, schemas, rutas y factory. Comparar hashes con `hmac.compare_digest`.
- [ ] **Step 4: Run** unit + integración del task → PASS.
- [ ] **Step 5: Commit** `feat(quick-capture): token personal del atajo`.

### Task 3: Crear un gasto con sus efectos, en una sola función

Hoy los efectos de un alta (refresh de archivado, notificaciones, armado de la respuesta) viven dentro del router `create_expense`. El borrador tiene que crear por el mismo camino.

**Files:**
- Create: `src/template/service_layer/expense_creation.py`
- Modify: `src/template/entrypoint/expense.py` (`create_expense` delega)
- Test: los existentes `tests/integration/expense/` y `tests/unit/service/test_push_wiring_guard.py` deben seguir verdes; nuevo `tests/unit/service/test_expense_creation.py`

**Interfaces:**
- Produces: `create_expense_with_effects(*, service: ExpenseService, expense_data: ExpenseCreate, creator: Member, background_tasks: BackgroundTasks, member_service: MemberService, group_service: GroupService, repository: ExpenseRepository, db: Session) -> ExpenseResponse`. Lanza `ValueError` igual que hoy (el router sigue traduciendo "está saldado" → 409, resto → 400).

- [ ] **Step 1: Write the failing test** — `test_create_expense_with_effects_skips_notifications_for_personal_group` y `test_create_expense_with_effects_queues_notification_for_shared_group` (servicios mockeados, `BackgroundTasks()` real, assert sobre `background_tasks.tasks`).
- [ ] **Step 2: Run** → FAIL (módulo no existe).
- [ ] **Step 3: Implement** moviendo el cuerpo del router sin cambiar comportamiento; el router queda en try/except + `ResponseModel(data=...)`.
- [ ] **Step 4: Run** `make test` y `make integration` (suite de expense) → PASS.
- [ ] **Step 5: Commit** `refactor(expenses): alta con efectos reutilizable`.

### Task 4: Opciones de grupo, resumen y textos (lógica pura)

**Files:**
- Create: `src/template/service_layer/quick_capture_text.py`
- Test: `tests/unit/service/test_quick_capture_text.py`

**Interfaces:**
- Produces:
  - `@dataclass GroupCandidate(group_id: int, name: str, group_type: str, member_count: int, recent_count: int, category_count: int)`
  - `pick_options(candidates: list[GroupCandidate], payment_type: str) -> list[GroupCandidate]` — descarta `one_time` si `payment_type == "credit"`; ordena por `recent_count` desc (empate: `group_id` asc, que es orden de creación); toma 2; el primero de la lista resultante es el **sugerido** = el de mayor `category_count` entre esos 2 (empate o 0 → el de mayor `recent_count`).
  - `option_label(candidate: GroupCandidate, amount: float, currency: str) -> str` — personal → `"Personal · todo tuyo"`; si no → `f"{name} · {monto} c/u"` con `monto = round(amount / member_count, 2)`, formateado con `format_amount_es`; USD con prefijo `"US$ "` en lugar de `"$"`.
  - `summary_text(*, category: str, description: str, amount: float, currency: str, payment_type: str, installments: int) -> str` — `"{emoji} {description} · {monto} · pagaste vos · {pago}"` (`pago` = `format_payment_type_es`).
  - `similar_warning(description: str, amount: float, currency: str) -> str` — `"⚠️ Parecido a uno que ya cargaste: {monto} {description}"`.
  - `pending_push_body(drafts: list[tuple[str, float|None, str]]) -> str` — `"Tenés N gastos para revisar"` (N=1 → `"Tenés 1 gasto para revisar"`) + `"\n"` + hasta 2 items `"{descripción} {monto}"` unidos por `" · "` + `" · y K más"` si sobran; un item sin monto se muestra solo con la descripción (o `"Captura sin leer"` si tampoco hay descripción).

- [ ] **Step 1: Write the failing tests** con los valores del spec: Fran y Guada (2 miembros) + Personal → labels `"Fran y Guada · $2.500 c/u"` y `"Personal · todo tuyo"` para `$5.000`; grupo de 3 con `$5.000` → `"… · $1.666,67 c/u"`; credit descarta un `one_time` y entra el tercero; sugerido por categoría gana aunque tenga menos `recent_count`; un solo grupo → 1 opción; push con 3 borradores → `"Tenés 3 gastos para revisar\nSupermercado $5.000 · Nafta $42.300 · y 1 más"`.
- [ ] **Step 2: Run** `poetry run pytest tests/unit/service/test_quick_capture_text.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(quick-capture): opciones de grupo y textos del atajo`.

### Task 5: QuickCaptureService + endpoints del atajo + tag en push

**Files:**
- Create: `src/template/service_layer/quick_capture_service.py`
- Create: `src/template/entrypoint/quick_capture.py` (router `prefix="/quick-capture"`)
- Modify: `src/template/router.py` (registrar), `src/template/dependencies.py` (`get_quick_capture_service`)
- Modify: `src/template/service_layer/expense_draft_service.py` (extraer `validate_image(image_bytes: bytes, mime_type: str) -> None`; `build_expense_draft` la usa)
- Modify: `src/template/service_layer/push_service.py` (`send_to_member(..., tag: str | None = None)` y `send_if_subscribed(..., tag=None)`; el payload incluye `"tag"` solo si viene)
- Modify: `src/template/domain/schemas/quick_capture.py`
- Test: `tests/integration/quick_capture/test_quick_capture_router.py`, `tests/unit/service/test_push_notifications.py` (agregar caso tag)

**Interfaces:**
- Consumes: Tasks 1–4; `build_expense_draft`, `ExpenseService.find_similar_expenses`, `GroupRepository.list_for_member(member_id, include_personal=True)`, `GroupService.list_members`, `PushService`.
- Produces:
  - Schemas: `QuickCaptureAction(label: str, action: Literal["confirm","keep","discard"], group_id: int|None)`, `QuickCaptureResult(draft_id: int, status: Literal["read","unreadable"], summary: str, warning: str|None, actions: list[QuickCaptureAction], message: str|None)`, `QuickCaptureConfirm(group_id: int)`, `QuickCaptureMessage(message: str)`.
  - `QuickCaptureService(db, ...)`: `capture(member: Member, image: bytes, mime: str) -> QuickCaptureResult`; `confirm(member: Member, draft_id: int, group_id: int, background_tasks: BackgroundTasks) -> ExpenseResponse`; `keep(member, draft_id) -> None`; `discard(member, draft_id) -> None`; `notify_pending(member_id: int) -> None`.
  - Rutas (auth `get_shortcut_member`): `POST /api/v1/quick-capture` (multipart `file`) → `QuickCaptureResult`; `POST /api/v1/quick-capture/{draft_id}/confirm` → `QuickCaptureMessage` (`"Gasto creado · {monto} · {grupo}"`); `POST /{draft_id}/keep` → `QuickCaptureMessage` (`"Guardado en borradores"`); `DELETE /{draft_id}` → `QuickCaptureMessage` (`"Descartado"`).
- Comportamiento:
  - `capture`: `validate_image` → 400 sin guardar. Guarda el borrador con imagen. `build_expense_draft` dentro de `try`: `ValueError` o cualquier `Exception` del parser (loguear) → `status="unreadable"`, `actions=[]`, `message="No pude leerla, quedó en borradores"`, `notify_pending`. Si se leyó: arma candidatos (grupos del miembro no archivados + personal, `member_count` de `list_members`, conteos de Task 1 con `since = hoy - 90 días`), `pick_options`, guarda `suggested_group_id` = primero, `warning` = primer parecido encontrado en los grupos ofrecidos (año/mes de la fecha leída), `actions` = opciones de grupo (`"confirm"`) + `{"Editar en la app","keep"}` + `{"Cancelar","discard"}`. Si `amount is None` tras leer → tratar como unreadable.
  - `confirm`: `get_owned_for_update` (None → 404); `status != "pending"` → 409 `"Ese borrador ya se resolvió"`; `amount is None` → 400; miembro no pertenece o archivó el grupo → 400 `"Ese grupo no está disponible"`; arma `ExpenseCreate` (payer = miembro, `split_strategy={"type":"equal"}`, categoría/fecha/pago/cuotas/moneda del borrador) y llama `create_expense_with_effects`; `ValueError` con "está saldado" → 409, otros → 400 (el borrador sigue `pending`); éxito → `status="confirmed"`, `expense_id`, `image=None`, `resolved_at`, commit.
  - `keep`: 404 si no es suyo; si `pending` → `notify_pending`. `discard`: `status="discarded"`, `image=None`, `resolved_at`.
  - `notify_pending`: lista pendientes; si hay, `PushService.send_if_subscribed(member_id, "Jirens", pending_push_body(...), "/drafts", tag="drafts-pending")`.

- [ ] **Step 1: Write the failing tests** (parser parcheado en `template.service_layer.expense_draft_service.parse_image_expense`; token emitido vía `POST /members/me/shortcut-token`): `test_capture_returns_summary_and_group_actions_without_creating` (0 gastos tras capture; actions = 2 grupos + keep + discard; labels de Task 4), `test_capture_rejects_non_image_without_saving`, `test_unreadable_capture_keeps_draft_and_pushes` (parser → `None`; `PushService.send_if_subscribed` parcheado y llamado con `tag="drafts-pending"`), `test_confirm_creates_one_expense_and_second_confirm_is_409`, `test_confirm_into_settled_month_is_409_and_draft_stays_pending`, `test_confirm_someone_elses_draft_is_404`, `test_confirm_in_personal_group_assigns_full_amount`, `test_credit_capture_does_not_offer_one_time_group`, `test_similar_expense_adds_warning`, `test_revoked_token_gets_401` (token regenerado: el viejo → 401 en capture), y en push: `test_payload_includes_tag_only_when_given`.
- [ ] **Step 2: Run** `TEST_DATABASE_URL=<staging> poetry run pytest tests/integration/quick_capture -v` → FAIL.
- [ ] **Step 3: Implement** servicio, rutas, `validate_image`, tag en push.
- [ ] **Step 4: Run** → PASS; `make test` → PASS.
- [ ] **Step 5: Commit** `feat(quick-capture): capturar, confirmar y descartar desde el atajo`.

### Task 6: Endpoints de borradores para la PWA

**Files:**
- Create: `src/template/entrypoint/drafts.py` (router `prefix="/drafts"`, JWT `get_current_member`)
- Modify: `src/template/router.py`, `src/template/domain/schemas/quick_capture.py`
- Test: `tests/integration/quick_capture/test_drafts_router.py`

**Interfaces:**
- Consumes: `QuickCaptureService` (Task 5).
- Produces:
  - Schema `DraftResponse(id, amount: float|None, description: str|None, category: str|None, date: date|None, payment_type: str|None, installments: int|None, currency: str|None, confidence: str|None, suggested_group_id: int|None, suggested_group_name: str|None, has_image: bool, created_at: datetime)`.
  - `GET /api/v1/drafts` → `list[DraftResponse]` (pendientes, más viejo primero).
  - `GET /api/v1/drafts/{id}/image` → `Response(content=bytes, media_type=image_mime)`; 404 si no es suyo o no hay imagen. (Fuera del sobre `{data}`: es binario.)
  - `POST /api/v1/drafts/{id}/confirm` body `QuickCaptureConfirm` → `ExpenseResponse` (mismo `QuickCaptureService.confirm`).
  - `POST /api/v1/drafts/{id}/resolve` → 204 — la PWA guardó el gasto con el formulario; marca `confirmed`, `image=None`, `resolved_at` (sin `expense_id`). 409 si no está `pending`.
  - `DELETE /api/v1/drafts/{id}` → 204 (`discard`).
  - `QuickCaptureService.resolve(member, draft_id) -> None` y `list_pending_responses(member) -> list[DraftResponse]` agregados en este task.

- [ ] **Step 1: Write the failing tests** — `test_list_only_my_pending_drafts`, `test_image_endpoint_returns_bytes_and_404_for_others`, `test_resolve_then_list_is_empty_and_image_is_cleared`, `test_confirm_from_pwa_creates_expense_in_suggested_group`, `test_drafts_routes_reject_shortcut_token` (`Bearer jrn_...` → 401).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(quick-capture): borradores para la PWA`.

### Task 7: Documentación del atajo y del API

**Files:**
- Create: `docs/quick-capture-shortcut.md` — cómo armar el atajo "Cargar gasto" en Atajos: (1) pregunta de importación "Token" (texto); (2) "Tomar captura de pantalla" (y entrada desde hoja de compartir: imágenes); (3) "Cambiar tamaño de imagen" ancho 1280 + "Convertir imagen" JPEG; (4) "Obtener contenido de URL" POST `{BASE}/api/v1/quick-capture`, header `Authorization: Bearer <Token>`, cuerpo formulario con campo `file`; (5) si `data.status == "unreadable"` → "Mostrar notificación" con `data.message` y terminar; (6) "Elegir del menú" con prompt `summary` (+ `warning`) usando los `label` de `data.actions`; (7) según `action`: `confirm` → POST `/{draftId}/confirm` `{"groupId": …}`, `keep` → POST `/{draftId}/keep`, `discard` → DELETE `/{draftId}`; (8) "Mostrar notificación" con `data.message` (o el `detail` del error). Incluir cómo asignarlo a Toque posterior y la advertencia de no compartir un atajo con token puesto.
- Modify: `shared_expense_manager/CLAUDE.md` (API surface: Quick capture, Drafts, `/members/me/shortcut-token`) y `CLAUDE.md` raíz (data model: `ExpenseDraft`, token del atajo; mención en "When changing the API surface" de `src/api/drafts.ts`).

- [ ] **Step 1:** Escribir los dos cambios.
- [ ] **Step 2:** `git add -A && make lint` → todo `Passed`.
- [ ] **Step 3: Commit** `docs(quick-capture): armado del atajo y superficie del API`.

---

## Frontend — `shared_expense_front` (rama `feat/carga-rapida` desde `origin/main` actualizado)

### Task 8: Clientes de API y tipos

**Files:**
- Create: `src/api/drafts.ts`, `src/api/shortcutToken.ts`
- Modify: `src/types/expense.ts` (o el archivo de tipos que corresponda) — `Draft`, `ShortcutTokenStatus`, `ShortcutTokenIssued`

**Interfaces:**
- Produces (fetch con bearer a mano, como `dueDates.ts`):
  - `getDrafts(): Promise<Draft[]>`, `getDraftImage(id: number): Promise<File>` (blob → `File` con nombre `captura-{id}.jpg` y el mime de la respuesta), `confirmDraft(id: number, groupId: number): Promise<void>` (lanza `Error(detail)`), `resolveDraft(id: number): Promise<void>`, `discardDraft(id: number): Promise<void>`.
  - `getShortcutToken(): Promise<ShortcutTokenStatus>`, `issueShortcutToken(): Promise<ShortcutTokenIssued>`, `revokeShortcutToken(): Promise<void>`.
  - `Draft` = camelCase de `DraftResponse` (Task 6).

- [ ] **Step 1:** Implementar.
- [ ] **Step 2:** `npm run lint && npx tsc -b` → sin errores.
- [ ] **Step 3: Commit** `feat(quick-capture): clientes de borradores y token del atajo`.

### Task 9: Revisar un borrador con el lanzador existente

**Files:**
- Modify: `src/hooks/useReceiptScan.ts` — `scan(file, apply, preRead?: ExpenseDraft)`: con `preRead` no llama a `parseExpenseImage`, aplica ese borrador.
- Modify: `src/components/expenses/AddExpenseDialog.tsx`, `src/components/personal/PersonalExpenseSheet.tsx` — prop opcional `scanDraft?: ExpenseDraft | null`, pasada a `scan.scan(scanFile, apply, scanDraft ?? undefined)`.
- Modify: `src/components/layout/GroupExpenseLauncher.tsx` — props opcionales `scanDraft?: ExpenseDraft | null`, `suggestedGroupId?: number | null` (en el picker, el grupo sugerido —o Personal si es el personal— lleva una pastilla "Sugerido" con el estilo de `FromPhotoPill` y va primero), `onSaved?: () => void` (se llama en `handleDone` del grupo y en `handleSaved` del personal).

**Interfaces:**
- Consumes: `ExpenseDraft` (existente en `src/api/expenses.ts`).
- Produces: `GroupExpenseLauncher` con `scanDraft`, `suggestedGroupId`, `onSaved` — Task 10 lo abre así: `scanFile` = `getDraftImage(id)`, `scanDraft` = el borrador mapeado a `ExpenseDraft` (`amount`, `description ?? ''`, `category ?? 'otros'`, `date ?? hoy`, `paymentType ?? 'debit'`, `installments ?? 1`, `currency ?? 'ARS'`, `confidence ?? 'low'`).
- Decisión del plan: el "selector de grupo" del spec **es el picker que ya tiene el lanzador** (grupos + Personal), no una fila de chips nueva — cumple "no inventar UI" y ya abre el formulario correcto por tipo de grupo.

- [ ] **Step 1:** Implementar sin cambiar el comportamiento cuando las props nuevas no vienen (escanear desde el "+" sigue igual).
- [ ] **Step 2:** `npm run lint && npx tsc -b` → sin errores.
- [ ] **Step 3:** Verificación manual en `npm run dev`: escanear desde el "+" sigue leyendo la foto (una llamada a `parse-image` en Network).
- [ ] **Step 4: Commit** `feat(quick-capture): el lanzador abre un borrador ya leído`.

### Task 10: Página de borradores, tarjeta de pendientes y ruta

**Files:**
- Create: `src/pages/DraftsPage.tsx` (ruta `/drafts`, dentro de `AppShell`)
- Create: `src/components/expenses/DraftsCard.tsx`
- Create: `src/hooks/useDrafts.ts` — `{ drafts, loading, refetch }`; refetch al volver el foco a la ventana
- Modify: `src/App.tsx` (ruta), `src/pages/GroupSelectorPage.tsx` y `src/pages/PersonalDashboard.tsx` (tarjeta arriba del contenido), `src/i18n/locales/es.json`, `en.json`

**Interfaces:**
- Consumes: Task 8 y Task 9.
- `DraftsCard`: no renderiza nada con 0 pendientes; con N: título `"{N} gastos para revisar"` (1 → singular), subtítulo con antigüedad del más viejo (`"el más viejo de hace 2 días"`), botón "Revisar" → `navigate('/drafts')`. Estilo de tarjeta existente (`bg-brand-wash`, `border-brand-wash-line`, `rounded-card`).
- `DraftsPage`: encabezado con `FloatingTopBar` y flecha `navigate(-1)` (memoria iOS back swipe); una tarjeta por borrador con miniatura (`getDraftImage` → object URL), descripción, monto (`useCurrency().formatAmount`), grupo sugerido, pago. Acciones:
  - **Confirmar** solo si `amount != null && suggestedGroupId != null` → `confirmDraft`; error → `toast.error(message)`; éxito → `island.success()`, `requestExpenseRefresh()`, refetch.
  - **Revisar** (o **Completar** si `amount == null`) → abre `GroupExpenseLauncher` (`mode="expense"`, sin `presetGroupId`, `scanFile`, `scanDraft`, `suggestedGroupId`, `onSaved={() => resolveDraft(id).then(refetch)}`).
  - **Descartar** → confirmación inline en la tarjeta (dos toques, sin `confirm()`), `discardDraft`, refetch.
  - Lista vacía → texto "No tenés gastos para revisar" y volver.

- [ ] **Step 1:** Implementar.
- [ ] **Step 2:** `npm run lint && npx tsc -b && npm run build` → sin errores.
- [ ] **Step 3:** Verificación manual (backend local + un borrador creado con `curl` contra `/api/v1/quick-capture`): tarjeta visible en `/groups` y `/personal`; Confirmar crea el gasto; Revisar → picker con "Sugerido" → formulario precargado sin llamar a `parse-image` → guardar → el borrador desaparece; Descartar lo saca. Probar a 390 px y 320 px en WebKit (memoria grid/minmax).
- [ ] **Step 4: Commit** `feat(quick-capture): borradores en la PWA`.

### Task 11: Perfil → "Conectar atajo"

**Files:**
- Create: `src/components/ui/ShortcutCard.tsx` (al lado de `PushCard`, mismo patrón)
- Modify: `src/pages/ProfilePage.tsx` (debajo de `<PushCard />`), `src/config/env.ts` (`shortcutInstallUrl` desde `VITE_SHORTCUT_URL`, opcional), locales

**Interfaces:**
- Consumes: Task 8.
- Estados: sin token → botón "Conectar atajo" → `issueShortcutToken` → muestra el token completo una sola vez con botón "Copiar" (`navigator.clipboard.writeText`), el link "Instalar el atajo" (solo si `shortcutInstallUrl`) y tres pasos cortos (instalar y pegar el token · Ajustes → Accesibilidad → Tocar → Toque posterior → Doble toque → "Cargar gasto" · no compartas tu atajo, cada uno genera el suyo). Con token → "Atajo conectado · último uso hace X" (o "sin usar todavía"), "Generar uno nuevo" (confirmación inline: el atajo viejo deja de andar) y "Desconectar".

- [ ] **Step 1:** Implementar.
- [ ] **Step 2:** `npm run lint && npx tsc -b` → sin errores.
- [ ] **Step 3:** Verificación manual del ciclo conectar → copiar → regenerar → desconectar contra backend local.
- [ ] **Step 4: Commit** `feat(quick-capture): conectar el atajo desde el perfil`.

### Task 12: Pegar captura + tag en el service worker

**Files:**
- Create: `src/utils/clipboardImage.ts` — `readClipboardImage(): Promise<File | null>` (`navigator.clipboard.read()`, primer item con tipo `image/*` → `File` `captura-pegada.png`; sin soporte, sin permiso o sin imagen → `null`)
- Modify: `src/components/layout/FloatingTabBar.tsx` — ítem "Pegar captura" (icono `ClipboardPaste`) en `menuItems` justo después de `scanItem`; `onClick` lee el portapapeles **en el mismo toque** y llama `openLauncher('expense', groupId ?? undefined, file)`; sin imagen → `toast(t('paste.empty'))`
- Modify: `src/components/personal/PersonalAddLauncher.tsx` / `PersonalAddMatrix.tsx` — la misma opción en el panel personal (setea `scanFile` como hace escanear)
- Modify: `public/sw.js` — `showNotification(..., { tag: payload.tag, renotify: Boolean(payload.tag) })` cuando venga `tag`
- Modify: locales

**Interfaces:**
- Consumes: el camino `scanFile` existente (no crea borrador; usa `parse-image` como subir foto).
- Decisión del plan: la opción se muestra siempre (detectar si hay imagen exige leer el portapapeles, y en iOS eso muestra el botón de permiso); sin imagen avisa con un toast.

- [ ] **Step 1:** Implementar.
- [ ] **Step 2:** `npm run lint && npx tsc -b && npm run build` → sin errores.
- [ ] **Step 3:** Verificación manual: copiar una imagen → "+" → Pegar captura → "Leyendo…" → formulario precargado; sin imagen copiada → toast. En iPhone (staging): "Copiar y eliminar" en el editor de capturas → pegar.
- [ ] **Step 4: Commit** `feat(quick-capture): pegar una captura y avisos que se reemplazan`.

---

## Cierre

### Task 13: Gates, migración en staging y revisión

- [ ] **Step 1:** Backend: `git add -A && make lint && make test && make integration` → todo verde.
- [ ] **Step 2:** Frontend: `npm run lint && npx tsc -b && npm run build` → sin errores.
- [ ] **Step 3:** `DATABASE_URL=<staging neon> poetry run alembic upgrade head` (o `alembic stamp m18_quick_capture` si `create_all` ya creó las tablas: verificar con `\d expense_drafts` antes).
- [ ] **Step 4:** Prueba punta a punta en staging desde el iPhone: conectar atajo en el perfil, armar el atajo según `docs/quick-capture-shortcut.md`, doble toque → menú → crear en cada grupo; "Editar en la app" → push → `/drafts` → revisar y guardar.
- [ ] **Step 5:** `superpowers:requesting-code-review` sobre ambas ramas; resolver hallazgos.
- [ ] **Step 6:** `superpowers:finishing-a-development-branch` (PRs en cada repo; producción solo cuando el usuario lo pida, con migración en prod Neon antes).
