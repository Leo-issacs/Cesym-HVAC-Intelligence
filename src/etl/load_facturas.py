"""
ETL: Excel de facturas → tabla `facturas` en SQLite.

Limpieza que aplica:
  - Elimina filas canceladas (cliente NaN)
  - Normaliza nombres de cliente: strip + mayúsculas
  - Parsea dos formatos de fecha que conviven en el Excel:
      · "dd/mm/yyyy"            (ej. "26/11/2025")
      · "yyyy-mm-dd HH:MM:SS"  (ej. "2025-03-12 00:00:00")
  - Calcula dias_pago = fecha_pago - fecha_factura (mínimo 0)
  - Marca cada factura como pagada/impagada

Uso como módulo: from src.etl.load_facturas import run
"""

import pathlib
import pandas as pd
from sqlalchemy import create_engine, text

# Raíz del proyecto: subimos 2 niveles desde src/etl/
ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "db" / "hvac.db"

ARCHIVO_FACTURAS = RAW_DIR / "reporteMensual_FACTURAS.xlsx"


def _parsear_fechas(serie: pd.Series) -> pd.Series:
    """
    Convierte una columna de fechas con formato mixto a datetime.

    El Excel tiene dos formatos mezclados:
      - Filas antiguas:  "26/11/2025"  → día/mes/año (dayfirst=True)
      - Filas nuevas:    "2025-03-12 00:00:00"  → ya en ISO

    pd.to_datetime con dayfirst=True maneja ambos correctamente.
    errors="coerce" convierte cualquier valor no reconocible a NaT
    en vez de lanzar una excepción.
    """
    return pd.to_datetime(serie, dayfirst=True, errors="coerce")


def extraer_facturas() -> pd.DataFrame:
    """
    Lee el Excel de facturas, limpia y estandariza los datos.

    Returns
    -------
    pd.DataFrame con columnas:
        folio, cliente, fecha_factura, concepto, total,
        fecha_pago, dias_pago, pagada
    """
    df = pd.read_excel(ARCHIVO_FACTURAS)

    # Los nombres de columna del Excel tienen espacios extra (' Total ')
    df.columns = df.columns.str.strip()

    # ── Eliminar filas vacías/canceladas ─────────────────────────────────────
    # Las filas con cliente NaN son canceleaciones o separadores visuales
    df = df.dropna(subset=["Cliente"]).copy()

    # ── Normalizar nombres de cliente ────────────────────────────────────────
    # "TOYODA  " y "TOYODA" son el mismo cliente; strip + upper los unifica
    df["Cliente"] = df["Cliente"].str.strip().str.upper()

    # ── Parsear fechas ───────────────────────────────────────────────────────
    df["fecha_factura"] = _parsear_fechas(df["Fecha"])
    df["fecha_pago"] = _parsear_fechas(df["FECHA DE PAGO"])

    # Eliminar filas donde la fecha de factura no pudo parsearse
    df = df.dropna(subset=["fecha_factura"]).copy()

    # ── Calcular días de pago ────────────────────────────────────────────────
    # Algunas filas tienen fecha_pago anterior a fecha_factura (pagos
    # anticipados o errores de captura). Usamos clip(lower=0) para no tener
    # valores negativos que distorsionen el score.
    df["dias_pago"] = (
        (df["fecha_pago"] - df["fecha_factura"])
        .dt.days
        .clip(lower=0)       # nunca negativo
    )

    # 1 = factura con fecha de pago registrada, 0 = pendiente/impagada
    df["pagada"] = df["fecha_pago"].notna().astype(int)

    # ── Renombrar y seleccionar columnas finales ─────────────────────────────
    df = df.rename(columns={
        "Folio": "folio",
        "Cliente": "cliente",
        "Concepto": "concepto",
        "Total": "total",
    })

    return df[[
        "folio", "cliente", "fecha_factura", "concepto",
        "total", "fecha_pago", "dias_pago", "pagada",
    ]]


def cargar_en_db(df: pd.DataFrame, engine, limpiar: bool = False) -> None:
    """
    Escribe el DataFrame en la tabla `facturas` de SQLite.

    Parameters
    ----------
    limpiar : bool
        Si True, borra la tabla antes de escribir (útil para recargas completas).
        Si False, reemplaza igualmente (comportamiento de if_exists="replace").
    """
    if limpiar:
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS facturas"))
            conn.commit()

    # to_sql con if_exists="replace" crea la tabla si no existe,
    # o la reemplaza si ya existe. index=False evita guardar el índice de pandas.
    df.to_sql("facturas", engine, if_exists="replace", index=False)
    print(f"  ✓ {len(df)} filas en tabla 'facturas'")


def run(limpiar: bool = False) -> None:
    """Ejecuta el ETL completo: Excel → SQLite."""
    print(f"Leyendo {ARCHIVO_FACTURAS.name} ...")
    df = extraer_facturas()
    print(f"  {len(df)} filas válidas tras limpieza")
    print(f"  {df['cliente'].nunique()} clientes únicos")
    print(f"  {df['pagada'].sum()} facturas pagadas / {(df['pagada'] == 0).sum()} pendientes")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{DB_PATH}")

    print(f"\nCargando en {DB_PATH.relative_to(ROOT)} ...")
    cargar_en_db(df, engine, limpiar=limpiar)
    print("ETL completado.\n")
