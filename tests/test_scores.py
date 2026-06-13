"""Tests de scoring (src/models/client_score): calcular_features y calcular_scores.

Clientes sinteticos con resultados calculados A MANO (aritmetica en comentarios).
MinMaxScaler escala cada feature: x_scaled = (x - min) / (max - min); el score es
x_scaled * 100, redondeado a 2 decimales.

Aislado: sin DB, sin data/raw/. Estos scores deciden sobre clientes reales, asi
que el calculo se verifica numero a numero.
"""

import numpy as np
import pandas as pd
import pytest

from src.models.client_score import calcular_features, calcular_scores


# ── calcular_features: agregacion + imputacion p95 ────────────────────────────

def test_calcular_features_agregacion_e_imputacion():
    # Facturas (una fila por factura). 3 clientes, con casos borde:
    #   X: 2 facturas pagadas (dias 4 y 6)              -> avg 5, pct 0
    #   Y: 1 factura pagada en 0 dias (borde: 1 factura) -> avg 0, pct 0
    #   Z: 2 facturas 100% impagadas (borde: impago)     -> avg NaN -> imputado p95
    df = pd.DataFrame({
        "cliente":   ["X", "X", "Y", "Z", "Z"],
        "total":     [100.0, 200.0, 500.0, 1000.0, 1000.0],
        "pagada":    [1, 1, 1, 0, 0],
        "dias_pago": [4.0, 6.0, 0.0, np.nan, np.nan],
    })
    feat = calcular_features(df).set_index("cliente")

    # n_facturas (count) y monto_total (sum)
    assert feat.loc["X", "n_facturas"] == 2
    assert feat.loc["X", "monto_total"] == 300.0      # 100 + 200
    assert feat.loc["Y", "n_facturas"] == 1
    assert feat.loc["Z", "monto_total"] == 2000.0     # 1000 + 1000

    # pct_impagadas = n_impagadas / n_facturas
    assert feat.loc["X", "pct_impagadas"] == 0.0
    assert feat.loc["Z", "pct_impagadas"] == 1.0      # 2 de 2 impagadas

    # avg_dias_pago: promedio SOLO de facturas pagadas
    assert feat.loc["X", "avg_dias_pago"] == 5.0      # (4 + 6) / 2
    assert feat.loc["Y", "avg_dias_pago"] == 0.0      # unica factura, 0 dias

    # Z nunca pago -> avg_dias_pago imputado con p95 de TODOS los dias_pago.
    #   dias_pago no-nulos = [4, 6, 0]; quantile(0.95) lineal:
    #   sorted [0, 4, 6], pos = 0.95*(3-1) = 1.9 -> 4 + 0.9*(6-4) = 5.8
    assert feat.loc["Z", "avg_dias_pago"] == pytest.approx(5.8)


# ── calcular_scores: 4 clientes, MinMax calculado a mano ──────────────────────

@pytest.fixture
def features_4():
    # cliente | n_facturas | monto_total | avg_dias_pago | pct_impagadas
    #   A: 1 factura, pagado en 0 dias (bordes: 1 factura + 0 dias + 0% impago)
    #   C: 100% impagado
    return pd.DataFrame({
        "cliente":       ["A", "B", "C", "D"],
        "n_facturas":    [1, 10, 5, 20],
        "monto_total":   [1000.0, 10000.0, 5000.0, 50000.0],
        "avg_dias_pago": [0.0, 10.0, 30.0, 60.0],
        "pct_impagadas": [0.0, 0.5, 1.0, 0.25],
    })


def test_score_pago(features_4):
    sc = calcular_scores(features_4).set_index("cliente")["score_pago"]
    # score_pago = (1 - minmax(avg_dias_pago)) * 100 ; avg_dias_pago en [0, 60]
    #   A: (1 - 0/60)  * 100 = 100.00   (paga al instante -> mejor pagador)
    #   B: (1 - 10/60) * 100 =  83.33
    #   C: (1 - 30/60) * 100 =  50.00
    #   D: (1 - 60/60) * 100 =   0.00   (el mas lento)
    assert sc["A"] == pytest.approx(100.00, abs=0.01)
    assert sc["B"] == pytest.approx(83.33, abs=0.01)
    assert sc["C"] == pytest.approx(50.00, abs=0.01)
    assert sc["D"] == pytest.approx(0.00, abs=0.01)


def test_score_riesgo(features_4):
    sc = calcular_scores(features_4).set_index("cliente")["score_riesgo"]
    # score_riesgo = (0.6*minmax(pct_impagadas) + 0.4*minmax(avg_dias_pago)) * 100
    #   minmax(pct)  en [0, 1]:   A 0     B 0.5      C 1     D 0.25
    #   minmax(dias) en [0, 60]:  A 0     B 0.16667  C 0.5   D 1
    #   A: (0.6*0    + 0.4*0)       * 100 =  0.00
    #   B: (0.6*0.5  + 0.4*0.16667) * 100 = (0.30 + 0.06667) * 100 = 36.67
    #   C: (0.6*1.0  + 0.4*0.5)     * 100 = (0.60 + 0.20)    * 100 = 80.00  (100% impago)
    #   D: (0.6*0.25 + 0.4*1.0)     * 100 = (0.15 + 0.40)    * 100 = 55.00
    assert sc["A"] == pytest.approx(0.00, abs=0.01)
    assert sc["B"] == pytest.approx(36.67, abs=0.01)
    assert sc["C"] == pytest.approx(80.00, abs=0.01)
    assert sc["D"] == pytest.approx(55.00, abs=0.01)


def test_score_valor(features_4):
    sc = calcular_scores(features_4).set_index("cliente")["score_valor"]
    # score_valor = minmax(log1p(n_facturas) * log1p(monto_total)) * 100
    #   val(A) = ln(2)  * ln(1001)   = 0.693147 * 6.908755  =  4.78878
    #   val(B) = ln(11) * ln(10001)  = 2.397895 * 9.210440  = 22.08567
    #   val(C) = ln(6)  * ln(5001)   = 1.791759 * 8.517393  = 15.26112
    #   val(D) = ln(21) * ln(50001)  = 3.044522 * 10.819798 = 32.94112
    #   min = val(A), max = val(D), rango = 32.94112 - 4.78878 = 28.15234
    #   A: 0                                  -> 0.00
    #   B: (22.08567 - 4.78878)/28.15234*100  -> 61.44
    #   C: (15.26112 - 4.78878)/28.15234*100  -> 37.20
    #   D: 100                                -> 100.00
    assert sc["A"] == pytest.approx(0.00, abs=0.02)
    assert sc["B"] == pytest.approx(61.44, abs=0.02)
    assert sc["C"] == pytest.approx(37.20, abs=0.02)
    assert sc["D"] == pytest.approx(100.00, abs=0.02)


def test_scores_en_rango_0_100(features_4):
    sc = calcular_scores(features_4)
    for col in ("score_pago", "score_valor", "score_riesgo"):
        assert sc[col].between(0, 100).all()
