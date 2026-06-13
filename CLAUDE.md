# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HVAC AI System — a Python-based pipeline for an HVAC service company. Ingests raw Excel data (invoices, installations, client portfolio), cleans it through an ETL layer, stores it in SQLite, and provides AI-assisted scoring and analytics.

Service concepts are categorized into four classes:
- `mantenimiento_preventivo` — scheduled preventive maintenance
- `mantenimiento_correctivo` — corrective/repair service
- `instalacion_nueva` — new equipment installation
- `venta_refaccion` — spare parts sale

## Architecture Docs

Reverse-engineered documentation of the system as it actually exists:

- `docs/ARCHITECTURE.md` — modules, responsibilities, end-to-end data flow, and
  known fragile points (destructive `to_sql` replaces, Alembic schema with no
  PK/constraints that the ETL overwrites, dashboard cache without TTL).
- `docs/DATA_FLOW.md` — tables, columns, **real runtime types** (what pandas
  `to_sql` creates, which differs from the Alembic declarations), and the
  read/write owner of every table and file.

> The schema tables further down in this file reflect the *intended* schema. For
> the types that actually exist at runtime, see `docs/DATA_FLOW.md`.

## Conventions

- **Commits:** Conventional Commits in Spanish (`feat:`, `fix:`, `docs:`,
  `refactor:`, `chore:`). Matches existing history (e.g. `feat: integra Alembic
  y migra acceso a datos al engine central`). End commit messages with the
  `Co-Authored-By` trailer when generated with Claude.
- **Pull requests:** keep them small — **≤400 lines of diff**. Split larger work
  into multiple PRs.
- **Tests in the same PR:** any behavior change ships with its tests in the same
  PR (`tests/`). Don't defer tests to a follow-up.
- **UTF-8 always:** run every script with `python -X utf8` — the data is full of
  Spanish text and accents.
- **Never edit `data/raw/`** by hand; it is the source of truth from Drive.
- **Don't commit** the venv (`cesym_data_analytics/`), `.env`, or
  `credentials/service_account.json`.

## Virtual Environment

The project uses a virtual environment named `cesym_data_analytics` (Cesym Data Analytics).

```powershell
# Activar (PowerShell)
.\cesym_data_analytics\Scripts\Activate.ps1

# Instalar dependencias desde cero
pip install -r requirements.txt
```

The venv folder is local — do not commit it to git.

## Database Configuration

The database connection is centralized in `src/db.py`. It reads `DATABASE_URL` from `.env`:

- **SQLite (default):** leave `DATABASE_URL` unset → uses `data/db/hvac.db` automatically.
- **PostgreSQL:** set `DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname` → all tables go to the `analytics` schema (set via `search_path` on every connection).

Copy `.env.example` to `.env` and fill in your values.

### Environment variables

All read from `.env` (loaded via `python-dotenv`) or the system environment.

| Variable | Used by | Purpose |
|---|---|---|
| `DATABASE_URL` | `src/db.py`, `alembic/env.py`, `scripts/migrate_sqlite_to_postgres.py` | Connection string. Unset → SQLite fallback (`data/db/hvac.db`). `postgresql+psycopg2://...` → Postgres, `analytics` schema. In `.env.example` this is the Supabase **pooler** URL (port 6543). |
| `DATABASE_MIGRATION_URL` | *(declared in `.env.example` only)* | Direct connection (port 5432) "for migrations". **Note:** no code reads it today — `migrate_sqlite_to_postgres.py` actually uses `DATABASE_URL`. See `docs/ARCHITECTURE.md` §5.4. |
| `DRIVE_FOLDER_ID` | `scripts/sync_drive.py` | ID of the shared Google Drive folder to pull the Excel files from. |
| `DRIVE_CREDENTIALS_PATH` | `scripts/sync_drive.py` | Path to the Service Account JSON (default `credentials/service_account.json`). |

Run `setup_google_cloud.ps1` (after `gcloud auth login`) to provision the GCP
project + Service Account and auto-write the Drive variables into `.env`.

### Schema migrations (Alembic)

```powershell
# Generate SQL preview (offline, no real DB needed)
alembic upgrade head --sql

# Apply migrations to PostgreSQL (requires DATABASE_URL set)
alembic upgrade head

# Rollback
alembic downgrade -1
```

### Data migration SQLite → PostgreSQL

```powershell
# After running alembic upgrade head:
python -X utf8 scripts/migrate_sqlite_to_postgres.py
```

## Running each piece

Always use `-X utf8` to handle Spanish text in data. Activate the venv first.
Every script reads the DB through `src/db.py`, so they target SQLite or Postgres
depending on `DATABASE_URL`.

```powershell
# ── Ingest from Google Drive (download + ETL + scoring in one shot) ──
python -X utf8 scripts/sync_drive.py             # download new Excel, then run pipeline
python -X utf8 scripts/sync_drive.py --dry-run   # show what it would download, change nothing
python -X utf8 scripts/sync_drive.py --solo-sync # download only, skip ETL/scoring

# ── ETL: Excel → table `facturas` ──
python -X utf8 scripts/cargar_bd.py --limpiar    # full reload, drops table first
python -X utf8 scripts/cargar_bd.py              # replace table in place (still destructive)
python -X utf8 scripts/etl.py                    # same ETL, no --limpiar

# ── Client scores → table `scores_clientes` + CSV ──
python -X utf8 src/models/client_score.py

# ── Cash-flow forecast → PNG + CSV in data/processed/ (does NOT touch the DB) ──
python -X utf8 src/models/forecasting.py

# ── NLP concept classifier → CSV + .joblib model (does NOT touch the DB) ──
python -X utf8 src/models/classifier.py

# ── Dashboard ──
streamlit run src/dashboard/app.py
```

> Heads-up: `cargar_bd.py` and `client_score.py` write with
> `to_sql(if_exists="replace")` — they **drop and recreate** the table every run,
> discarding any index/PK/constraint. The dashboard caches reads with
> `@st.cache_data` **without a TTL**, so it can show stale data after a sync until
> restarted. Details in `docs/ARCHITECTURE.md` §5.

### Scheduled automation (Windows)

```powershell
# Sync both projects (HVAC + Cesym Chatbot) once
.\scripts\sync_maestro.ps1
.\scripts\sync_maestro.ps1 -DryRun

# Register the weekly scheduled task (Mondays 07:00) — run as Administrator
.\setup_tarea_semanal.ps1
```

## Directory Structure

```
data/
  raw/          Source Excel files — never modify
    reporteMensual_FACTURAS.xlsx          396 rows: invoices with payment dates
    CARTERA AL 11032026.xlsx              Customer portfolio / accounts receivable
    CONTROL DE INST. MINISPLIT 2026.xlsx  Mini-split installation log (currently empty)
  processed/
    conceptos_clasificados.csv            Ground-truth labels for concept classifier
    scores_clientes.csv                   Output of client_score.py
  db/
    hvac.db                               SQLite database (created by ETL)

src/
  db.py               Central DB config: reads DATABASE_URL, creates SQLAlchemy engine
  etl/
    load_facturas.py  Cleans and loads reporteMensual_FACTURAS.xlsx → table `facturas`
  models/
    client_score.py   Reads `facturas`, computes 3 scores, writes `scores_clientes`
    forecasting.py    Reads `facturas`, Holt-Winters cash-flow forecast → PNG + CSV
    classifier.py     TF-IDF + LogReg concept classifier → CSV + .joblib (no DB write)
  agents/             Planned sub-modules: collections, orchestrator, quotes, routes
  api/                Not yet implemented
  dashboard/
    app.py            Streamlit dashboard (3 tabs: Resumen, Scores, Forecast)

scripts/
  etl.py                        Entry point → calls src/etl/load_facturas.run()
  cargar_bd.py                  Entry point with --limpiar flag → calls same ETL
  sync_drive.py                 Download Excel from Drive → run ETL + scoring
  sync_maestro.ps1              Sync HVAC + Cesym Chatbot projects in one run
  migrate_sqlite_to_postgres.py Copy data from SQLite to PostgreSQL with count verification

alembic/                        Alembic migration setup
  env.py                        Migration environment (reads DATABASE_URL)
  versions/
    001_initial_schema.py       Creates facturas + scores_clientes in analytics schema

docs/
  ARCHITECTURE.md   Modules, data flow, known fragile points
  DATA_FLOW.md      Tables, columns, real runtime types, read/write owners

setup_google_cloud.ps1  Provision GCP project + Service Account, write .env
setup_tarea_semanal.ps1 Register weekly Windows scheduled task (run as admin)

notebooks/        Exploratory analysis
tests/            Test suite
```

## Database Schema

**Table `facturas`** (374 rows after cleaning)

| Column         | Type    | Notes                                      |
|----------------|---------|--------------------------------------------|
| folio          | INTEGER | Invoice number                             |
| cliente        | TEXT    | Normalized: strip + uppercase              |
| fecha_factura  | TEXT    | ISO datetime                               |
| concepto       | TEXT    | Service description                        |
| total          | REAL    | Invoice amount (MXN)                       |
| fecha_pago     | TEXT    | ISO datetime, NULL if unpaid               |
| dias_pago      | INTEGER | Days invoice→payment, clipped to min=0     |
| pagada         | INTEGER | 1 = paid, 0 = unpaid/pending              |

**Table `scores_clientes`** (17 rows)

| Column        | Notes                                              |
|---------------|----------------------------------------------------|
| cliente       | Primary key                                        |
| n_facturas    | Total invoices issued                              |
| monto_total   | Lifetime billed amount                             |
| avg_dias_pago | Mean days to pay (paid invoices only)              |
| pct_impagadas | Fraction of unpaid invoices (0.0–1.0)              |
| score_pago    | 0–100, higher = faster payer                       |
| score_valor   | 0–100, higher = more valuable client               |
| score_riesgo  | 0–100, higher = more likely to be late/unpaid      |
| fecha_calculo | ISO date when scoring was run                      |

## Data Quality Notes

- **Client names**: 22 raw variants collapse to 17 after `.strip().upper()`. Fuzzy matches (e.g., `TEC Y DISEÑO` vs `TEC Y DISEÑOS`) are treated as separate clients.
- **Date formats**: `Fecha` column is `yyyy-mm-dd`, `FECHA DE PAGO` is `dd/mm/yyyy` or `yyyy-mm-dd` (mixed). ETL uses `dayfirst=True` + `errors="coerce"`.
- **Negative dias_pago**: Some invoices show payment before invoice date (likely advance payments or data entry errors). Clipped to 0.
- **Unpaid invoices**: 135 of 374 invoices lack a payment date. `pct_impagadas` is the primary risk signal in `score_riesgo`.
