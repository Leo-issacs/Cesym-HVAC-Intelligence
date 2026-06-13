"""
Migración de datos: SQLite → PostgreSQL.

Lee todos los datos del SQLite actual y los inserta en PostgreSQL.
Imprime conteos de origen vs destino para verificación.

Uso:
    python -X utf8 scripts/migrate_sqlite_to_postgres.py

Prerrequisitos:
    1. DATABASE_URL en .env debe apuntar a PostgreSQL.
    2. Las tablas deben existir en PostgreSQL (alembic upgrade head).
    3. El SQLite en data/db/hvac.db debe existir (scripts/cargar_bd.py --limpiar).

El archivo SQLite de origen NO se modifica en ningún caso.
"""

import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text

load_dotenv()

SQLITE_PATH = ROOT / "data" / "db" / "hvac.db"
SQLITE_URL = f"sqlite:///{SQLITE_PATH}"
PG_URL = os.getenv("DATABASE_URL", "")

TABLES = ["facturas", "scores_clientes"]


def _validate():
    if not SQLITE_PATH.exists():
        print(f"ERROR: SQLite no encontrado en {SQLITE_PATH}")
        print("Ejecuta primero: python -X utf8 scripts/cargar_bd.py --limpiar")
        sys.exit(1)

    if not PG_URL.startswith("postgresql"):
        print("ERROR: DATABASE_URL no está configurada o no apunta a PostgreSQL.")
        print("Ejemplo: DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname")
        sys.exit(1)


def _pg_engine():
    eng = create_engine(PG_URL, pool_pre_ping=True)

    # search_path = analytics en autocommit (ver nota detallada en src/db.py):
    # con el pooler de Supabase la opción de arranque de libpq se descarta, y un
    # `SET` dentro de transacción lo revierte el rollback del pool.
    @event.listens_for(eng, "connect")
    def _set_path(dbapi_conn, _record):
        prev_autocommit = dbapi_conn.autocommit
        dbapi_conn.autocommit = True
        cur = dbapi_conn.cursor()
        cur.execute("SET search_path TO analytics")
        cur.close()
        dbapi_conn.autocommit = prev_autocommit

    return eng


def migrate():
    _validate()

    src = create_engine(SQLITE_URL)
    dst = _pg_engine()

    sep = "─" * 58
    print(f"\n{sep}")
    print(f"  MIGRACIÓN SQLite → PostgreSQL (schema: analytics)")
    print(sep)

    for table in TABLES:
        print(f"\n[{table}]")

        try:
            df = pd.read_sql(f"SELECT * FROM {table}", src)
        except Exception as exc:
            print(f"  ADVERTENCIA: tabla '{table}' no encontrada en SQLite — {exc}")
            continue

        count_src = len(df)
        print(f"  Origen  (SQLite):     {count_src:>6} filas")

        if count_src == 0:
            print("  Tabla vacía, saltando.")
            continue

        with dst.connect() as conn:
            exists = conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = 'analytics' AND table_name = :t"
                ),
                {"t": table},
            ).scalar()

        if not exists:
            print(f"  ERROR: tabla '{table}' no existe en PostgreSQL.")
            print("  Ejecuta primero: alembic upgrade head")
            continue

        df.to_sql(table, dst, if_exists="replace", index=False)

        with dst.connect() as conn:
            count_dst = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()

        status = "✓" if count_dst == count_src else "✗ DIFERENCIA"
        print(f"  Destino (PostgreSQL): {count_dst:>6} filas  {status}")
        if count_dst != count_src:
            print(f"  *** ALERTA: {count_src} vs {count_dst} — revisar antes de continuar ***")

    print(f"\n{sep}")
    print("  Migración completada. Verifica los conteos arriba.")
    print(f"  SQLite original intacto: {SQLITE_PATH.relative_to(ROOT)}")
    print(sep)


if __name__ == "__main__":
    migrate()
