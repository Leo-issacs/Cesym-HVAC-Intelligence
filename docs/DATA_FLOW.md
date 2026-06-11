# DATA_FLOW.md

> Tablas, columnas y **tipos reales** (los que pandas `to_sql` crea en runtime,
> no los que declara Alembic), más quién lee y quién escribe cada tabla.
> Documentación de lo que existe.

## 1. Mapa de lectura/escritura

| Tabla / archivo | Escribe | Lee |
|---|---|---|
| `facturas` (DB) | `src/etl/load_facturas.py` (`to_sql replace`) | `src/models/client_score.py`, `src/models/forecasting.py`, `src/models/classifier.py`, `src/dashboard/app.py` |
| `scores_clientes` (DB) | `src/models/client_score.py` (`to_sql replace`) | `src/dashboard/app.py` |
| `data/processed/scores_clientes.csv` | `client_score.py` | (consumo externo / Excel) |
| `data/processed/facturas_clasificadas.csv` | `classifier.py` | (consumo externo; el dashboard NO lo lee) |
| `data/processed/modelo_clasificador.joblib` | `classifier.py` | `classifier.py` (recarga el modelo) |
| `data/processed/forecast_resultados.csv` | `forecasting.py` | (consumo externo; el dashboard NO lo lee) |
| `data/processed/forecast_flujo_caja.png` | `forecasting.py` | (imagen estática) |
| `data/processed/conceptos_clasificados.csv` | (curado a mano) | `classifier.py` (labels de entrenamiento) |
| `alembic_version` (DB) | Alembic | Alembic |

En Postgres todas las tablas viven en el schema `analytics`. En SQLite no hay
schema (`data/db/hvac.db`).

## 2. Origen: `data/raw/reporteMensual_FACTURAS.xlsx`

Columnas del Excel que el ETL consume (tras `df.columns.str.strip()`, porque los
encabezados traen espacios extra como `' Total '`):

| Columna Excel | Uso en el ETL |
|---|---|
| `Folio` | → `folio` |
| `Cliente` | → `cliente` (`.strip().str.upper()`); filas con `Cliente` NaN se descartan |
| `Fecha` | → `fecha_factura` (parseo `dayfirst=True, errors="coerce"`) |
| `FECHA DE PAGO` | → `fecha_pago` (mismo parseo) |
| `Concepto` | → `concepto` |
| `Total` | → `total` |

Los otros dos Excel (`CARTERA AL 11032026.xlsx`, `CONTROL DE INST. MINISPLIT
2026.xlsx`) se descargan de Drive pero **ningún módulo los lee** hoy.

## 3. Tabla `facturas`

Producida por `load_facturas.py` con `df.to_sql(..., if_exists="replace")`. El
schema lo infiere pandas desde los dtypes del DataFrame, **no** la migración de
Alembic.

| Columna | Tipo real (pandas/runtime) | Tipo declarado en Alembic 001 | Notas |
|---|---|---|---|
| `folio` | INTEGER/BIGINT | `Integer` | Coincide (salvo que el Excel tenga folios vacíos, que volverían float). |
| `cliente` | TEXT | `Text` | Normalizado strip+upper. |
| `fecha_factura` | **DATETIME / TIMESTAMP** | `Text` | **Difiere.** Es `datetime64[ns]` en el DataFrame → pandas crea columna de fecha, no texto. |
| `concepto` | TEXT | `Text` | |
| `total` | FLOAT | `Float` | MXN. |
| `fecha_pago` | **DATETIME / TIMESTAMP** | `Text` | **Difiere** (igual que `fecha_factura`). NaT si la factura no se pagó. |
| `dias_pago` | **FLOAT** | `Integer` | **Difiere.** Las facturas impagadas dan `NaT.dt.days` = NaN, así que la columna entera es `float64` → FLOAT, no INTEGER. `clip(lower=0)`. |
| `pagada` | INTEGER/BIGINT | `Integer` | 1 = pagada, 0 = pendiente. |

> **Por qué importa:** quien consulte la tabla esperando los tipos de la
> migración (fechas como `Text`, `dias_pago` como `Integer`) se equivoca. En
> runtime las fechas son timestamps y `dias_pago` es float con NaN. Esto es
> consecuencia directa de `to_sql(if_exists="replace")` recreando la tabla —
> ver `docs/ARCHITECTURE.md` §5.1–5.2.

Filtros aplicados durante la limpieza (`extraer_facturas`):

- Se eliminan filas con `Cliente` NaN (canceladas / separadores).
- Se eliminan filas donde `fecha_factura` no pudo parsearse (queda NaT).
- `dias_pago = (fecha_pago - fecha_factura).dt.days`, recortado a mínimo 0
  (pagos anticipados o errores de captura darían negativo).

## 4. Tabla `scores_clientes`

Producida por `client_score.py` con `to_sql(if_exists="replace")`. Una fila por
cliente.

| Columna | Tipo real (pandas/runtime) | Alembic 001 | Significado |
|---|---|---|---|
| `cliente` | TEXT | `Text` (sin PK) | Identificador. **No es PRIMARY KEY** pese a lo que dice `CLAUDE.md`. |
| `n_facturas` | INTEGER/BIGINT | `Integer` | Total de facturas emitidas. |
| `monto_total` | FLOAT | `Float` | Suma histórica facturada. |
| `avg_dias_pago` | FLOAT | `Float` | Promedio de días a pago **solo de facturas cobradas**. Si el cliente nunca pagó, se imputa con el percentil 95 global (`df["dias_pago"].quantile(0.95)`). |
| `pct_impagadas` | FLOAT | `Float` | Fracción de facturas sin fecha de pago (0.0–1.0). |
| `score_pago` | FLOAT | `Float` | 0–100. `(1 - minmax(avg_dias_pago)) * 100`. Alto = paga rápido. |
| `score_valor` | FLOAT | `Float` | 0–100. `minmax(log1p(n_facturas) * log1p(monto_total)) * 100`. |
| `score_riesgo` | FLOAT | `Float` | 0–100. `(0.6 * minmax(pct_impagadas) + 0.4 * minmax(avg_dias_pago)) * 100`. |
| `fecha_calculo` | TEXT | `Text` | `date.today().isoformat()` (string ISO). |

Cómo se calculan los scores (`MinMaxScaler` de scikit-learn, fit por columna):

- **score_pago** — invierte `avg_dias_pago` normalizado: días bajos → score alto.
- **score_valor** — feature compuesta logarítmica de volumen × monto, normalizada.
- **score_riesgo** — 60% impagadas + 40% lentitud de pago, ambas normalizadas.

> Los scores son **relativos al lote**: MinMax usa el min/max del conjunto actual
> de clientes. Si cambia la cartera, los scores de todos se recalibran. No son
> comparables entre corridas distintas.

## 5. Salidas que NO van a la base de datos

### `forecasting.py` → `data/processed/`

- `forecast_resultados.csv` — columnas `mes` (str `YYYY-MM`), `ingreso_esperado`,
  `intervalo_inferior_10pct`, `intervalo_superior_90pct` (floats, clip ≥0,
  redondeo 2). 3 filas (3 meses).
- `forecast_flujo_caja.png` — gráfica histórico + forecast con banda P10–P90.

Serie de entrada: suma de `total` por mes de `fecha_pago` (solo `fecha_pago` no
nula), con meses faltantes rellenados a 0. Holt-Winters aditivo, estacionalidad
de 12 meses solo si hay ≥24 puntos.

### `classifier.py` → `data/processed/`

- `facturas_clasificadas.csv` — `folio, cliente, fecha_factura, concepto, total,
  pagada, categoria_predicha, confianza`. Una fila por factura.
- `modelo_clasificador.joblib` — pipeline TF-IDF + LogisticRegression serializado.

Categorías de salida: `mantenimiento_preventivo`, `mantenimiento_correctivo`,
`instalacion_nueva`, `venta_refaccion`, y `otro` (asignada por umbral de
confianza `< 0.40`, no es una clase entrenada). `confianza` es un float 0–1.

## 6. Diferencia entre el forecast del dashboard y el de `forecasting.py`

Son **dos cálculos distintos** sobre la misma serie de cobros mensuales:

| | `src/models/forecasting.py` | `src/dashboard/app.py` (tab 3) |
|---|---|---|
| Modelo | Holt-Winters (statsmodels) | Promedio ponderado exponencial de los últimos ≤6 meses + tendencia lineal (`np.polyfit`) |
| Intervalo | P10–P90 por simulación bootstrap (1000 trayectorias) | ±1.5σ del histórico reciente |
| Horizonte | 3 meses | 3 meses |
| Persistencia | CSV + PNG en disco | en memoria, recalculado en cada render |

El dashboard **no** lee el CSV de `forecasting.py`; reimplementa su propia
proyección en vivo. Si se busca "el forecast oficial", hay que decidir cuál.
</content>
