"""Tests de `validar_facturas`: guardas previas a escribir la tabla `facturas`.

Casos sintéticos, sin tocar la base de datos. Cubren los tres síntomas de un
Excel corrupto que el job desatendido de los lunes podría intentar cargar:
  - caída de volumen (conteo nuevo < 90% del actual),
  - folios duplicados,
  - fecha_factura sin parsear (NaT).
"""

import pandas as pd

from src.etl.load_facturas import validar_facturas


def test_df_valido_sin_problemas(make_facturas):
    assert validar_facturas(make_facturas(100), conteo_actual=100) == []


def test_caida_de_volumen_falla(make_facturas):
    # 50 filas nuevas vs 100 actuales → 50 < 90 (90% de 100)
    problemas = validar_facturas(make_facturas(50), conteo_actual=100)
    assert any("90%" in p or "Caída" in p for p in problemas)


def test_volumen_en_el_umbral_no_falla(make_facturas):
    # 90 == 90% de 100 → permitido (la guarda es estrictamente < 90%)
    assert validar_facturas(make_facturas(90), conteo_actual=100) == []


def test_primera_carga_sin_conteo_actual_no_falla(make_facturas):
    # conteo_actual=0 (tabla nueva/vacía): no aplica la guarda de volumen
    assert validar_facturas(make_facturas(3), conteo_actual=0) == []


def test_folios_duplicados_falla(make_facturas):
    df = make_facturas(10)
    df.loc[5, "folio"] = df.loc[4, "folio"]
    problemas = validar_facturas(df, conteo_actual=10)
    assert any("duplicad" in p.lower() for p in problemas)


def test_fecha_factura_no_parseada_falla(make_facturas):
    df = make_facturas(10)
    df.loc[3, "fecha_factura"] = pd.NaT
    problemas = validar_facturas(df, conteo_actual=10)
    assert any("fecha_factura" in p for p in problemas)


def test_fecha_pago_nat_es_valida(make_facturas):
    # NaT en fecha_pago es legítimo (factura impagada): NO debe fallar
    df = make_facturas(10)
    df.loc[2, "fecha_pago"] = pd.NaT
    df.loc[2, "pagada"] = 0
    assert validar_facturas(df, conteo_actual=10) == []


def test_df_vacio_falla(make_facturas):
    problemas = validar_facturas(make_facturas(0), conteo_actual=100)
    assert any("vac" in p.lower() for p in problemas)


def test_reporta_multiples_problemas_a_la_vez(make_facturas):
    df = make_facturas(5)                      # 5 < 90% de 100
    df.loc[1, "folio"] = df.loc[0, "folio"]    # folio duplicado
    df.loc[2, "fecha_factura"] = pd.NaT        # fecha sin parsear
    problemas = validar_facturas(df, conteo_actual=100)
    assert len(problemas) >= 3
