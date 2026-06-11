"""002: constraints y tipos reales en analytics.facturas.

Escrita contra el schema VIVO de Postgres (el que pandas dejó con
to_sql if_exists="replace"), NO contra lo que declaró la 001. Estado real al
escribir esta migración (inspección de information_schema, 374 filas):

    folio          bigint              -> se vuelve PK NOT NULL
    cliente        text  nullable      -> NOT NULL
    total          float8 nullable     -> NOT NULL
    fecha_factura  timestamp nullable  -> date (hora siempre 00:00, sin pérdida)
    fecha_pago     timestamp nullable  -> date (135 NULL = impagadas; sigue nullable)
    dias_pago      float8 nullable     -> integer nullable (NaN -> NULL; valores enteros)

Sólo aplica en PostgreSQL. En SQLite (fallback de desarrollo) es un no-op:
SQLite no soporta ALTER COLUMN TYPE ni ADD CONSTRAINT vía ALTER, y el problema
de drift es exclusivo de Postgres.

Seguridad: antes de crear la PRIMARY KEY/UNIQUE, verifica que no haya folios
duplicados ni NULLs en folio/cliente/total. Si los hay, ABORTA con un mensaje
claro y NO borra nada — la decisión de cómo resolver duplicados es humana.

Revision ID: 002
Revises: 001
Create Date: 2026-06-11
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "analytics"


def _upgrade_sql(schema: str) -> list[str]:
    """DDL de upgrade, parametrizado por schema (reutilizable en pruebas)."""
    t = f'"{schema}"."facturas"'
    return [
        # timestamp (hora 00:00) -> date, sin pérdida.
        f"ALTER TABLE {t} ALTER COLUMN fecha_factura TYPE date "
        f"USING fecha_factura::date",
        f"ALTER TABLE {t} ALTER COLUMN fecha_pago TYPE date "
        f"USING fecha_pago::date",
        # double precision -> integer nullable. NaN -> NULL (defensivo: en PG
        # NaN = 'NaN'::float8 es TRUE). Los valores son enteros, round() es exacto.
        f"ALTER TABLE {t} ALTER COLUMN dias_pago TYPE integer USING ("
        f"CASE WHEN dias_pago = 'NaN'::float8 THEN NULL "
        f"ELSE round(dias_pago)::integer END)",
        # NOT NULL en las columnas no opcionales.
        f"ALTER TABLE {t} ALTER COLUMN folio SET NOT NULL",
        f"ALTER TABLE {t} ALTER COLUMN cliente SET NOT NULL",
        f"ALTER TABLE {t} ALTER COLUMN total SET NOT NULL",
        # PRIMARY KEY(folio): provee también UNIQUE(folio) y NOT NULL(folio).
        f"ALTER TABLE {t} ADD CONSTRAINT pk_facturas PRIMARY KEY (folio)",
    ]


def _downgrade_sql(schema: str) -> list[str]:
    """DDL de downgrade: revierte al schema previo (el que dejó pandas)."""
    t = f'"{schema}"."facturas"'
    return [
        f"ALTER TABLE {t} DROP CONSTRAINT IF EXISTS pk_facturas",
        f"ALTER TABLE {t} ALTER COLUMN folio DROP NOT NULL",
        f"ALTER TABLE {t} ALTER COLUMN cliente DROP NOT NULL",
        f"ALTER TABLE {t} ALTER COLUMN total DROP NOT NULL",
        f"ALTER TABLE {t} ALTER COLUMN dias_pago TYPE double precision "
        f"USING dias_pago::double precision",
        f"ALTER TABLE {t} ALTER COLUMN fecha_pago TYPE timestamp "
        f"USING fecha_pago::timestamp",
        f"ALTER TABLE {t} ALTER COLUMN fecha_factura TYPE timestamp "
        f"USING fecha_factura::timestamp",
    ]


def _check_constraints_viables(bind, schema: str) -> None:
    """Aborta (sin tocar nada) si los datos impiden PK/UNIQUE o NOT NULL."""
    dups = bind.execute(sa.text(
        f'SELECT folio, count(*) AS n FROM "{schema}".facturas '
        f"GROUP BY folio HAVING count(*) > 1 ORDER BY n DESC"
    )).fetchall()
    if dups:
        muestra = ", ".join(f"folio={r[0]!r}×{r[1]}" for r in dups[:10])
        raise RuntimeError(
            f"002 ABORTADA: {len(dups)} folio(s) duplicado(s) en {schema}.facturas "
            f"impiden PRIMARY KEY/UNIQUE(folio). NO se modificó ni borró nada. "
            f"Ejemplos: {muestra}. Resuelve los duplicados manualmente y decide "
            f"qué fila conservar antes de re-aplicar la migración."
        )

    for col in ("folio", "cliente", "total"):
        n = bind.execute(sa.text(
            f'SELECT count(*) FROM "{schema}".facturas WHERE {col} IS NULL'
        )).scalar()
        if n:
            raise RuntimeError(
                f"002 ABORTADA: {n} fila(s) con {col} NULL en {schema}.facturas "
                f"impiden NOT NULL. NO se modificó nada. Limpia esas filas primero."
            )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        print("002: no-op en SQLite (constraints/tipos específicos de PostgreSQL).")
        return
    # El guard de datos necesita una conexión viva; en modo offline (--sql) se
    # omite y sólo se emite el DDL.
    if not context.is_offline_mode():
        _check_constraints_viables(bind, _SCHEMA)
    for sql in _upgrade_sql(_SCHEMA):
        op.execute(sql)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for sql in _downgrade_sql(_SCHEMA):
        op.execute(sql)
