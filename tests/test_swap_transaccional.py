"""Swap transaccional DELETE+INSERT (`src.db.swap_tabla`) y `cargar_en_db`.

Verifica que:
  - la primera carga crea la tabla e inserta,
  - una carga válida reemplaza las filas preservando el schema (PK incluido),
  - una validación fallida (Excel corrupto) NO toca la tabla,
  - el swap es atómico: si el INSERT falla, el DELETE se revierte (rollback).
"""

import pandas as pd
import pytest
from sqlalchemy import inspect, text

from src.db import ValidacionError, conteo_filas, swap_tabla
from src.etl.load_facturas import cargar_en_db


# Schema "a mano" con PRIMARY KEY, como lo crearía una migración real.
# Si cargar_en_db usara if_exists="replace", pandas recrearía la tabla y este
# PK desaparecería — los tests de abajo lo detectan.
SCHEMA_FACTURAS = """
    CREATE TABLE facturas (
        folio INTEGER PRIMARY KEY,
        cliente TEXT NOT NULL,
        fecha_factura TEXT,
        concepto TEXT,
        total REAL,
        fecha_pago TEXT,
        dias_pago REAL,
        pagada INTEGER
    )
"""


def test_conteo_filas_none_si_no_existe(engine):
    assert conteo_filas(engine, "facturas") is None


def test_primera_carga_crea_tabla_e_inserta(engine, make_facturas):
    cargar_en_db(make_facturas(100), engine)
    assert conteo_filas(engine, "facturas") == 100


def test_segunda_carga_reemplaza_filas(engine, make_facturas):
    cargar_en_db(make_facturas(100), engine)
    cargar_en_db(make_facturas(120), engine)
    assert conteo_filas(engine, "facturas") == 120


def test_swap_preserva_schema_y_pk(engine, make_facturas):
    with engine.begin() as conn:
        conn.execute(text(SCHEMA_FACTURAS))
    cargar_en_db(make_facturas(100), engine)      # tabla vacía pre-creada → llena
    cargar_en_db(make_facturas(120), engine)      # swap
    assert conteo_filas(engine, "facturas") == 120
    pk = inspect(engine).get_pk_constraint("facturas")
    assert pk["constrained_columns"] == ["folio"]  # replace lo habría borrado


def test_validacion_fallida_no_toca_tabla(engine, make_facturas):
    cargar_en_db(make_facturas(100), engine)             # 100 filas buenas
    with pytest.raises(ValidacionError):
        cargar_en_db(make_facturas(50), engine)          # 50 < 90% → abortar
    assert conteo_filas(engine, "facturas") == 100       # intacta


def test_swap_atomico_rollback_si_falla_insert(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (folio INTEGER, cliente TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO t (folio, cliente) VALUES (1, 'A'), (2, 'B')"))
    # cliente NULL viola NOT NULL → el INSERT del swap falla a media transacción,
    # después de que el DELETE ya borró las filas originales.
    malo = pd.DataFrame({"folio": [3, 4], "cliente": [None, None]})
    with pytest.raises(Exception):
        swap_tabla(engine, "t", malo, existe=True)
    with engine.connect() as conn:
        # rollback: las 2 filas originales siguen ahí (DELETE+INSERT eran 1 tx)
        assert conn.execute(text("SELECT COUNT(*) FROM t")).scalar() == 2
