"""
Módulo de forecast de flujo de caja mensual.

Algoritmo: Holt-Winters Exponential Smoothing (statsmodels).
  - Captura tendencia + estacionalidad multiplicativa igual que Prophet,
    pero no requiere cmdstan ni rutas largas de Windows.
  - Para migrar a Prophet en el futuro, ver la sección "Migración a Prophet"
    al final de este archivo.

Pipeline completo:
  1. Lee la tabla 'facturas' de hvac.db
  2. Agrupa ingresos por mes (solo facturas con fecha_pago registrada)
  3. Rellena meses faltantes con cero (meses sin cobros)
  4. Ajusta el modelo de serie de tiempo
  5. Proyecta 3 meses hacia adelante con intervalo de confianza
  6. Guarda gráfica en data/processed/forecast_flujo_caja.png
  7. Guarda predicciones en data/processed/forecast_resultados.csv
  8. Imprime resumen en consola

Uso:
    python -X utf8 src/models/forecasting.py
"""

import pathlib
import sqlite3
import warnings

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

# Silencia advertencias de convergencia que no afectan el resultado
warnings.filterwarnings("ignore")

# ── Rutas ────────────────────────────────────────────────────────────────────
# pathlib.Path(__file__) → ruta de este archivo
# .resolve() → ruta absoluta sin '..'
# .parent.parent.parent → sube tres niveles hasta la raíz del proyecto
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "db" / "hvac.db"
PROCESSED = ROOT / "data" / "processed"
CHART_PATH = PROCESSED / "forecast_flujo_caja.png"
CSV_PATH = PROCESSED / "forecast_resultados.csv"

# Número de meses a proyectar
MESES_FORECAST = 3


# ── 1. Carga de datos ─────────────────────────────────────────────────────────

def cargar_ingresos_mensuales() -> pd.Series:
    """
    Conecta a hvac.db, consulta la tabla 'facturas' y agrupa el
    ingreso total por mes de pago (fecha_pago no nula).

    Por qué usamos fecha_pago y no fecha:
      La fecha de la factura es cuando se emite. La fecha_pago es cuando
      el dinero entra. Para flujo de caja, nos interesa el cobro real.

    Devuelve una pd.Series con índice PeriodIndex mensual (M) y valores
    de suma de 'total'.
    """
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"No se encontró la base de datos en:\n  {DB_PATH}\n"
            "Ejecuta primero: python -X utf8 scripts/cargar_bd.py --limpiar"
        )

    con = sqlite3.connect(DB_PATH)
    try:
        # SQL: seleccionamos solo facturas cobradas (fecha_pago IS NOT NULL)
        query = """
            SELECT fecha_pago, total
            FROM   facturas
            WHERE  fecha_pago IS NOT NULL
              AND  total      IS NOT NULL
        """
        df = pd.read_sql_query(query, con, parse_dates=["fecha_pago"])
    finally:
        con.close()

    # Crear columna de período mensual (e.g. '2025-11') para agrupar
    df["mes"] = df["fecha_pago"].dt.to_period("M")

    # Sumar ingresos por mes
    ingresos = df.groupby("mes")["total"].sum()

    # Completar meses faltantes con 0 para que la serie sea continua.
    # Una serie con huecos confunde al modelo porque asume pasos regulares.
    idx_completo = pd.period_range(ingresos.index.min(), ingresos.index.max(), freq="M")
    ingresos = ingresos.reindex(idx_completo, fill_value=0)

    return ingresos


# ── 2. Entrenamiento del modelo ───────────────────────────────────────────────

def entrenar_modelo(serie: pd.Series) -> ExponentialSmoothing:
    """
    Ajusta un modelo Holt-Winters con:
      - trend='add'       → captura tendencia lineal (subida/bajada sostenida)
      - seasonal='add'    → captura estacionalidad aditiva
      - seasonal_periods  → 12 meses = 1 ciclo anual
      - damped_trend=True → la tendencia se "amortigua" hacia el futuro
                            en lugar de crecer indefinidamente; esto da
                            proyecciones más conservadoras y realistas.

    Por qué Holt-Winters y no ARIMA:
      Holt-Winters es más intuitivo: modela directamente nivel, tendencia
      y estacionalidad. ARIMA requiere decidir órdenes (p,d,q) y es menos
      transparente para explicar el negocio.

    Por qué no 'multiplicative' seasonal:
      Con meses en cero (sin cobros), la estacionalidad multiplicativa
      genera infinitos/NaN porque intenta dividir por cero.
    """
    n = len(serie)
    # Con pocos datos (<2 ciclos completos) desactivamos la estacionalidad
    # para evitar overfitting: el modelo no puede aprender un patrón anual
    # con menos de 24 puntos.
    usar_estacional = n >= 24

    modelo = ExponentialSmoothing(
        serie.values.astype(float),
        trend="add",
        seasonal="add" if usar_estacional else None,
        seasonal_periods=12 if usar_estacional else None,
        damped_trend=True,
    )
    return modelo.fit(optimized=True)


# ── 3. Forecast y cálculo de intervalo de confianza ──────────────────────────

def calcular_forecast(
    serie: pd.Series, resultado_modelo
) -> pd.DataFrame:
    """
    Genera la proyección y construye un intervalo de confianza empírico.

    Statsmodels Holt-Winters no produce intervalos de confianza analíticos,
    así que los estimamos con simulación bootstrap:
      - Generamos N=1000 trayectorias simuladas del modelo (cada una con
        ruido basado en los residuos históricos).
      - El percentil 10 es el límite inferior (pesimista).
      - El percentil 90 es el límite superior (optimista).
    Esto es metodológicamente equivalente a lo que Prophet llama
    'uncertainty_samples'.
    """
    pred_media = resultado_modelo.forecast(MESES_FORECAST)

    # Simulación para intervalos de confianza
    import numpy as np

    sim = resultado_modelo.simulate(
        nsimulations=MESES_FORECAST,
        repetitions=1000,
        error="add",
    )
    # sim tiene shape (MESES_FORECAST, 1000) como ndarray
    sim = np.asarray(sim)
    lower = np.percentile(sim, 10, axis=1)
    upper = np.percentile(sim, 90, axis=1)

    # Calcular el período inicial del forecast (el mes siguiente al último dato)
    ultimo_mes = serie.index[-1]
    meses_futuros = pd.period_range(
        start=ultimo_mes + 1, periods=MESES_FORECAST, freq="M"
    )

    df_forecast = pd.DataFrame(
        {
            "mes": meses_futuros.astype(str),
            "ingreso_esperado": pred_media,
            "intervalo_inferior_10pct": lower,
            "intervalo_superior_90pct": upper,
        }
    )

    # Los ingresos no pueden ser negativos; forzamos a 0 mínimo
    for col in ["ingreso_esperado", "intervalo_inferior_10pct", "intervalo_superior_90pct"]:
        df_forecast[col] = df_forecast[col].clip(lower=0).round(2)

    return df_forecast


# ── 4. Gráfica ────────────────────────────────────────────────────────────────

def graficar(serie: pd.Series, df_forecast: pd.DataFrame) -> None:
    """
    Genera una gráfica de dos partes:
      - Línea histórica (datos reales) en azul
      - Línea de forecast en naranja con banda de confianza sombreada

    La banda de confianza representa el rango entre el escenario pesimista
    (10° percentil) y el optimista (90° percentil).
    """
    fig, ax = plt.subplots(figsize=(12, 5))

    # Datos históricos
    fechas_hist = [str(p) for p in serie.index]
    ax.plot(
        fechas_hist,
        serie.values / 1_000,  # Convertir a miles para legibilidad
        marker="o",
        color="#2563EB",
        linewidth=2,
        markersize=4,
        label="Histórico",
    )

    # Forecast: línea central + banda de confianza
    fechas_fc = df_forecast["mes"].tolist()
    ax.plot(
        fechas_fc,
        df_forecast["ingreso_esperado"] / 1_000,
        marker="s",
        color="#F97316",
        linewidth=2,
        markersize=6,
        linestyle="--",
        label="Forecast (media)",
    )
    ax.fill_between(
        fechas_fc,
        df_forecast["intervalo_inferior_10pct"] / 1_000,
        df_forecast["intervalo_superior_90pct"] / 1_000,
        alpha=0.25,
        color="#F97316",
        label="Intervalo confianza 80%",
    )

    # Línea vertical que separa histórico de forecast
    ax.axvline(x=len(serie) - 1, color="gray", linestyle=":", linewidth=1.2)

    ax.set_title("Forecast de Flujo de Caja — Ingresos Mensuales", fontsize=14, pad=12)
    ax.set_xlabel("Mes")
    ax.set_ylabel("Ingresos (miles de pesos MXN)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}k"))

    # Rotar etiquetas del eje X para evitar solapamiento
    plt.xticks(
        ticks=list(range(len(fechas_hist) + len(fechas_fc))),
        labels=fechas_hist + fechas_fc,
        rotation=45,
        ha="right",
        fontsize=8,
    )
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.4)

    plt.tight_layout()
    PROCESSED.mkdir(parents=True, exist_ok=True)
    fig.savefig(CHART_PATH, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nGráfica guardada en: {CHART_PATH}")


# ── 5. Exportar resultados ────────────────────────────────────────────────────

def guardar_csv(df_forecast: pd.DataFrame) -> None:
    """Guarda el DataFrame de predicciones como CSV."""
    PROCESSED.mkdir(parents=True, exist_ok=True)
    df_forecast.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
    # utf-8-sig: variante de UTF-8 con BOM que Excel abre correctamente
    print(f"Predicciones guardadas en: {CSV_PATH}")


# ── 6. Resumen en consola ─────────────────────────────────────────────────────

def imprimir_resumen(df_forecast: pd.DataFrame) -> None:
    """Imprime una tabla legible con el forecast de los próximos meses."""
    sep = "─" * 65
    print(f"\n{sep}")
    print(f"  {'FORECAST DE FLUJO DE CAJA':^61}")
    print(sep)
    print(f"  {'Mes':<12} {'Esperado':>15} {'Mínimo (P10)':>15} {'Máximo (P90)':>15}")
    print(sep)
    for _, row in df_forecast.iterrows():
        print(
            f"  {row['mes']:<12}"
            f"  ${row['ingreso_esperado']:>13,.0f}"
            f"  ${row['intervalo_inferior_10pct']:>13,.0f}"
            f"  ${row['intervalo_superior_90pct']:>13,.0f}"
        )
    print(sep)
    total = df_forecast["ingreso_esperado"].sum()
    print(f"  {'TOTAL 3 MESES':<12}  ${total:>13,.0f}")
    print(sep)


# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> pd.DataFrame:
    """
    Ejecuta el pipeline completo y devuelve el DataFrame de forecast.
    Puede importarse desde otros módulos sin efectos secundarios de I/O
    si se llama a las funciones individuales.
    """
    print("1/5  Cargando ingresos mensuales desde la base de datos...")
    serie = cargar_ingresos_mensuales()
    print(f"     Serie: {len(serie)} meses ({serie.index[0]} → {serie.index[-1]})")

    print("2/5  Entrenando modelo Holt-Winters...")
    resultado = entrenar_modelo(serie)
    # AIC (Akaike Information Criterion): mide calidad del ajuste penalizando
    # la complejidad. Más bajo = mejor. Útil para comparar modelos.
    print(f"     AIC del modelo: {resultado.aic:.1f}")

    print(f"3/5  Proyectando {MESES_FORECAST} meses...")
    df_forecast = calcular_forecast(serie, resultado)

    print("4/5  Generando gráfica...")
    graficar(serie, df_forecast)

    print("5/5  Guardando CSV...")
    guardar_csv(df_forecast)

    imprimir_resumen(df_forecast)
    return df_forecast


if __name__ == "__main__":
    run()


# ─────────────────────────────────────────────────────────────────────────────
# MIGRACIÓN A PROPHET (cuando se habiliten rutas largas en Windows)
# ─────────────────────────────────────────────────────────────────────────────
#
# Prophet espera un DataFrame con dos columnas: 'ds' (fecha) y 'y' (valor).
# Para reemplazar entrenar_modelo + calcular_forecast con Prophet:
#
#   from prophet import Prophet
#
#   def entrenar_y_proyectar_prophet(serie: pd.Series) -> pd.DataFrame:
#       # Convertir la serie a formato Prophet
#       df_prophet = pd.DataFrame({
#           "ds": serie.index.to_timestamp(),  # Period → Timestamp
#           "y":  serie.values.astype(float),
#       })
#       modelo = Prophet(
#           yearly_seasonality=True,
#           weekly_seasonality=False,
#           daily_seasonality=False,
#           interval_width=0.80,         # equivale a P10–P90
#       )
#       modelo.fit(df_prophet)
#       futuro = modelo.make_future_dataframe(periods=MESES_FORECAST, freq="MS")
#       prediccion = modelo.predict(futuro)
#       # Columnas relevantes: ds, yhat, yhat_lower, yhat_upper
#       return prediccion.tail(MESES_FORECAST)[["ds", "yhat", "yhat_lower", "yhat_upper"]]
#
# Para habilitar rutas largas en Windows (requiere admin una sola vez):
#   1. Abre regedit como administrador
#   2. Navega a: HKLM\SYSTEM\CurrentControlSet\Control\FileSystem
#   3. Cambia LongPathsEnabled de 0 a 1
#   4. Reinicia PowerShell y ejecuta: pip install prophet matplotlib
# ─────────────────────────────────────────────────────────────────────────────
