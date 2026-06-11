"""Configuración compartida de pytest: sys.path + fixtures de datos sintéticos.

Las pruebas corren contra un SQLite temporal (fixture `engine`). El código bajo
prueba (src/db.py, load_facturas, client_score) es agnóstico al motor: la única
diferencia con Postgres es el `search_path`, que resuelve el engine central de
src/db.py. Por eso validar el comportamiento transaccional en SQLite es
suficiente para ambos backends.
"""

import pathlib
import sys

import pandas as pd
import pytest
from sqlalchemy import create_engine

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def engine(tmp_path):
    """Engine SQLite temporal y aislado por test (archivo en tmp_path)."""
    eng = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def make_facturas():
    """Fábrica de DataFrames de facturas válidos (mismas columnas que el ETL)."""
    def _make(n=100, start_folio=1):
        return pd.DataFrame({
            "folio": list(range(start_folio, start_folio + n)),
            "cliente": [f"CLIENTE {i % 5}" for i in range(n)],
            "fecha_factura": pd.to_datetime(["2025-01-01"] * n),
            "concepto": ["SERVICIO"] * n,
            "total": [1000.0] * n,
            "fecha_pago": pd.to_datetime(["2025-01-10"] * n),
            "dias_pago": [9.0] * n,
            "pagada": [1] * n,
        })
    return _make


@pytest.fixture
def make_scores_df():
    """Fábrica del DataFrame ya armado de scores_clientes (una fila por cliente)."""
    def _make(n=10, start=0):
        clientes = [f"CLIENTE {i}" for i in range(start, start + n)]
        return pd.DataFrame({
            "cliente": clientes,
            "n_facturas": [5] * n,
            "monto_total": [1000.0] * n,
            "avg_dias_pago": [10.0] * n,
            "pct_impagadas": [0.1] * n,
            "score_pago": [80.0] * n,
            "score_valor": [50.0] * n,
            "score_riesgo": [20.0] * n,
            "fecha_calculo": ["2026-06-11"] * n,
        })
    return _make
