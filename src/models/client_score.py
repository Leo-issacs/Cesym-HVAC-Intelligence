"""
Módulo de scoring de clientes HVAC.

Calcula tres scores (0–100) por cliente basados en el historial de facturas:

  score_pago   → qué tan puntualmente paga (100 = paga al instante)
  score_valor  → qué tan importante es el cliente (100 = el más valioso)
  score_riesgo → probabilidad de que una factura tarde o no se pague (100 = máximo riesgo)

Pipeline:
  1. Extracción de facturas desde hvac.db con SQLAlchemy
  2. Cálculo de features agregadas por cliente con pandas
  3. Normalización a [0, 100] con MinMaxScaler de scikit-learn
  4. Persistencia: tabla `scores_clientes` en la DB + CSV en data/processed/
  5. Reporte en consola con los top 10 clientes por score de valor

Uso:
    python -X utf8 src/models/client_score.py
"""

import pathlib
import sys
from datetime import date

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from sqlalchemy import create_engine

# ── Rutas absolutas usando pathlib ────────────────────────────────────────────
# __file__ = src/models/client_score.py
# .parents[0] = src/models/
# .parents[1] = src/
# .parents[2] = raíz del proyecto
ROOT = pathlib.Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "db" / "hvac.db"
CSV_OUT = ROOT / "data" / "processed" / "scores_clientes.csv"


# ═════════════════════════════════════════════════════════════════════════════
# PASO 1 — Extracción desde la base de datos
# ═════════════════════════════════════════════════════════════════════════════

def cargar_facturas(engine) -> pd.DataFrame:
    """
    Lee la tabla `facturas` desde SQLite y devuelve un DataFrame.

    Usamos pd.read_sql + SQLAlchemy en lugar de sqlite3 directamente porque:
      - SQLAlchemy abstrae el motor de BD (cambiar a PostgreSQL solo requiere
        cambiar la URL del engine, sin tocar este código)
      - parse_dates convierte automáticamente las columnas de fecha a datetime64
    """
    query = """
        SELECT
            cliente,
            fecha_factura,
            fecha_pago,
            total,
            dias_pago,
            pagada
        FROM facturas
        WHERE cliente IS NOT NULL
          AND total IS NOT NULL
    """
    df = pd.read_sql(query, engine, parse_dates=["fecha_factura", "fecha_pago"])
    print(f"  {len(df)} facturas · {df['cliente'].nunique()} clientes únicos")
    return df


# ═════════════════════════════════════════════════════════════════════════════
# PASO 2 — Cálculo de features por cliente
# ═════════════════════════════════════════════════════════════════════════════

def calcular_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transforma la tabla de facturas (una fila por factura) en una tabla
    de features a nivel cliente (una fila por cliente).

    Features calculadas
    -------------------
    n_facturas    : total de facturas emitidas al cliente
    monto_total   : suma histórica de todos los totales facturados
    avg_dias_pago : promedio de días entre fecha_factura y fecha_pago,
                    calculado SOLO sobre facturas efectivamente cobradas
    pct_impagadas : proporción de facturas sin fecha de pago registrada
                    (valor entre 0.0 y 1.0)

    Nota sobre avg_dias_pago cuando el cliente nunca ha pagado
    ----------------------------------------------------------
    Si un cliente no tiene ninguna factura cobrada, avg_dias_pago es NaN
    tras el groupby. Lo imputamos con el percentil 95 del resto del dataset:
    el peor pagador conocido. Esto es más conservador que usar un valor
    arbitrario como 365 días.
    """
    # ── Métricas globales (todas las facturas) ────────────────────────────────
    base = df.groupby("cliente").agg(
        n_facturas   = ("total", "count"),
        monto_total  = ("total", "sum"),
        n_impagadas  = ("pagada", lambda x: (x == 0).sum()),
    ).reset_index()

    base["pct_impagadas"] = base["n_impagadas"] / base["n_facturas"]

    # ── Velocidad de pago (solo facturas cobradas) ────────────────────────────
    # Separamos las facturas pagadas antes del groupby para no confundir
    # los días de las pendientes (que tienen dias_pago = NaN)
    pagadas = df[df["pagada"] == 1]
    velocidad = (
        pagadas.groupby("cliente")["dias_pago"]
        .mean()
        .rename("avg_dias_pago")
        .reset_index()
    )

    features = base.merge(velocidad, on="cliente", how="left")

    # ── Imputación de clientes sin historial de cobro ─────────────────────────
    penalizacion = df["dias_pago"].quantile(0.95)
    features["avg_dias_pago"] = features["avg_dias_pago"].fillna(penalizacion)

    return features


# ═════════════════════════════════════════════════════════════════════════════
# PASO 3 — Normalización y cálculo de scores
# ═════════════════════════════════════════════════════════════════════════════

def calcular_scores(features: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte las features crudas en scores de 0 a 100.

    Cómo funciona MinMaxScaler
    --------------------------
    Para cada columna independientemente:
        x_scaled = (x - x_min) / (x_max - x_min)

    El resultado está en [0, 1]. Multiplicamos por 100 para el rango final.

    Dirección de cada score
    -----------------------
    score_pago   : días bajos → buen pagador → score ALTO  → INVERTIMOS (1 - scaled)
    score_valor  : valor alto → cliente importante → score ALTO → dirección natural
    score_riesgo : más impagos o más días de retraso → más riesgo → score ALTO
                   Combinamos dos features con pesos: 60% impagadas + 40% demora
    """
    scaler = MinMaxScaler()
    scores = features[["cliente"]].copy()

    # ── score_pago ────────────────────────────────────────────────────────────
    # Feature: avg_dias_pago
    # Un cliente que paga en 5 días tiene días bajos → scaled cercano a 0
    # Invertimos para que ese cliente tenga score_pago cercano a 100
    dias_scaled = scaler.fit_transform(features[["avg_dias_pago"]])
    scores["score_pago"] = ((1 - dias_scaled) * 100).round(2)

    # ── score_valor ───────────────────────────────────────────────────────────
    # Feature compuesta: log1p(n_facturas) × log1p(monto_total)
    #
    # Por qué logaritmo:
    #   Un cliente con 50 facturas de $10,000 y otro con 5 de $100,000
    #   tienen importancias distintas pero comparables.
    #   Sin log, la diferencia lineal (50 vs 5) dominaría artificialmente.
    #   log1p(x) = log(x + 1) evita log(0) si algún cliente tuviera 0 facturas.
    log_compound = (
        np.log1p(features["n_facturas"]) * np.log1p(features["monto_total"])
    ).values.reshape(-1, 1)

    valor_scaled = scaler.fit_transform(log_compound)
    scores["score_valor"] = (valor_scaled * 100).round(2)

    # ── score_riesgo ──────────────────────────────────────────────────────────
    # Combinamos dos señales de riesgo:
    #   pct_impagadas (60%): proporción de facturas sin cobrar — señal más fuerte,
    #                        indica incumplimiento real, no solo retraso
    #   avg_dias_pago  (40%): lentitud histórica de pago — señal de tendencia
    #
    # Normalizamos cada columna por separado (mismo MinMaxScaler, distintos fit)
    # antes de combinarlas para que ambas estén en la misma escala [0,1].
    impagadas_scaled = scaler.fit_transform(features[["pct_impagadas"]])
    demora_scaled    = scaler.fit_transform(features[["avg_dias_pago"]])

    riesgo_raw = 0.6 * impagadas_scaled[:, 0] + 0.4 * demora_scaled[:, 0]
    scores["score_riesgo"] = (riesgo_raw * 100).round(2)

    return scores


# ═════════════════════════════════════════════════════════════════════════════
# PASO 4 — Persistencia
# ═════════════════════════════════════════════════════════════════════════════

def guardar_resultados(features: pd.DataFrame, scores: pd.DataFrame, engine) -> None:
    """
    Une features y scores, guarda en la DB y exporta un CSV.

    El CSV usa encoding "utf-8-sig" (UTF-8 con BOM) para que Excel en Windows
    lo abra directamente sin problemas con caracteres especiales en español.
    """
    tabla = features.merge(scores, on="cliente").copy()
    tabla["fecha_calculo"] = date.today().isoformat()

    # Orden de columnas orientado a lectura humana
    tabla = tabla[[
        "cliente", "n_facturas", "monto_total",
        "avg_dias_pago", "pct_impagadas",
        "score_pago", "score_valor", "score_riesgo",
        "fecha_calculo",
    ]]

    # ── SQLite ────────────────────────────────────────────────────────────────
    # if_exists="replace" recrea la tabla cada vez que corre el scoring.
    # Esto garantiza que siempre refleja los datos más recientes.
    tabla.to_sql("scores_clientes", engine, if_exists="replace", index=False)
    print(f"  ✓ Tabla 'scores_clientes' guardada en {DB_PATH.name}")

    # ── CSV ───────────────────────────────────────────────────────────────────
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    tabla.to_csv(CSV_OUT, index=False, encoding="utf-8-sig")
    print(f"  ✓ CSV exportado → {CSV_OUT.relative_to(ROOT)}")

    return tabla


# ═════════════════════════════════════════════════════════════════════════════
# PASO 5 — Reporte en consola
# ═════════════════════════════════════════════════════════════════════════════

def imprimir_top10(tabla: pd.DataFrame) -> None:
    """Imprime en consola los 10 clientes con mayor score de valor."""
    top = (
        tabla.sort_values("score_valor", ascending=False)
        .head(10)
        .reset_index(drop=True)
    )
    top.index += 1  # ranking legible: 1, 2, 3...

    sep = "─" * 80
    print(f"\n{sep}")
    print(f"{'TOP 10 CLIENTES POR SCORE DE VALOR':^80}")
    print(sep)
    print(
        f"{'#':>3}  {'CLIENTE':<38}"
        f"{'FACTS':>5}  {'MONTO TOTAL':>13}"
        f"  {'PAGO':>5}  {'VALOR':>5}  {'RIESGO':>6}"
    )
    print(sep)
    for i, row in top.iterrows():
        print(
            f"{i:>3}. {row['cliente']:<38}"
            f"{int(row['n_facturas']):>5}  ${row['monto_total']:>12,.0f}"
            f"  {row['score_pago']:>5.1f}  {row['score_valor']:>5.1f}  {row['score_riesgo']:>6.1f}"
        )
    print(sep)
    print("  Columnas: PAGO=score_pago, VALOR=score_valor, RIESGO=score_riesgo (0–100)\n")


# ═════════════════════════════════════════════════════════════════════════════
# Punto de entrada
# ═════════════════════════════════════════════════════════════════════════════

def run() -> None:
    """Orquesta el pipeline completo de scoring."""
    if not DB_PATH.exists():
        print(f"ERROR: No se encontró la base de datos en:\n  {DB_PATH}")
        print("Ejecuta primero: python -X utf8 scripts/etl.py")
        sys.exit(1)

    engine = create_engine(f"sqlite:///{DB_PATH}")

    print("\n[1/4] Cargando facturas desde la DB...")
    facturas = cargar_facturas(engine)

    print("\n[2/4] Calculando features por cliente...")
    features = calcular_features(facturas)
    print(f"  {len(features)} clientes")
    print(
        f"  Días de pago observados — "
        f"min: {features['avg_dias_pago'].min():.0f}  "
        f"mediana: {features['avg_dias_pago'].median():.0f}  "
        f"max: {features['avg_dias_pago'].max():.0f}"
    )

    print("\n[3/4] Calculando scores (MinMaxScaler)...")
    scores = calcular_scores(features)

    print("\n[4/4] Guardando resultados...")
    tabla = guardar_resultados(features, scores, engine)

    imprimir_top10(tabla)
    print("Scoring completado.")


if __name__ == "__main__":
    run()
