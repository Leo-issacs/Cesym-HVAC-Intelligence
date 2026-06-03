# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HVAC AI System — a Python-based pipeline for an HVAC service company. Ingests raw Excel data (invoices, installations, client portfolio), cleans it through an ETL layer, stores it in SQLite, and provides AI-assisted scoring and analytics.

Service concepts are categorized into four classes:
- `mantenimiento_preventivo` — scheduled preventive maintenance
- `mantenimiento_correctivo` — corrective/repair service
- `instalacion_nueva` — new equipment installation
- `venta_refaccion` — spare parts sale

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

## Running the Pipeline

Always use `-X utf8` to handle Spanish text in data. Activate the venv first.

```powershell
# 1. Populate the database (creates data/db/hvac.db or writes to PostgreSQL)
python -X utf8 scripts/cargar_bd.py --limpiar   # full reload, drops existing tables
python -X utf8 scripts/cargar_bd.py             # incremental (replaces tables in place)

# 2. Calculate client scores (writes scores_clientes table + CSV)
python -X utf8 src/models/client_score.py

# 3. Launch the Streamlit dashboard
streamlit run src/dashboard/app.py
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
  agents/             Planned sub-modules: collections, orchestrator, quotes, routes
  api/                Not yet implemented
  dashboard/
    app.py            Streamlit dashboard (3 tabs: Resumen, Scores, Forecast)

scripts/
  etl.py                        Entry point → calls src/etl/load_facturas.run()
  cargar_bd.py                  Entry point with --limpiar flag → calls same ETL
  migrate_sqlite_to_postgres.py Copy data from SQLite to PostgreSQL with count verification

alembic/                        Alembic migration setup
  env.py                        Migration environment (reads DATABASE_URL)
  versions/
    001_initial_schema.py       Creates facturas + scores_clientes in analytics schema

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
