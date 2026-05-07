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
│   │   ├── category.py  # Category (static list, NOT a DB table)
│   │   └── split.py     # SplitStrategy, EqualSplit, PercentageSplit
│   ├── schemas/         # Pydantic request/response DTOs
│   └── schema_model.py  # CamelCaseModel + ResponseModel[T] generic wrapper
├── service_layer/
│   ├── expense_service.py
│   ├── member_service.py
│   ├── auth_service.py
│   ├── notification_service.py
│   ├── whatsapp_client.py       # WhatsAppClient Protocol + MetaWhatsAppClient
│   ├── whatsapp_service.py      # chatbot state machine (uses WhatsAppClient via DI)
│   └── initialization_service.py  # seeds default members on startup
└── entrypoint/
    ├── expense.py
    ├── monthly_share.py
    ├── member.py
    ├── auth.py
    ├── category.py
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
| `Member` | id, name, telephone, email, hashed_password, notification_preference, last_wpp_chat_datetime | `notification_preference`: WHATSAPP / EMAIL / NONE |
| `Expense` | id, description, amount, date, category, payer_id, payment_type, installments, installment_no, split_strategy (JSON), parent_expense_id | `parent_expense_id` self-FK, cascade delete |
| `MonthlyShare` | year, month, is_settled, balances (JSON dict member_id→float), expenses | owns `recalculate_balances` logic |
| `Category` | name, emoji, is_internal | **Not a DB table** — class-level static list in `category.py` |
| `SplitStrategy` | abstract | `EqualSplit` / `PercentageSplit` (percentages must sum to 100 ±0.01) |
| `ExpenseManager` | — | aggregate root; orchestrates create/update/delete, settlement, monthly share recalc |
| `ChatSession` | telephone (PK), estado, expense_data (JSON), updated_at | DB-backed chatbot state — replaces the old in-memory `estado_actual` dict |
| `ProcessedWhatsappMessage` | message_id (PK), processed_at | Idempotency table — prevents duplicate processing on Meta retries |

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
- **DB tables created on startup AND Alembic migrations both exist** — they coexist by design. The Alembic baseline is `baseline_baseline_20250318.py`. Latest revision: `m4_reconcile_schema`.
- **Default members re-seeded every startup** — safe because `InitializationService` checks for existence first.
- **`get_expense` raises `ValueError` for missing IDs** — the expense endpoint catches this as HTTP 400, not 404. Integration tests should assert `status_code in (400, 404)` for the not-found case.

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

## SendGrid setup (one-time, per environment)

Email notifications are sent via the [SendGrid](https://sendgrid.com) HTTP API. Free tier: 100 emails/day, no expiry.

### 1 — Create a SendGrid account
Go to [sendgrid.com](https://sendgrid.com) and sign up for a free account.

### 2 — Verify a sender address
SendGrid requires a verified "from" address before it will send mail.

1. In the SendGrid dashboard go to **Settings → Sender Authentication**
2. Click **Verify a Single Sender**
3. Fill in your name and the email address you want as the sender (e.g. your Gmail)
4. Click **Create** — SendGrid sends a verification email to that address
5. Open the email and click **Verify Single Sender**

### 3 — Create an API key
1. Go to **Settings → API Keys → Create API Key**
2. Name it (e.g. `shared-expenses-staging` or `shared-expenses-prod`)
3. Choose **Restricted Access**
4. Under **Mail Send** set to **Full Access**
5. Click **Create & View** — copy the key immediately (shown only once)

### 4 — Add env vars in Render
Do this for **both** the staging and production services in the Render dashboard
(**Dashboard → your service → Environment**):

| Variable | Value |
|---|---|
| `SENDGRID_API_KEY` | the API key from step 3 |
| `SENDGRID_FROM_EMAIL` | the verified sender email from step 2 |

Use a **different API key** for staging vs prod (makes it easy to revoke one without affecting the other).

### 5 — Remove old SMTP variables
Delete the following from Render if they exist (they are no longer read by the app):
`SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`

### Disabling email
Leave `SENDGRID_API_KEY` unset (or empty) to silently skip email notifications without errors.
Useful for local dev or test environments where you don't need real emails.

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

## Staging WhatsApp setup

A separate Meta app (`shared-expense-manager-staging`) is wired to the **Render staging service** and the Meta **test phone number** (`+1 555-184-1153`, phone number ID `1170347522817754`). This lets you test end-to-end WhatsApp flows without touching production.

### WABA subscription — the step everyone forgets
Configuring a webhook URL in the Meta Developer Console only enables the GET verification handshake. To actually receive POST webhook events you must also subscribe the app to your WABA:

```bash
curl -X POST \
  "https://graph.facebook.com/v17.0/<WABA_ID>/subscribed_apps" \
  -H "Authorization: Bearer <TOKEN>"
# → {"success": true}
```

Do this once per Meta app (not per phone number). Without it, Meta shows the webhook as "configured" but delivers no events.

### Token management
- **Never use a temporary user token** for a deployed service — they expire after a few hours (Meta error code 190).
- Generate a **permanent system user token**: Business Settings → Users → System Users → select the system user → Generate New Token → select the app → grant `whatsapp_business_messaging` and `whatsapp_business_management` permissions → copy immediately.
- Validate a token before deploying: `GET https://graph.facebook.com/v17.0/me?access_token=<TOKEN>`. A working token returns `{"id": "...", "name": "..."}`.

### Phone number format
- Meta webhooks deliver numbers as `549XXXXXXXXXX` (country code 54 + digit 9 + local number).
- `replace_start()` in `whatsapp_service.py` strips the `9` → DB lookup uses `54XXXXXXXXXX`.
- Outbound messages (and the numbers stored in the DB) also use `54XXXXXXXXXX` — Meta's own API examples use this format.
- Store all telephone values in the DB **without the 9** (e.g. `541138718498`, not `5491138718498`).

### `expense_notification` template
The `expense_notification` template (locale `es_AR`) exists only in the **production** Meta app. In staging it will 404 when the 24-hour free-form window has expired. Workaround: send a message from the staging test number first to open the window, then the bot can reply with free-form text.

---

## Recent fixes & refactors

### MetaWhatsAppClient error logging (2026-05)
`MetaWhatsAppClient.send_message()` now logs the status code and response body when Meta returns a non-200. Previously, failed sends were silently swallowed. This was critical for diagnosing token expiry (401) and missing templates (404) in staging.

### WhatsApp N-member UX — C2, C3, C5 (2026-05)
Three WhatsApp chatbot flows were hardcoded for exactly two members (Fran/Guada). All three are now fully dynamic:

- **C5 — Payer selection** (`handle_waiting_for_description`): switched from `button_reply_message` (Meta limit: 3 buttons) to `member_select_message`, which auto-promotes to a `list_reply` interactive message when there are more than 3 members.
- **C2 — Lending recipient** (`handle_waiting_for_payment_date`): replaced the `id_of_not_payer = 1 if payer_id == 2 else 2` ternary. For exactly 2 members the non-payer is still inferred automatically; for 3+ members a new state `esperando_destinatario_prestamo` prompts the user to pick the recipient. New handler: `handle_waiting_for_loan_recipient`.
- **C3 — Percentage split** (`handle_waiting_for_split_strategy` / `handle_waiting_for_percentage`): for exactly 2 members the single-prompt flow is unchanged; for 3+ members a queue-based loop iterates over all non-payers, collecting one percentage per member. Accumulated in `expense_data["pending_percentages"]`; payer's share is assigned as the remainder. New state `esperando_porcentaje_para_miembro` and handler `handle_waiting_for_percentage_for_member`. Overflow validation rejects inputs that would push the running total above 100%.

New unit tests in `tests/unit/service/test_whatsapp_state_machine.py` cover all paths.

### Date serialisation in chat session JSON (2026-05)
`handle_waiting_for_payment_date` was storing a Python `date` object in `expense_data` (a SQLAlchemy JSON column). SQLAlchemy cannot serialise `date` to JSON; the fix stores `.isoformat()` instead. Pydantic v2 coerces the ISO string back to `date` when `ExpenseCreate(date=...)` is constructed, so no change was needed at the consumption point.

### `asyncio.create_task` → `asyncio.run` in expense creation (2026-05)
`create_expense` called `asyncio.create_task(notification_service.notify_expense_created(...))`, which requires a running event loop. The FastAPI `BackgroundTask` that drives `_process_message` runs in a **threadpool thread** (not an async context), so there is no running loop and the call raised `RuntimeError: no running event loop`.

Fix: replaced with `asyncio.run(notification_service.notify_expense_created(...))`, which creates a fresh event loop in the current thread, runs the coroutine to completion, and closes the loop. This is the correct pattern for calling async code from a synchronous threadpool callback.

### SMTP → SendGrid HTTP API (2026-05)
Render explicitly blocks outbound TCP on SMTP ports (25, 465, 587) on all tiers. The previous `smtplib`-based `_send_email` implementation would always fail on Render regardless of credentials.

Replaced with the [SendGrid HTTP API](https://docs.sendgrid.com/api-reference/mail-send) (port 443, allowed on Render). Uses the existing `requests` dependency — no new packages. The `_send_email` method now POSTs to `https://api.sendgrid.com/v3/mail/send` with a Bearer token. Free tier: 100 emails/day with no expiry. If `SENDGRID_API_KEY` or `SENDGRID_FROM_EMAIL` is unset, email is silently skipped (safe for local dev).

Removed env vars: `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`. Added: `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`. See the **SendGrid setup** section above for one-time configuration steps.

New unit tests in `tests/unit/service/test_notification_service.py` cover: correct payload shape, skip-when-unconfigured, non-2xx response swallowed, `RequestException` swallowed.

### WhatsApp chatbot UX enhancements — dates, amounts, categories, cancel (2026-05)
Multiple friction points in the chatbot were resolved:

- **Amount input**: accepts comma as decimal separator (`1234,56`) in addition to dot.
- **Date entry**: accepts `hoy`, `ayer`, `DD/MM/AAAA`, `DD-MM-AAAA`, and `DD-MM`/`DD/MM` (assumes current year). The date prompt shows "Hoy" / "Ayer" as tappable buttons. Dates are stored as ISO strings and displayed as `DD/MM/AAAA` in the summary.
- **Payment type**: 3-button prompt — "Débito", "Crédito 1 cuota" (skips cuotas question), "Crédito en cuotas". Installments require ≥2 (no upper bound).
- **Category picker**: interactive `list_reply` with `cat_<name>` IDs. List-only — number and name text fallbacks removed. Categories `viajes` ✈️ and `salud` 💊 added; `compras` renamed to `supermercado` 🛒. A data migration (`m5_rename_compras`) updates existing rows. Internal categories (`balance`, `prestamo`) filtered from `GET /api/v1/categories`.
- **Spanish polish**: summary uses `format_payment_type_es`, `format_date_es`, `format_category_es`, `format_member_name_es` helpers. "Resumen del préstamo" for loan flow. "Partes iguales" division label.
- **Global cancel**: typing `cancelar` from any state resets to `inicial` and sends the main menu prefixed with "❌ Operación cancelada." Hint shown in the greeting.
- **State reset on success**: `clean_estado_usuario` is called in the confirmation success branch, so sessions return to `inicial` after a successful expense creation.
- **Button matching by ID**: `obtener_interactive_id_whatsapp` extracts `button_reply.id` / `list_reply.id`. Handlers match by ID where available (e.g. `cat_salud`) instead of fragile title-substring matching.

New unit tests in `tests/unit/service/test_whatsapp_ux_enhancements.py`.

**Frontend impact**: `GET /api/v1/categories` and `GET /api/v1/categories/with-emojis` no longer return `balance` or `prestamo`. Category `compras` is now `supermercado`. Two new categories: `viajes`, `salud`. Update any frontend category lists/filters accordingly.

### Subset-equal and exact-amounts split strategies (2026-05)
Two new first-class split options added to the WhatsApp chatbot and API:

- **Subset-equal** (`type: "equal"` with `participant_ids`): after tapping "Partes iguales" with ≥3 members, the user can exclude members via a toggle list (tap a name → tap "✅ Listo"). The expense splits equally among only the included participants. Excluded members get a $0 share in the balance.
- **Exact amounts** (`type: "exact"` with `amounts`): new third button "💵 Montos exactos". The bot asks each non-payer's exact dollar share via a queue flow (mirrors the percentage flow). The payer receives the remainder. Running total validated in real time; overflow rejected with "Te quedan $X."

**Domain changes** (`src/template/domain/models/split.py`):
- `EqualSplit` now accepts `participant_ids: Optional[List[int]]` — `None` means all members (backward compatible).
- New `ExactAmountsSplit(amounts: Dict[int, float])` — validates sum == total in `calculate_shares`.

**Schema changes** (`src/template/domain/schemas/expense.py`):
- `SplitStrategySchema.type` pattern widened to `^(equal|percentage|exact)$`.
- New optional fields: `participant_ids: Optional[List[int]]` (camelCase: `participantIds`) and `amounts: Optional[Dict[int, float]]`.
- `ExpenseCreate` has a `model_validator` that validates exact-split amounts sum to the expense total.

**Persistence**: JSON column — no Alembic migration needed. New serialize/deserialize branches in `repositories.py`. Old `{"type": "equal"}` rows deserialize as `EqualSplit(participant_ids=None)` — fully backward compatible.

**Service layer** (`src/template/service_layer/expense_service.py`): three near-duplicate strategy-construction blocks replaced by a single `_build_split_strategy(schema)` helper.

**New WhatsApp states**: `esperando_definicion_participantes`, `esperando_excluidos`, `esperando_monto_para_miembro` and their handlers. The split strategy prompt now has 3 buttons. `clean_estado_usuario` defensively clears all queue keys.

**Frontend impact**: `SplitStrategy` type in the API now supports `type: "exact"` and `type: "equal"` with optional `participantIds`. Existing payloads are unaffected (new fields are optional). Frontend needs updating to display and create these two new split types. See `src/api/expenses.ts` in the companion repo.

New unit tests in `tests/unit/domain/models/test_split.py` and `tests/unit/service/test_whatsapp_ux_enhancements.py` (35 new tests).

### PDF generation crash on non-latin-1 characters (2026-05)
`fpdf` encodes page content as latin-1, causing `UnicodeEncodeError` when an expense description contains characters outside that range — most commonly the iOS/Android curly apostrophe (`'`, U+2019) entered via phone autocorrect.

Added `_sanitize(text: str) -> str` in `src/template/domain/models/pdf_builder.py`. It first replaces the most common typographic characters with ASCII equivalents (`'`/`'` → `'`, `"`/`"` → `"`, `–`/`—` → `-`, `…` → `...`), then falls back to `encode('latin-1', 'replace')` for anything else. Applied to `expense.description`, `expense.category`, member name, and strategy columns, as well as the balance section member names.

### Post-PDF follow-up menu in WhatsApp (2026-05)
After sending the monthly balance PDF the bot left the conversation at a dead end. It now appends a `button_reply_message` with the 3 main-menu options ("💰 Cargar Gasto", "💸 Prestar Plata", "📊 Generar Balance") and resets state to `inicial`. Body: "¿Querés hacer algo más?". The PDF is visible above it so no redundant "document sent" confirmation is shown.

### Notification filtering for excluded members (2026-05)
`NotificationService.notify_expense_created` previously notified every member except the creator. It now also skips members who have no share in the expense:

- **Subset-equal** (`EqualSplit` with `participant_ids`): only members in `participant_ids` are notified.
- **Exact amounts** (`ExactAmountsSplit`): only members with a non-zero entry in `amounts` are notified.
- **Percentage** (`PercentageSplit`): only members with a non-zero percentage are notified.
- **Equal-all** (`EqualSplit` without `participant_ids`): unchanged — everyone is notified.

Implemented via `_is_involved_in_expense(expense, member_id)` private helper. New tests in `tests/unit/service/test_notification_service.py` cover all four split types.

### Argentine amount formatting in WhatsApp messages (2026-05)
All monetary amounts displayed in WhatsApp bot messages now use the Argentine convention (comma as decimal separator, dot as thousands separator): `$1.234,56` instead of `$1234.56`.

New helper `format_amount_es(amount: float) -> str` in `whatsapp_service.py` handles the conversion. Applied to:
- Expense summary (`💰 Monto`) in `get_expense_summary`
- Per-member amounts in the exact-split summary (`- {name}: $X,XX`)
- The exact-amounts input prompt (`Total del gasto`, `Asignado hasta ahora`, `Restante por asignar`)
- Overflow rejection message (`Te quedan $X,XX`)

The input hint (`ej: 250 o 250,50`) already used commas and is now visually consistent with the displayed values.

### Un-settle monthly share (2026-05)
New `POST /api/v1/shares/unsettle/{year}/{month}` endpoint reverses a settlement:

1. Deletes all `"balance"`-category expenses for that month (the auto-generated balancing expenses created by the settle flow). Manual `"prestamo"` lending expenses are **not** touched — they use a different category.
2. Sets `is_settled = False` on the `MonthlyShare`.
3. Recalculates balances from the remaining expenses.

Implemented across all four layers: `ExpenseRepository.unsettle_monthly_share` (interface + `SqlAlchemyExpenseRepository` implementation), `ExpenseManager.unsettle_monthly_share`, `ExpenseService.unsettle_monthly_share`, and the new router endpoint in `src/template/entrypoint/monthly_share.py`.

**Frontend impact**: add a "Reabrir mes" button on the monthly share view, visible only when `is_settled = true`. Should show a confirmation modal before calling the endpoint. Returns the standard `MonthlyBalanceResponse` with `is_settled: false` and recalculated balances.

### Alembic + `create_all` coexistence on Neon
When deploying a new Alembic migration to prod Neon after `create_all` already created those tables, use `alembic stamp <revision>` to mark the migration as applied before running `alembic upgrade head`. This avoids `DuplicateTable` errors.

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
