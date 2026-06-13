"""Crear tablas iniciales en el schema analytics.

Diseñada para PostgreSQL. En SQLite crea las tablas sin schema
(SQLite no soporta schemas).

Revision ID: 001
Revises:
Create Date: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "analytics"


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS analytics"))

    schema = _SCHEMA if is_pg else None

    op.create_table(
        "facturas",
        sa.Column("folio", sa.Integer(), nullable=True),
        sa.Column("cliente", sa.Text(), nullable=True),
        sa.Column("fecha_factura", sa.Text(), nullable=True),
        sa.Column("concepto", sa.Text(), nullable=True),
        sa.Column("total", sa.Float(), nullable=True),
        sa.Column("fecha_pago", sa.Text(), nullable=True),
        sa.Column("dias_pago", sa.Integer(), nullable=True),
        sa.Column("pagada", sa.Integer(), nullable=True),
        schema=schema,
    )

    op.create_table(
        "scores_clientes",
        sa.Column("cliente", sa.Text(), nullable=True),
        sa.Column("n_facturas", sa.Integer(), nullable=True),
        sa.Column("monto_total", sa.Float(), nullable=True),
        sa.Column("avg_dias_pago", sa.Float(), nullable=True),
        sa.Column("pct_impagadas", sa.Float(), nullable=True),
        sa.Column("score_pago", sa.Float(), nullable=True),
        sa.Column("score_valor", sa.Float(), nullable=True),
        sa.Column("score_riesgo", sa.Float(), nullable=True),
        sa.Column("fecha_calculo", sa.Text(), nullable=True),
        schema=schema,
    )


def downgrade() -> None:
    bind = op.get_bind()
    schema = _SCHEMA if bind.dialect.name == "postgresql" else None

    op.drop_table("scores_clientes", schema=schema)
    op.drop_table("facturas", schema=schema)
