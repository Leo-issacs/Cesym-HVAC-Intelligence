"""Validación y swap transaccional de `scores_clientes` (client_score.py).

`validar_scores` aplica el patrón análogo a facturas: la clave lógica es
`cliente` (una fila por cliente), así que las guardas son volumen, cliente nulo
y clientes duplicados. `guardar_resultados` debe escribir con el mismo swap
transaccional y, si la validación falla, dejar la tabla intacta.
"""

import pandas as pd
import pytest

from src.db import ValidacionError, conteo_filas
from src.models.client_score import validar_scores


def test_scores_validos(make_scores_df):
    assert validar_scores(make_scores_df(10), conteo_actual=10) == []


def test_caida_de_volumen_falla(make_scores_df):
    problemas = validar_scores(make_scores_df(4), conteo_actual=10)
    assert problemas


def test_volumen_en_el_umbral_no_falla(make_scores_df):
    assert validar_scores(make_scores_df(9), conteo_actual=10) == []


def test_primera_carga_no_falla(make_scores_df):
    assert validar_scores(make_scores_df(2), conteo_actual=0) == []


def test_clientes_duplicados_falla(make_scores_df):
    df = make_scores_df(5)
    df.loc[2, "cliente"] = df.loc[1, "cliente"]
    problemas = validar_scores(df, conteo_actual=5)
    assert any("duplicad" in p.lower() for p in problemas)


def test_cliente_nulo_falla(make_scores_df):
    df = make_scores_df(5)
    df.loc[0, "cliente"] = None
    problemas = validar_scores(df, conteo_actual=5)
    assert any("cliente" in p.lower() for p in problemas)


def test_vacio_falla(make_scores_df):
    assert validar_scores(make_scores_df(0), conteo_actual=10)


def test_guardar_resultados_falla_no_toca_tabla(engine, tmp_path, monkeypatch):
    import src.models.client_score as cs

    # Evitar que el test escriba el CSV real de data/processed/.
    monkeypatch.setattr(cs, "CSV_OUT", tmp_path / "scores.csv")

    clientes = [f"CLIENTE {i}" for i in range(10)]
    features = pd.DataFrame({
        "cliente": clientes, "n_facturas": [5] * 10, "monto_total": [1000.0] * 10,
        "avg_dias_pago": [10.0] * 10, "pct_impagadas": [0.1] * 10,
    })
    scores = pd.DataFrame({
        "cliente": clientes, "score_pago": [80.0] * 10,
        "score_valor": [50.0] * 10, "score_riesgo": [20.0] * 10,
    })

    cs.guardar_resultados(features, scores, engine)          # 10 clientes buenos
    assert conteo_filas(engine, "scores_clientes") == 10

    # lote corrupto: 4 clientes (< 90% de 10) → abortar sin tocar la tabla
    with pytest.raises(ValidacionError):
        cs.guardar_resultados(features.head(4), scores.head(4), engine)
    assert conteo_filas(engine, "scores_clientes") == 10
