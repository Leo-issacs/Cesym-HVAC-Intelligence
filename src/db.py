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
from sqlalchemy import create_engine, event, inspect, text

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


# ═════════════════════════════════════════════════════════════════════════════
# Escritura segura: validación + swap transaccional
#
# Reemplaza el patrón destructivo to_sql(if_exists="replace"), que hacía
# DROP+CREATE y borraba el schema (tipos, PK, constraints) en cada corrida — y,
# peor, dejaba la tabla vacía si el Excel de origen venía corrupto. Aquí en su
# lugar: contar → validar → DELETE+INSERT dentro de UNA transacción, preservando
# el schema existente. Si algo falla, rollback y la tabla queda intacta.
#
# Agnóstico al motor: usa solo SQL estándar (DELETE, COUNT) + to_sql append, así
# que funciona igual en SQLite y en PostgreSQL/analytics (el search_path lo fija
# el listener de _make_engine).
# ═════════════════════════════════════════════════════════════════════════════


class ValidacionError(Exception):
    """Las validaciones previas a la escritura fallaron; la tabla NO se tocó.

    Lleva la lista de problemas detectados para un log claro y un exit code != 0
    en los entry points (clave para el job desatendido de los lunes).
    """

    def __init__(self, tabla: str, problemas: list[str]):
        self.tabla = tabla
        self.problemas = list(problemas)
        detalle = "\n".join(f"    - {p}" for p in self.problemas)
        super().__init__(
            f"Validación de '{tabla}' falló ({len(self.problemas)} problema(s)); "
            f"la tabla NO se modificó:\n{detalle}"
        )


def conteo_filas(engine, tabla: str):
    """Número de filas en `tabla`, o None si la tabla aún no existe.

    None distingue "tabla inexistente" (primera carga) de "tabla vacía"
    (conteo 0), lo que cambia si el swap debe ejecutar DELETE o solo crear.
    """
    if not inspect(engine).has_table(tabla):
        return None
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {tabla}")).scalar()


def swap_tabla(engine, tabla: str, df, *, existe: bool) -> None:
    """DELETE + INSERT de `df` en `tabla` dentro de UNA sola transacción.

    Preserva el schema existente (nunca DROP ni if_exists="replace"). Si la tabla
    no existe (`existe=False`), to_sql append la crea. Cualquier error en el
    INSERT revierte también el DELETE: la tabla queda como estaba.

    `tabla` es un identificador interno controlado ("facturas"/"scores_clientes"),
    no entrada de usuario, por eso se interpola directo en el DELETE.
    """
    with engine.begin() as conn:
        if existe:
            conn.execute(text(f"DELETE FROM {tabla}"))
        df.to_sql(tabla, conn, if_exists="append", index=False)
