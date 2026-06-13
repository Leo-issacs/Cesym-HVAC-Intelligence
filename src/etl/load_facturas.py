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

import sys
import pathlib
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import (  # noqa: E402
    engine,
    is_postgres,
    SQLITE_DB_PATH,
    ValidacionError,
    conteo_filas,
    swap_tabla,
)

RAW_DIR = ROOT / "data" / "raw"
ARCHIVO_FACTURAS = RAW_DIR / "reporteMensual_FACTURAS.xlsx"

# Si el lote nuevo trae menos de este % de las filas actuales, lo tratamos como
# sospecha de Excel corrupto y abortamos sin tocar la tabla.
UMBRAL_CAIDA_VOLUMEN = 0.9


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


def validar_facturas(df: pd.DataFrame, conteo_actual: int = 0) -> list[str]:
    """
    Devuelve la lista de problemas que impiden escribir `df` en `facturas`.

    Lista vacía = el DataFrame es seguro de cargar. Guardas:
      - DataFrame vacío (nunca sobrescribir datos buenos con nada).
      - Caída de volumen: < 90% de las filas actuales (Excel corrupto/truncado).
      - Folios duplicados (el folio identifica la factura; duplicado = corrupción).
      - fecha_factura sin parsear (NaT) — fecha_pago NaT sí es válida (impagada).
    """
    problemas: list[str] = []
    n = len(df)

    if n == 0:
        problemas.append("El DataFrame de facturas está vacío.")

    if conteo_actual and n < UMBRAL_CAIDA_VOLUMEN * conteo_actual:
        umbral = UMBRAL_CAIDA_VOLUMEN * conteo_actual
        problemas.append(
            f"Caída de volumen sospechosa: {n} filas nuevas < 90% de las "
            f"{conteo_actual} actuales (umbral {umbral:.0f})."
        )

    folios = df["folio"].dropna()
    if folios.duplicated().any():
        dups = sorted(folios[folios.duplicated(keep=False)].unique().tolist())
        problemas.append(f"Folios duplicados: {dups}")

    if df["fecha_factura"].isna().any():
        n_nat = int(df["fecha_factura"].isna().sum())
        problemas.append(f"{n_nat} fila(s) con fecha_factura no parseada (NaT).")

    return problemas


def cargar_en_db(df: pd.DataFrame, engine, limpiar: bool = False) -> None:
    """
    Valida el DataFrame y, si pasa, reemplaza el contenido de `facturas` con un
    DELETE+INSERT dentro de una sola transacción (ver src.db.swap_tabla).

    Nunca usa if_exists="replace": el schema existente (tipos, PK, constraints)
    se respeta. Si la validación falla, lanza ValidacionError y NO toca la tabla.

    `limpiar` se conserva por compatibilidad con los entry points; como el swap
    siempre refresca el total de filas, ya no es necesario dropear la tabla (y
    dropearla destruiría el schema, justo lo que queremos evitar).
    """
    conteo_actual = conteo_filas(engine, "facturas")

    problemas = validar_facturas(df, conteo_actual or 0)
    if problemas:
        raise ValidacionError("facturas", problemas)

    swap_tabla(engine, "facturas", df, existe=conteo_actual is not None)
    print(f"  ✓ {len(df)} filas en 'facturas' (swap transaccional, schema intacto)")


def run(limpiar: bool = False) -> None:
    """Ejecuta el ETL completo: Excel → base de datos."""
    print(f"Leyendo {ARCHIVO_FACTURAS.name} ...")
    df = extraer_facturas()
    print(f"  {len(df)} filas válidas tras limpieza")
    print(f"  {df['cliente'].nunique()} clientes únicos")
    print(f"  {df['pagada'].sum()} facturas pagadas / {(df['pagada'] == 0).sum()} pendientes")

    if not is_postgres:
        SQLITE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    db_label = "PostgreSQL · analytics" if is_postgres else str(SQLITE_DB_PATH.relative_to(ROOT))
    print(f"\nCargando en {db_label} ...")
    try:
        cargar_en_db(df, engine, limpiar=limpiar)
    except ValidacionError as e:
        print("\n✗ VALIDACIÓN FALLIDA — ETL abortado. La tabla 'facturas' quedó intacta.")
        print(e)
        sys.exit(1)
    print("ETL completado.\n")
