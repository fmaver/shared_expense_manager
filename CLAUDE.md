# shared_expense_manager — CLAUDE.md

Personal expense tracker for Fran (id=1) and Guada (id=2). Tracks expenses over time, splits costs, and settles balances by month. Sends WhatsApp and email notifications when expenses are added. Companion frontend lives at `/Users/franciscomaver/Documents/shared_expenses/shared_expense_front`.

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
make test                                  # pytest
make cover                                 # pytest + coverage
make lint                                  # pre-commit --all-files
```

Alembic migrations: `alembic upgrade head` (reads `DATABASE_URL` env var).

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
│   ├── orm.py           # SQLAlchemy ORM models (MemberModel, ExpenseModel, MonthlyShareModel)
│   └── repositories.py  # repository implementations (translate ORM ↔ domain)
├── domain/
│   ├── models/          # domain entities + business logic
│   │   ├── models.py    # Expense, MonthlyShare (with recalculate_balances)
│   │   ├── expense_manager.py   # ExpenseManager aggregate root
│   │   ├── member.py    # Member
│   │   ├── category.py  # Category (static list, NOT a DB table)
│   │   └── split.py     # SplitStrategy, EqualSplit, PercentageSplit
│   ├── schemas/         # Pydantic request/response DTOs
│   └── schema_model.py  # CamelCaseModel + ResponseModel[T] generic wrapper
├── service_layer/
│   ├── expense_service.py
│   ├── member_service.py
│   ├── auth_service.py
│   ├── notification_service.py
│   ├── whatsapp_service.py      # ~1 000 lines — WhatsApp Cloud API calls + chatbot
│   └── initialization_service.py  # seeds default members on startup
└── entrypoint/
    ├── expense.py
    ├── monthly_share.py
    ├── member.py
    ├── auth.py
    ├── category.py
    ├── monitor.py       # / and /liveness, /readiness
    └── whatsapp_bot.py  # Meta webhook + in-memory chatbot state machine
```

---

## Domain model

| Entity | Key fields | Notes |
|---|---|---|
| `Member` | id, name, telephone, email, hashed_password, notification_preference, last_wpp_chat_datetime | `notification_preference`: WHATSAPP / EMAIL / NONE |
| `Expense` | id, description, amount, date, category, payer_id, payment_type, installments, installment_no, split_strategy (JSON), parent_expense_id | `parent_expense_id` self-FK, cascade delete |
| `MonthlyShare` | year, month, is_settled, balances (JSON dict member_id→float), expenses | owns `recalculate_balances` logic |
| `Category` | name, emoji, is_internal | **Not a DB table** — class-level static list in `category.py` |
| `SplitStrategy` | abstract | `EqualSplit` / `PercentageSplit` (percentages must sum to 100 ±0.01) |
| `ExpenseManager` | — | aggregate root; orchestrates create/update/delete, settlement, monthly share recalc |

**Seeded members** (auto-inserted on every startup by `InitializationService`): Fran (id=1), Guadi (id=2).

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
- `POST /settle/{year}/{month}` — close out, generate balancing expense
- `POST /recalculate/{year}/{month}`

**Categories** `/api/v1/categories`
- `GET /`, `GET /with-emojis`

**Monitor** (root)
- `GET /` → 301 → `/docs`
- `GET /liveness`, `GET /readiness`

**WhatsApp webhook** (root)
- `GET /webhook` — Meta verification
- `POST /webhook` — inbound messages → chatbot state machine

---

## Conventions that will bite you

- **Response envelope**: every response is `ResponseModel[T]` → `{ "data": ... }`. Set `response_model=ResponseModel[YourSchema]` on every route.
- **camelCase on the wire**: `CamelCaseModel` aliases snake_case → camelCase. `model_dump()` defaults to `by_alias=True`. The frontend expects camelCase.
- **Money is `float`** (not Decimal/cents). `EqualSplit` and `PercentageSplit` round to 2 decimals; `PercentageSplit` adds rounding discrepancy to the highest-percentage member.
- **Credit-card installments**: a credit expense with N installments is expanded into N rows — parent (installment 1, date = expense.date + 1 month) + N-1 children linked via `parent_expense_id`. Description becomes `"<desc> (k/N)"`. Monthly shares for all affected months are auto-created/recalculated. Cascade delete on `parent_expense_id` removes children automatically.
- **Internal categories**: `balance` (auto-generated by settle) and `prestamo` are hidden from `GET /categories`. Don't expose them in the UI.
- **Datetimes**: `last_wpp_chat_datetime` is timezone-aware UTC. Always produce timezone-aware datetimes when doing arithmetic against it (commit 924c4bb fixed a naive-vs-aware subtraction bug).
- **Notifications are BackgroundTasks**: HTTP response returns before WhatsApp/email I/O completes.
- **WhatsApp 24-hour window rule**: if `now - member.last_wpp_chat_datetime >= 1 day` (or never set), Meta requires a pre-approved template. Template name: `expense_notification`, locale `es_AR`. Within the window, free-form text is allowed.
- **DB tables created on startup AND Alembic migrations both exist** — they coexist by design. The Alembic baseline is `baseline_baseline_20250318.py`.
- **Default members re-seeded every startup** — safe because `InitializationService` checks for existence first.

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
| `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` | Email (defaults to Gmail) |
| `STORAGE_PATH` | Directory for generated PDFs |

---

## Frontend integration

Companion app: `/Users/franciscomaver/Documents/shared_expenses/shared_expense_front`
- React 18 + TypeScript + Vite, runs on port **5173** (`npm run dev`)
- Backend URL via `VITE_API_URL` env var (defaults to `http://localhost:8000`)
- Hand-written API clients in `src/api/` (no codegen). Uses both `axios` and `fetch`.
- Auth: stores JWT in `localStorage` key `token`; sets axios default header on login.
- **When you change the API surface** (add/rename/remove an endpoint, change a request/response shape), cross-check `src/api/` in the frontend.

---

## Known issues / tech-debt

- **Hardcoded JWT secret** — `SECRET_KEY = "your-secret-key"` in `service_layer/auth_service.py:19`. Must be moved to an env var before treating security seriously.
- **In-memory chatbot state** — `estado_actual` dict in `entrypoint/whatsapp_bot.py` is module-level; it won't survive restarts and is not safe with multiple workers.
- **Sparse test coverage** — unit tests cover domain/split strategies/expense_manager; there are no tests for auth, notifications, WhatsApp, or any router. The e2e suite only hits `/liveness` and `/readiness`.
- **`print()` for logging** — many `print()` calls exist in `repositories.py`, `expense_manager.py`, etc. Should be replaced with `logging`.
- **Frontend auth inconsistency** — `fetch`-based API calls in `src/api/expenses.ts` and `src/api/shares.ts` mostly omit the bearer token header.

---

## Development workflow

- `make lint` must pass before committing (pre-commit: black @ line-length 120, isort, pylint, flake8, mypy).
- CI: `.github/workflows/build.yml` — lint + coverage + docker build on Python 3.11.
- Production: hosted on **Render** (`DATABASE_ENV=PROD`). Long-lived branch `prod_render` is merged from `main` for each deploy.
- Migrations target **Neon** postgres (set `NEON_DATABASE_URL` or override with `DATABASE_URL`).

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
