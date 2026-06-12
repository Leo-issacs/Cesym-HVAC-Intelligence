"""Completa la cobertura de validaciones: distincion entre tabla INEXISTENTE
(conteo_filas -> None, primera carga) y tabla VACIA (conteo 0).

El resto de las validaciones ya estan cubiertas por el PR de staging/swap:
  - validar_facturas (volumen, folios duplicados, fecha NaT): test_validar_facturas.py
  - validar_scores y guardar_resultados:                      test_client_score.py
  - swap transaccional / atomicidad / preserva schema:        test_swap_transaccional.py

Aqui solo se llena el hueco de la semantica de "primera carga". Aislado: SQLite
temporal via fixture `engine`.
"""

from sqlalchemy import text

from src.db import conteo_filas
from src.etl.load_facturas import cargar_en_db

# Schema minimo (sin constraints) solo para crear una tabla vacia a mano.
SCHEMA_VACIO = """
    CREATE TABLE facturas (
        folio INTEGER, cliente TEXT, fecha_factura TEXT, concepto TEXT,
        total REAL, fecha_pago TEXT, dias_pago REAL, pagada INTEGER
    )
"""


def test_conteo_filas_none_si_tabla_no_existe(engine):
    # Tabla inexistente -> None (NO 0). Es lo que permite distinguir la primera
    # carga (None) de una tabla con datos a la hora de aplicar la guarda de volumen.
    assert conteo_filas(engine, "facturas") is None


def test_conteo_filas_cero_si_tabla_existe_vacia(engine):
    with engine.begin() as c:
        c.execute(text(SCHEMA_VACIO))
    # Existe pero sin filas -> 0, no None. (Contraste con el caso anterior.)
    assert conteo_filas(engine, "facturas") == 0


def test_tabla_inexistente_es_primera_carga(engine, make_facturas):
    # conteo_actual None -> primera carga: un lote pequeno entra sin disparar la
    # guarda de caida de volumen (no hay nada que proteger todavia).
    cargar_en_db(make_facturas(3), engine)
    assert conteo_filas(engine, "facturas") == 3


def test_tabla_vacia_se_trata_como_primera_carga(engine, make_facturas):
    # Tabla EXISTE pero esta vacia (conteo 0): la guarda de volumen NO aplica,
    # igual que si no existiera.
    #
    # Contraste explicito: con 100 filas, un lote de 3 disparararia ValidacionError
    # (cubierto en test_swap_transaccional.py::test_validacion_fallida_no_toca_tabla).
    # Vaciando primero la tabla, ese mismo lote de 3 entra sin problema.
    cargar_en_db(make_facturas(100), engine)        # 100 filas
    with engine.begin() as c:
        c.execute(text("DELETE FROM facturas"))     # ahora vacia (conteo 0)
    assert conteo_filas(engine, "facturas") == 0

    cargar_en_db(make_facturas(3), engine)          # 3 << 90% de 100, pero vacia -> OK
    assert conteo_filas(engine, "facturas") == 3
