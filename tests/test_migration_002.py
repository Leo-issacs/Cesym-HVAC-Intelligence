"""Tests del DDL de la migración 002 (sin base de datos).

La migración se prueba contra Postgres en su harness dedicado; aquí sólo se
fija el DDL que genera, para que un edit accidental (p.ej. quitar el manejo
NaN→NULL, la PK, o un NOT NULL) rompa una prueba rápida y offline.

El módulo vive en alembic/versions/002_constraints.py; su nombre empieza con
dígito, así que se carga vía importlib.
"""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "mig002", ROOT / "alembic" / "versions" / "002_constraints.py"
)
mig002 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig002)


def test_revision_encadena_001():
    assert mig002.revision == "002"
    assert mig002.down_revision == "001"


def test_upgrade_sql_completo():
    sql = " ".join(mig002._upgrade_sql("analytics"))
    # tipos
    assert "fecha_factura TYPE date" in sql
    assert "fecha_pago TYPE date" in sql
    assert "dias_pago TYPE integer" in sql
    # NaN → NULL preservado
    assert "'NaN'::float8" in sql
    # NOT NULL en las tres columnas
    assert "folio SET NOT NULL" in sql
    assert "cliente SET NOT NULL" in sql
    assert "total SET NOT NULL" in sql
    # PK(folio) (cubre también UNIQUE(folio))
    assert "ADD CONSTRAINT pk_facturas PRIMARY KEY (folio)" in sql


def test_downgrade_revierte():
    sql = " ".join(mig002._downgrade_sql("analytics"))
    assert "DROP CONSTRAINT IF EXISTS pk_facturas" in sql
    assert "dias_pago TYPE double precision" in sql
    assert "fecha_factura TYPE timestamp" in sql
    assert "fecha_pago TYPE timestamp" in sql
    assert "folio DROP NOT NULL" in sql


def test_ddl_parametrizado_por_schema():
    # Reutilizable contra un schema clon (así se probó en analytics_test).
    up = " ".join(mig002._upgrade_sql("analytics_test"))
    assert '"analytics_test"."facturas"' in up
    assert '"analytics"."facturas"' not in up
