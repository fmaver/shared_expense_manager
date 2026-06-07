# shared_expense_manager — CLAUDE.md

Personal expense tracker for N members (originally Fran and Guada). Tracks expenses over time, splits costs, and settles balances by month. Sends WhatsApp and email notifications when expenses are added. Companion frontend lives at `/Users/franciscomaver/Documents/shared_expenses/shared_expense_front`.

---

## Tech stack

- **Runtime**: Python 3.10+ (CI pins 3.11), managed by **Poetry**
- **Framework**: FastAPI + Uvicorn
- **DB / ORM**: PostgreSQL, SQLAlchemy 2.0 (declarative `Mapped`), migrations via Alembic
- **Validation**: Pydantic v2 + pydantic-settings
- **Auth**: OAuth2 password flow + JWT (python-jose), bcrypt passwords (passlib)
- **Notifications**: WhatsApp Cloud API (Meta), SMTP email
- **Other**: fpdf (PDF generation), python-dateutil (relativedelta for installment dates)
- **Tooling**: pytest, pre-commit (black, isort, pylint, flake8, mypy), Makefile

---

## How to run

```bash
# Local
poetry install
poetry run python -m template.main        # → http://localhost:8000, docs at /docs

# Docker
docker-compose up                          # starts FastAPI + Postgres 15

# Tests
make test                                  # unit tests only (no DB required)
make cover                                 # unit tests + coverage report
make integration                           # integration tests (requires TEST_DATABASE_URL)
make lint                                  # pre-commit --all-files
```

Alembic migrations: `DATABASE_URL="..." alembic upgrade head` (always pass the URL explicitly for Neon targets).

---

## Package naming gotcha

The Poetry package is named **`template`** (inherited from the upstream `cosmic-fastapi` template). All source lives under `src/template/` and all imports look like `from template.xxx import ...`. Do not rename this in passing — it would be a large refactor.

---

## Architecture

Clean Architecture / Cosmic Python layering:

```
entrypoint (routers)
    ↓
service_layer (use cases / application services)
    ↓
adapters (repositories, ORM, DB session)
    ↓
domain (models, schemas, split strategies)
```

**Rule**: routers must never touch SQLAlchemy directly. They call services injected via `Depends(get_*_service)` in `dependencies.py`.

---

## Directory map

```
src/template/
├── main.py              # entry point — loads .env, starts uvicorn
├── asgi.py              # FastAPI app factory + lifespan (creates tables, seeds members)
├── router.py            # aggregates all v1 routers under /api/v1
├── dependencies.py      # FastAPI Depends() factories for services and repos
├── version.py
├── settings/            # pydantic-settings: ApplicationSettings, UvicornSettings, DatabaseSettings
├── adapters/
│   ├── orm.py           # SQLAlchemy ORM models (Member, Expense, MonthlyShare,
│   │                    #   ChatSession, ProcessedWhatsappMessage)
│   ├── repositories.py  # repository implementations (translate ORM ↔ domain)
│   └── database.py      # engine + SessionLocal factory
├── domain/
│   ├── models/          # domain entities + business logic
│   │   ├── models.py    # Expense, MonthlyShare (with recalculate_balances)
│   │   ├── expense_manager.py   # ExpenseManager aggregate root
│   │   ├── member.py    # Member
│   │   ├── group.py     # Group, GroupMembership
│   │   ├── category.py  # Category (static list, NOT a DB table)
│   │   ├── enums.py     # shared enums (e.g. NotificationPreference)
│   │   ├── formatters.py  # format_amount_es, format_date_es, format_category_es, etc.
│   │   ├── pdf_builder.py  # PDF generation via fpdf; _sanitize() for non-latin-1 chars
│   │   └── split.py     # SplitStrategy, EqualSplit(participant_ids?), PercentageSplit, ExactAmountsSplit
│   ├── schemas/         # Pydantic request/response DTOs
│   └── schema_model.py  # CamelCaseModel + ResponseModel[T] generic wrapper
├── service_layer/
│   ├── expense_service.py
│   ├── group_service.py
│   ├── invitation_service.py    # InvitationService + GroupJoinLinkService
│   ├── member_service.py
│   ├── auth_service.py
│   ├── notification_service.py
│   ├── quick_expense_parser.py  # LLM free-text parser → ParsedExpense dataclass
│   ├── whatsapp_client.py       # WhatsAppClient Protocol + MetaWhatsAppClient
│   ├── whatsapp_invite_client.py  # MetaWhatsAppInviteClient for invitation messages
│   ├── whatsapp_service.py      # chatbot state machine (uses WhatsAppClient via DI)
│   └── initialization.py        # seeds default members on startup
└── entrypoint/
    ├── expense.py
    ├── monthly_share.py
    ├── member.py
    ├── auth.py
    ├── category.py
    ├── group.py         # /api/v1/groups — CRUD, membership, invitations, join-link
    ├── invitation.py    # public endpoints: resolve, accept, join
    ├── monitor.py       # / and /liveness, /readiness
    └── whatsapp_bot.py  # Meta webhook: acks immediately, processes in BackgroundTask

tests/
├── conftest.py          # unit test fixtures (no DB — sets DATABASE_URL before imports)
├── fakes/
│   └── fake_whatsapp_client.py  # FakeWhatsAppClient — records sent messages for assertions
├── integration/
│   ├── conftest.py      # DB fixtures: _create_schema (session), clean_tables (per-test),
│   │                    #   fake_wpp, client, auth_headers
│   ├── auth/test_auth.py
│   ├── expense/test_expense_router.py
│   └── whatsapp/
│       ├── test_chatbot_idempotency.py
│       └── test_chatbot_state_machine.py
└── unit/                # existing unit tests for domain/split/expense_manager
```

---

## Domain model

| Entity | Key fields | Notes |
|---|---|---|
| `Member` | id, name, telephone, email, hashed_password, notification_preference, last_wpp_chat_datetime | `notification_preference`: WHATSAPP / EMAIL / NONE; `is_stub` computed (`hashed_password is None`) |
| `Group` | id, name, status, group_type, created_at | Container for members and expenses |
| `GroupMembership` | group_id, member_id | Many-to-many join table |
| `Expense` | id, description, amount, date, category, payer_id, payment_type, installments, installment_no, split_strategy (JSON), parent_expense_id, group_id | `parent_expense_id` self-FK, cascade delete |
| `MonthlyShare` | year, month, is_settled, balances (JSON dict member_id→float), expenses, group_id | owns `recalculate_balances` logic |
| `Category` | name, emoji, is_internal | **Not a DB table** — class-level static list in `category.py` |
| `SplitStrategy` | abstract | `EqualSplit(participant_ids?)` (subset or all members), `PercentageSplit` (must sum to 100 ±0.01), `ExactAmountsSplit(amounts)` (must sum to expense total) |
| `ExpenseManager` | — | aggregate root; orchestrates create/update/delete, settlement, monthly share recalc |
| `ChatSession` | telephone (PK), estado, expense_data (JSON), updated_at | DB-backed chatbot state; `group_id` stored here for multi-group users |
| `ProcessedWhatsappMessage` | message_id (PK), processed_at | Idempotency table — prevents duplicate processing on Meta retries |
| `Invitation` | id, token, group_id, stub_member_id, channel, status, expires_at | Pending invite; creates a stub `Member` on creation; accept upgrades stub to full member |
| `GroupJoinLink` | id, group_id, token, created_by_member_id | Shareable open-join URL; `rotate` invalidates old token |

**Member bootstrapping** — `InitializationService` reads `MEMBERS_BOOTSTRAP_JSON` (a JSON array of `{name, email, telephone}` objects) and upserts by email on startup. If unset (production default), no seeding runs — existing rows (e.g. Fran at id=1, Guada at id=2 in prod) are untouched. New members register via `POST /api/v1/auth/register`.

---

## WhatsApp / chatbot architecture

The chatbot was refactored (M3) for testability and to fix two production bugs:

### WhatsAppClient protocol
`src/template/service_layer/whatsapp_client.py` defines the `WhatsAppClient` Protocol with methods: `send_text`, `send_template`, `upload_media`, `download_media`, `mark_message_read`. `MetaWhatsAppClient` is the real implementation; `FakeWhatsAppClient` (in `tests/fakes/`) is the test double — it records sent messages for assertions.

`WhatsAppService` receives the client via constructor injection, wired through `dependencies.py → get_whatsapp_client()`. Tests override this dependency with `FakeWhatsAppClient`.

### Webhook idempotency
Before processing any inbound message, the webhook handler inserts `message.id` into `processed_wpp_messages` with `ON CONFLICT DO NOTHING`. If the row already existed, processing is skipped. This eliminates the duplicate-response bug caused by Meta retrying during Render cold-boot.

### Immediate webhook ack
`POST /webhook` returns `200 OK` immediately and processes the chatbot logic in a `BackgroundTask`. Meta's 20-second timeout is never hit, so Meta never retries on slow cold starts.

### DB-backed chat state
`ChatSession` (keyed by telephone) replaces the old module-level `estado_actual` dict. State survives restarts and is safe across concurrent requests.

### Phone number normalisation
Incoming Meta webhooks send numbers as `549XXXXXXXXXX`; the `replace_start()` helper in `whatsapp_service.py` strips the `9` to produce `54XXXXXXXXXX` for DB lookup. Keep this in mind when writing test fixtures.

### Group-aware chatbot
When a user belongs to multiple groups, the chatbot prompts them to select a group at session start via `get_multi_group_member_ids`. The chosen `group_id` is stored in `ChatSession.expense_data` and attached to every expense created during that session.

`list_for_member` is called with `include_personal=True` in the webhook, so personal groups appear in the selector alongside shared groups.

### Personal group flows
When the active group is `GroupType.PERSONAL`, `administrar_chatbot` sets `is_personal = service.is_personal_group()` and adapts all flows:

- **Greetings menu**: shows `["💸 Cargar Gasto", "🔁 Gasto Recurrente", "💰 Cargar Ingreso"]` — hides "Prestar Plata", "Generar Balance", "Saldar Cuentas".
- **Regular personal expense** (`cargar gasto`): payer auto-set to current member, split auto-set to equal; confirmation summary omits Pagador and División lines; `edit_pagador` is filtered from the edit menu.
- **Personal recurring expense** (`gasto recurrente personal`): separate flow, no payment type, no payer, no split. Steps: amount → description → category → start month (MM/AAAA) → confirm. Saves via `RecurringPersonalExpenseRepository.create` + `upsert_instance`. State: `esperando_mes_inicio_recurrente_personal` → `esperando_confirmacion_recurrente_personal`.
- **Income** (`cargar ingreso`): variable (one-time, current month) or recurring (with start month). Saves via `IncomeRepository.create_variable_instance` or `create_recurring` + `upsert_recurring_instance`. States: `esperando_tipo_ingreso` → `esperando_monto_ingreso` → `esperando_descripcion_ingreso` → [`esperando_mes_inicio_ingreso`] → `esperando_confirmacion_ingreso`.

Notifications are already suppressed for personal groups throughout the codebase (`is_personal_group()` checks in `notification_service.py` and the WhatsApp chatbot).

### Quick-expense parser (LLM)
Free-text messages like "gasté 500 en comida" bypass the step-by-step flow. `service_layer/quick_expense_parser.py::parse_quick_expense` sends the message to the Claude API and returns a `ParsedExpense` dataclass (amount, description, category, payer_id, date, payment_type, installments, optional is_loan / split_strategy). If parsing succeeds, the chatbot skips to the confirmation step.

---

## API surface

All routes under `/api/v1` except monitor and webhook.

**Auth** `/api/v1/auth`
- `POST /register` — create member
- `POST /token` — login (OAuth2 form, returns JWT)
- `POST /initial-password` — set password for legacy seeded members

**Members** `/api/v1/members`
- `GET /` — list all
- `GET /me`, `PATCH /me` — current user profile (JWT required)
- `POST /me/password` — change password

**Expenses** `/api/v1/expenses`
- `POST /` — create (fires WhatsApp/email notification via BackgroundTasks)
- `GET /{expense_id}`, `PUT /{expense_id}`, `DELETE /{expense_id}`
- `GET /{expense_id}/parent`

**Monthly Shares** `/api/v1/shares`
- `GET /{year}/{month}`
- `POST /settle/{year}/{month}` — close out, generate balancing expenses
- `POST /unsettle/{year}/{month}` — reopen: delete `balance`-category expenses, set `is_settled=False`, recalculate
- `POST /recalculate/{year}/{month}`

**Groups** `/api/v1/groups`
- `POST /` — create group (creator becomes first member)
- `GET /` — list groups the current member belongs to
- `GET /{group_id}`, `PUT /{group_id}` — get/rename group
- `GET /{group_id}/members` — list members
- `POST /{group_id}/members/invite` — legacy auto-accept invite by email
- `POST /{group_id}/invitations` — create invitation (email or WhatsApp, creates stub member)
- `GET /{group_id}/invitations` — list pending invitations
- `DELETE /{group_id}/invitations/{token}` — revoke invitation
- `POST /{group_id}/join-link` — get or create shareable join link
- `POST /{group_id}/join-link/rotate` — invalidate old link, return new one
- `DELETE /{group_id}/members/leave` — leave group (blocked if outstanding balance in any unsettled month)

**Invitations / join links** (public — no auth required)
- `GET /invitations/resolve/{token}` — resolve invitation token (returns group + stub member info)
- `POST /invitations/{token}/accept` — accept invitation; existing members send JWT, new stubs provide password
- `GET /join/resolve/{token}` — resolve join-link token
- `POST /join/{token}` — register a new member and join the group

**Categories** `/api/v1/categories`
- `GET /`, `GET /with-emojis`

**Monitor** (root)
- `GET /` → 301 → `/docs`
- `GET /liveness`, `GET /readiness`

**WhatsApp webhook** (root)
- `GET /webhook` — Meta verification
- `POST /webhook` — acks 200 immediately; chatbot runs in BackgroundTask

---

## Conventions that will bite you

- **Response envelope**: every response is `ResponseModel[T]` → `{ "data": ... }`. Set `response_model=ResponseModel[YourSchema]` on every route.
- **camelCase on the wire**: `CamelCaseModel` aliases snake_case → camelCase. `model_dump()` defaults to `by_alias=True`. The frontend expects camelCase.
- **Money is `float`** (not Decimal/cents). `EqualSplit` and `PercentageSplit` round to 2 decimals; `PercentageSplit` adds rounding discrepancy to the highest-percentage member.
- **Credit-card installments**: a credit expense with N installments is expanded into N rows — parent (installment 1, date = expense.date + 1 month) + N-1 children linked via `parent_expense_id`. Description becomes `"<desc> (k/N)"`. Monthly shares for all affected months are auto-created/recalculated. Cascade delete on `parent_expense_id` removes children automatically.
- **Internal categories**: `balance` (auto-generated by settle) and `prestamo` are hidden from `GET /categories`. Don't expose them in the UI.
- **Datetimes**: `last_wpp_chat_datetime` is timezone-aware UTC. Always produce timezone-aware datetimes when doing arithmetic against it.
- **WhatsApp 24-hour window rule**: if `now - member.last_wpp_chat_datetime >= 1 day` (or never set), Meta requires a pre-approved template. Template name: `expense_notification`, locale `es_AR`. Within the window, free-form text is allowed.
- **DB tables created on startup AND Alembic migrations both exist** — they coexist by design. The Alembic baseline is `baseline_baseline_20250318.py`. Migration chain: `m3_add_chat_sessions_and_processed_messages` → `m4_reconcile_schema` → `m5_rename_compras_to_supermercado` → `m6_add_groups_schema` → `m7_migrate_to_default_group` → `m8_drop_old_monthly_shares_unique` → `m9_invitations_and_stubs` → `m10_personal_groups_income` → `m11_recurring_income_start_month` → `m12_recurring_personal_expenses` → `m13_recurring_group_expenses` (latest).
- **Default members re-seeded every startup** — safe because `InitializationService` checks for existence first.
- **`get_expense` raises `ValueError` for missing IDs** — the expense endpoint catches this as HTTP 400, not 404. Integration tests should assert `status_code in (400, 404)` for the not-found case.
- **`group_type` from `list_for_member` is a plain string**, not a `GroupType` enum. Never call `.value` on it directly — use `getattr(gt, "value", gt)` or compare with the string `"personal"` directly. See `handle_greetings` in `whatsapp_service.py` for the canonical pattern.
- **`ChatSession` top-level state keys** — the session DB column only stores `expense_data` and `estado`. Any extra top-level key (e.g. `group_id`, `group_name`) must be listed in `_SESSION_TOPLEVEL_KEYS` in `repositories.py` to survive across requests; they are serialised with a `_sess_` prefix and unpacked on load. Currently: `group_id`, `group_name`, `known_group_ids`, `pending_invitation_token`. New persistent session fields must be added there.

---

## Testing

### Unit tests (`make cover`)
- Run with `pytest` (no DB needed). `tests/conftest.py` sets `DATABASE_ENV=PROD` and a fallback `DATABASE_URL` before any import so the app can be imported safely.
- `pyproject.toml` has `addopts = "--ignore=tests/integration"` so unit test targets never accidentally pick up integration tests.

### Integration tests (`make integration`)
- Require a live PostgreSQL instance. Set `TEST_DATABASE_URL` env var before running.
- `tests/integration/conftest.py` fixtures:
  - `_create_schema` (session-scoped, autouse): runs the app lifespan once via `TestClient` to call `create_all`. With `MEMBERS_BOOTSTRAP_JSON` unset in test env, no seeding runs.
  - `clean_tables` (function-scoped, autouse): wipes all rows from members, expenses, monthly_shares, chat_sessions, processed_wpp_messages after each test. No `setval` needed — tests register members via the API and use their returned IDs.
  - `client`: creates a fresh `TestClient` per test with `FakeWhatsAppClient` injected.
  - `auth_headers`: registers `tester@example.com` and returns a JWT header dict.
- In CI, the `integration` job spins up a `postgres:15` service container; no Alembic migration is run (tables are created by `create_all` via lifespan).

### Fakes
- `FakeWhatsAppClient` in `tests/fakes/fake_whatsapp_client.py` records every `send_text` / `send_template` call. Assert on `fake_wpp.messages` in chatbot tests.

---

## Configuration / env vars

Loaded from `.env` via `python-dotenv` + `pydantic-settings`.

| Var | Purpose |
|---|---|
| `DATABASE_ENV` | `QA` (default, local docker) or `PROD` (Render) |
| `QA_DATABASE_URL` | local/staging postgres URL |
| `DATABASE_URL` | prod postgres URL (Render-provided) |
| `NEON_DATABASE_URL` | Neon serverless postgres — used for Alembic migrations |
| `WHATSAPP_TOKEN` | Meta Cloud API bearer token |
| `WHATSAPP_URL` | Meta messages endpoint |
| `WHATSAPP_URL_MEDIA` | Meta media upload endpoint |
| `TOKEN` | Meta webhook verification token |
| `SENDGRID_API_KEY` | SendGrid API key for email notifications (leave unset to disable email) |
| `SENDGRID_FROM_EMAIL` | Verified sender address used as the "From" field in SendGrid emails |
| `STORAGE_PATH` | Directory for generated PDFs |

> **Note:** `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` are no longer used.
> Remove them from Render if they are set. Email now goes through SendGrid's HTTP API (port 443),
> which works on Render (direct SMTP on port 587 is blocked by the platform).

---

Ops runbooks (SendGrid one-time setup, staging WhatsApp setup): see `docs/operations.md`.

---

## Frontend integration

Companion app: `/Users/franciscomaver/Documents/shared_expenses/shared_expense_front`
- React 18 + TypeScript + Vite, runs on port **5173** (`npm run dev`)
- Backend URL via `VITE_API_URL` env var (defaults to `http://localhost:8000`)
- Hand-written API clients in `src/api/` (no codegen). Uses both `axios` and `fetch`.
- Auth: stores JWT in `localStorage` key `token`; sets axios default header on login.
- **When you change the API surface** (add/rename/remove an endpoint, change a request/response shape), cross-check `src/api/` in the companion app.
- Known issue: `fetch`-based calls in `src/api/expenses.ts` and `src/api/shares.ts` mostly omit the bearer token header.

---

## Known issues / tech-debt

- **Hardcoded JWT secret** — `SECRET_KEY = "your-secret-key"` in `service_layer/auth_service.py`. Must be moved to an env var before treating security seriously.
- **N-member support** — hardcoded Fran/Guadi identity has been removed (M4 refactor). The backend now supports arbitrary member sets. WhatsApp flows (lending, percentage split, payer selection) adapt based on `member_service.list_members()`. Settlement generates one balancing expense per debtor→creditor pair.
- **`print()` for logging** — many `print()` calls exist in `repositories.py`, `expense_manager.py`, etc. Should be replaced with `logging`.
- **Frontend auth inconsistency** — `fetch`-based API calls in `src/api/expenses.ts` and `src/api/shares.ts` mostly omit the bearer token header.

---

## Development workflow

- `make lint` must pass before committing (pre-commit: black @ line-length 120, isort, pylint, flake8, mypy).
- Pylint is excluded from `migrations/` via `.pre-commit-config.yaml`.
- CI pipeline (`.github/workflows/build.yml`): `lint → unit → integration → docker-build`. Integration stage uses a `postgres:15` service container.
- **Branch model**: `main` = staging (auto-deploys to Render staging on every push after CI passes). `prod_render` = production (fast-forwarded via the release workflow).
- **Releasing**: run the `release.yml` workflow (`workflow_dispatch`) with a version like `v0.2.0`. It tags `main` HEAD, fast-forwards `prod_render`, and creates a GitHub Release. Before releasing, run `alembic upgrade head` against prod Neon with `DATABASE_URL=<prod neon url>`.
- Migrations target **Neon** postgres. When prod already has tables from `create_all`, stamp any new migration that only reconciles schema drift rather than re-running it: `alembic stamp <revision>`.

---

---

## Adding a new resource — checklist

1. `src/template/domain/models/` — new domain model (Pydantic)
2. `src/template/domain/schemas/` — request/response schemas (`CamelCaseModel`)
3. `src/template/adapters/orm.py` — SQLAlchemy `Mapped` model
4. `migrations/versions/` — new Alembic migration (`alembic revision --autogenerate`)
5. `src/template/adapters/repositories.py` — repository methods (ORM ↔ domain translation)
6. `src/template/service_layer/` — application service
7. `src/template/dependencies.py` — `Depends()` factory
8. `src/template/entrypoint/` — FastAPI router (wrap responses in `ResponseModel[T]`)
9. `src/template/router.py` — register the new router under `/api/v1`
10. Frontend: add/update `src/api/<resource>.ts` in the companion app
