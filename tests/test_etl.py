"""Tests del ETL (src/etl/load_facturas): _parsear_fechas y extraer_facturas.

Aislado: CERO lectura de data/raw/. extraer_facturas() se prueba contra un
mini-Excel sintetico escrito en tmp_path, monkeypatcheando ARCHIVO_FACTURAS.
Los resultados esperados estan calculados a mano (ver comentarios).
"""

import numpy as np
import pandas as pd
import pytest

import src.etl.load_facturas as load_facturas
from src.etl.load_facturas import _parsear_fechas, extraer_facturas


# ── _parsear_fechas ───────────────────────────────────────────────────────────

def test_parsear_fechas_como_en_produccion():
    # En produccion la columna llega MIXTA: las fechas "nuevas" (ISO) vienen como
    # celdas datetime reales de Excel -> pandas las entrega como Timestamp; las
    # "viejas" vienen como texto dd/mm/yyyy. Asi _parsear_fechas maneja ambas.
    s = pd.Series([
        pd.Timestamp("2025-03-12"),  # ISO como celda datetime -> pasa directo
        "26/11/2025",                # dd/mm texto -> 26-nov-2025 (dayfirst)
        "01/02/2025",                # dd/mm texto -> 1-feb-2025 (dia primero, NO 2-ene)
        "no es fecha",               # basura -> NaT
        None,                        # vacio  -> NaT
    ], dtype=object)
    out = _parsear_fechas(s)
    assert out.iloc[0] == pd.Timestamp("2025-03-12")
    assert out.iloc[1] == pd.Timestamp("2025-11-26")
    assert out.iloc[2] == pd.Timestamp("2025-02-01")   # dayfirst: 1 de febrero
    assert pd.isna(out.iloc[3])
    assert pd.isna(out.iloc[4])


def test_parsear_fechas_strings_iso_mezclados_es_fragil():
    # GOTCHA documentado (comportamiento actual a observar): si las fechas ISO
    # llegaran como TEXTO mezclado con dd/mm, pandas infiere UN solo formato (el
    # del primer elemento) y coerciona el resto a NaT. El ETL "funciona" solo
    # porque las ISO vienen como celdas datetime, no como texto. Si algun dia el
    # Excel trae ISO en texto, ESTAS se perderian silenciosamente (NaT).
    s = pd.Series(["26/11/2025", "2025-03-12 00:00:00", "basura"], dtype=object)
    out = _parsear_fechas(s)
    assert out.iloc[0] == pd.Timestamp("2025-11-26")   # formato dd/mm inferido: OK
    assert pd.isna(out.iloc[1])                         # ISO EN TEXTO -> NaT (!)
    assert pd.isna(out.iloc[2])


# ── extraer_facturas (mini-Excel sintetico) ───────────────────────────────────

@pytest.fixture
def mini_excel(tmp_path, monkeypatch):
    """Escribe un Excel sintetico en tmp_path y apunta ARCHIVO_FACTURAS a el."""
    # Columna ' Total ' con espacios A PROPOSITO: el ETL hace columns.str.strip().
    df = pd.DataFrame({
        "Folio":         [1, 2, 3, 4, 5, 6],
        "Cliente":       ["  toyoda  ", np.nan, "ACME", "acme s.a.", "ZZZ", "TOYODA"],
        # folio 4 lleva la fecha ISO como celda datetime REAL (como la guarda
        # Excel para las filas nuevas), no como texto; las demas son dd/mm texto.
        "Fecha":         ["01/03/2025", "05/03/2025", "10/03/2025",
                          pd.Timestamp("2025-03-12"), "no es fecha", "15/03/2025"],
        "Concepto":      ["MANT", "CANCELADA", "REPARACION", "INSTALACION", "X", "MANT"],
        " Total ":       [1000.0, 999.0, 500.0, 2000.0, 300.0, 300.0],
        "FECHA DE PAGO": ["11/03/2025", np.nan, "05/03/2025", np.nan, "01/04/2025", "20/03/2025"],
    })
    ruta = tmp_path / "mini_facturas.xlsx"
    df.to_excel(ruta, index=False)
    monkeypatch.setattr(load_facturas, "ARCHIVO_FACTURAS", ruta)
    return ruta


def test_extraer_facturas_limpieza_y_normalizacion(mini_excel):
    out = extraer_facturas().set_index("folio")

    # Filas validas: 1, 3, 4, 6. Se eliminan:
    #   folio 2 -> Cliente NaN (cancelada / separador)
    #   folio 5 -> Fecha 'no es fecha' -> NaT -> dropna(subset=['fecha_factura'])
    assert sorted(out.index.tolist()) == [1, 3, 4, 6]

    # Columnas finales del ETL (folio quedo como indice)
    assert list(out.columns) == [
        "cliente", "fecha_factura", "concepto", "total",
        "fecha_pago", "dias_pago", "pagada",
    ]

    # Normalizacion de cliente: strip + upper. '  toyoda  ' y 'TOYODA' COLAPSAN.
    assert out.loc[1, "cliente"] == "TOYODA"
    assert out.loc[6, "cliente"] == "TOYODA"
    assert out.loc[4, "cliente"] == "ACME S.A."
    assert (out["cliente"] == "TOYODA").sum() == 2   # 2 variantes -> 1 cliente

    # Columna ' Total ' (con espacios) quedo accesible como 'total'
    assert out.loc[1, "total"] == 1000.0

    # folio 1: factura 01-mar, pago 11-mar -> 10 dias, pagada
    assert out.loc[1, "fecha_factura"] == pd.Timestamp("2025-03-01")
    assert out.loc[1, "dias_pago"] == 10
    assert out.loc[1, "pagada"] == 1

    # folio 4: fecha ISO, SIN fecha de pago -> impagada, dias_pago NaN
    assert out.loc[4, "fecha_factura"] == pd.Timestamp("2025-03-12")
    assert out.loc[4, "pagada"] == 0
    assert pd.isna(out.loc[4, "fecha_pago"])
    assert pd.isna(out.loc[4, "dias_pago"])


def test_dias_pago_clip_enmascara_fechas_invertidas(mini_excel):
    out = extraer_facturas().set_index("folio")
    # folio 3: fecha_factura = 10-mar, fecha_pago = 05-mar (ANTES de facturar).
    # La diferencia real es -5 dias. El ETL hace clip(lower=0), asi que el valor
    # se ENMASCARA a 0 en lugar de quedar negativo.
    #
    # COMPORTAMIENTO ACTUAL A CONSERVAR (por ahora): este test documenta que el
    # clip OCULTA fechas invertidas (no las marca ni descarta). Si en el futuro se
    # decide tratarlas distinto (NaN / flag de revision), actualizar este test
    # conscientemente.
    assert out.loc[3, "fecha_factura"] == pd.Timestamp("2025-03-10")
    assert out.loc[3, "fecha_pago"] == pd.Timestamp("2025-03-05")
    assert out.loc[3, "dias_pago"] == 0          # -5 enmascarado a 0 por el clip
    assert out.loc[3, "pagada"] == 1
