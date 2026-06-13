"""
Configuración central de la base de datos.

Lee DATABASE_URL del entorno (.env o variable de sistema).
  - PostgreSQL: establece search_path = analytics en cada conexión.
  - Sin DATABASE_URL: usa SQLite local como fallback.

Importar desde cualquier módulo del proyecto:
    from src.db import engine, is_postgres, SQLITE_DB_PATH, DATABASE_URL
"""

import os
import pathlib

from dotenv import load_dotenv
from sqlalchemy import create_engine, event

load_dotenv()

ROOT = pathlib.Path(__file__).resolve().parent.parent
SQLITE_DB_PATH = ROOT / "data" / "db" / "hvac.db"

DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{SQLITE_DB_PATH}")
is_postgres: bool = DATABASE_URL.startswith("postgresql")


def _make_engine():
    if is_postgres:
        eng = create_engine(DATABASE_URL, pool_pre_ping=True)

        # Fijar search_path = analytics en cada conexión nueva del pool.
        #
        # Dos trampas que este código evita:
        #   1) NO se puede usar la opción de arranque de libpq
        #      (connect_args={"options": "-csearch_path=analytics"}): el pooler de
        #      Supabase (Supavisor) descarta ese parámetro y el search_path queda
        #      en el default (public), así que las tablas en `analytics` no se ven.
        #   2) El `SET search_path` debe ejecutarse en autocommit. Si corre dentro
        #      de una transacción, el ROLLBACK que el pool emite al devolver la
        #      conexión lo revierte (SET es transaccional en PostgreSQL) y solo la
        #      primera consulta de cada conexión vería `analytics` — fallo
        #      intermitente difícil de diagnosticar.
        @event.listens_for(eng, "connect")
        def _set_search_path(dbapi_conn, _record):
            prev_autocommit = dbapi_conn.autocommit
            dbapi_conn.autocommit = True
            cur = dbapi_conn.cursor()
            cur.execute("SET search_path TO analytics")
            cur.close()
            dbapi_conn.autocommit = prev_autocommit

        return eng
    return create_engine(DATABASE_URL)


engine = _make_engine()
