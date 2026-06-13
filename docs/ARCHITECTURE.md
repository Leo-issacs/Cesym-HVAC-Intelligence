# ARCHITECTURE.md

> Documentación **de lo que existe** en el repositorio (ingeniería inversa), no
> de un diseño ideal. Si el código y este documento difieren, gana el código:
> reporta la diferencia.
>
> Generado leyendo `src/`, `scripts/`, `alembic/` y los `.ps1`.

## 1. Qué es

HVAC AI System es un pipeline batch en Python para una empresa de servicio HVAC
(Cesym). Toma archivos Excel crudos (facturas, cartera, instalaciones), los
limpia con una capa ETL, los guarda en una base de datos (SQLite o PostgreSQL),
calcula scores y forecast, y los expone en un dashboard de Streamlit.

No hay API ni servidor de larga duración: cada pieza es un script que se ejecuta
de principio a fin y termina. El "estado" vive en la base de datos y en archivos
`data/processed/`.

## 2. Flujo de datos de extremo a extremo

```
┌─────────────────┐
│ Google Drive    │  Carpeta compartida (DRIVE_FOLDER_ID).
│ (carpeta Excel) │  La persona responsable sube los .xlsx aquí.
└────────┬────────┘
         │  Service Account (credentials/service_account.json), scope readonly
         ▼
┌──────────────────────────────┐
│ scripts/sync_drive.py        │  Descarga por keywords (no por nombre exacto),
│                              │  guarda en data/raw/, luego dispara el pipeline.
└────────┬─────────────────────┘
         ▼
┌──────────────────────────────┐
│ data/raw/*.xlsx              │  Fuente. NUNCA se modifica a mano.
│  reporteMensual_FACTURAS.xlsx│  (los otros dos Excel hoy no los consume nadie)
└────────┬─────────────────────┘
         │  pandas.read_excel + limpieza
         ▼
┌──────────────────────────────┐
│ src/etl/load_facturas.py     │  Limpia, parsea fechas, calcula dias_pago/pagada.
│  run(limpiar=...)            │  Escribe la tabla `facturas` con to_sql REPLACE.
└────────┬─────────────────────┘
         ▼
┌──────────────────────────────┐
│ DB: tabla `facturas`         │  SQLite (data/db/hvac.db) por defecto, o
│  (engine central src/db.py)  │  PostgreSQL schema `analytics` si hay DATABASE_URL.
└────────┬─────────────────────┘
         │  pd.read_sql
         ├──────────────────────────────┬──────────────────────────────┐
         ▼                              ▼                              ▼
┌────────────────────┐   ┌────────────────────────┐   ┌────────────────────────┐
│ models/            │   │ models/forecasting.py  │   │ models/classifier.py   │
│   client_score.py  │   │  Holt-Winters →        │   │  TF-IDF + LogReg →      │
│  3 scores →        │   │  forecast 3 meses →    │   │  categoría por factura →│
│  tabla             │   │  PNG + CSV en          │   │  CSV en                 │
│  `scores_clientes` │   │  data/processed/       │   │  data/processed/        │
│  + CSV             │   │  (NO escribe la DB)    │   │  (NO escribe la DB)     │
└─────────┬──────────┘   └────────────────────────┘   └────────────────────────┘
          │  read_sql facturas + scores_clientes
          ▼
┌──────────────────────────────┐
│ src/dashboard/app.py         │  Streamlit, 3 tabs (Resumen, Scores, Forecast).
│  @st.cache_data              │  Recalcula el forecast en vivo dentro del tab 3.
└──────────────────────────────┘
```

Ruta alternativa (una sola vez, para mudarse a Postgres):

```
SQLite data/db/hvac.db  ──►  scripts/migrate_sqlite_to_postgres.py  ──►  PostgreSQL analytics
                              (copia tabla por tabla, verifica conteos)
```

## 3. Módulos y responsabilidades

### Núcleo de datos

| Archivo | Responsabilidad |
|---|---|
| `src/db.py` | **Punto único** de configuración de la conexión. Lee `DATABASE_URL` del entorno; si no existe, usa SQLite en `data/db/hvac.db`. Para Postgres engancha un listener `connect` que hace `SET search_path TO analytics` en autocommit. Exporta `engine`, `is_postgres`, `SQLITE_DB_PATH`, `DATABASE_URL`. Todo el resto del código importa de aquí. |
| `src/etl/load_facturas.py` | ETL del Excel de facturas → tabla `facturas`. Funciones: `extraer_facturas()` (lee y limpia), `cargar_en_db()` (escribe), `run(limpiar)` (orquesta). |

### Modelos / analítica

| Archivo | Lee | Escribe | Técnica |
|---|---|---|---|
| `src/models/client_score.py` | tabla `facturas` | tabla `scores_clientes` + `data/processed/scores_clientes.csv` | Features por cliente con pandas + `MinMaxScaler`. 3 scores 0–100: pago, valor, riesgo. |
| `src/models/forecasting.py` | tabla `facturas` (solo `fecha_pago` no nula) | `data/processed/forecast_flujo_caja.png` + `forecast_resultados.csv` | Holt-Winters (`statsmodels`). Estacionalidad solo si ≥24 meses. Intervalo P10–P90 por simulación bootstrap. **No toca la DB.** |
| `src/models/classifier.py` | tabla `facturas` + `data/processed/conceptos_clasificados.csv` (labels) | `data/processed/facturas_clasificadas.csv` + `modelo_clasificador.joblib` | NLP: normalización de texto → TF-IDF (1–2 gramas) → Regresión Logística. Clase `otro` por umbral de confianza (0.40), no entrenada. **No toca la DB.** |

> Nota: el dashboard **no consume** las salidas de `forecasting.py` ni de
> `classifier.py`. El tab Forecast recalcula su propia proyección en vivo (un
> promedio ponderado exponencial + tendencia lineal, distinto del Holt-Winters
> de `forecasting.py`). Las categorías del classifier no se muestran en ninguna
> parte de la UI; el tab Scores solo usaría `tipo_cliente` si esa columna
> existiera en `scores_clientes`, cosa que hoy no ocurre.

### Dashboard

| Archivo | Responsabilidad |
|---|---|
| `src/dashboard/app.py` | Streamlit + Plotly. CSS inyectado vía `st.html`. Tabs: **Resumen** (KPIs + barras Top 10 + tabla paginada de pendientes), **Scores** (tabla HTML custom desde `scores_clientes`), **Forecast** (proyección estadística en vivo). |

### Scripts / entrada

| Archivo | Qué hace |
|---|---|
| `scripts/sync_drive.py` | Descarga los Excel de Drive a `data/raw/` (match por keywords) y, si bajó algo, ejecuta `load_facturas.run(limpiar=True)` + `client_score.run()`. Flags `--dry-run`, `--solo-sync`. Loguea a `logs/sync_drive.log`. |
| `scripts/cargar_bd.py` | Entry point del ETL. `--limpiar` → drop + recarga. Sin flag → reemplazo in-place. |
| `scripts/etl.py` | Entry point mínimo: `run(limpiar=False)`. |
| `scripts/migrate_sqlite_to_postgres.py` | Copia `facturas` y `scores_clientes` de SQLite a PostgreSQL/`analytics`, verificando conteos origen vs destino. No modifica el SQLite. |

### Migraciones (Alembic)

| Archivo | Qué hace |
|---|---|
| `alembic.ini` | Config. `sqlalchemy.url` apunta a SQLite como fallback; `env.py` la sobreescribe con `DATABASE_URL`. No usa `set_main_option` para evitar que ConfigParser interprete `%` de contraseñas codificadas. |
| `alembic/env.py` | Crea `SCHEMA analytics` si es Postgres, fija `search_path`, y coloca la tabla `alembic_version` dentro de `analytics`. `target_metadata = None` → migraciones manuales, sin autogenerate. |
| `alembic/versions/001_initial_schema.py` | Crea `facturas` y `scores_clientes`. En Postgres dentro de `analytics`; en SQLite sin schema. |

### Automatización (PowerShell)

| Archivo | Qué hace |
|---|---|
| `setup_google_cloud.ps1` | Vía `gcloud`: crea proyecto GCP, habilita Drive API, crea Service Account, descarga el JSON a `credentials/`, y escribe `.env` con `DRIVE_FOLDER_ID`. Requiere `gcloud auth login` previo. |
| `scripts/sync_maestro.ps1` | Corre `sync_drive.py` para **dos** proyectos (HVAC y "Cesym Chatbot", ruta hardcodeada) con sus respectivos venv. Carga cada `.env` al entorno del proceso. Flag `-DryRun`. |
| `setup_tarea_semanal.ps1` | Registra una tarea programada de Windows ("Cesym-SyncDrive") que corre `sync_maestro.ps1` los lunes 07:00. Requiere admin. |

## 4. Configuración de base de datos

`src/db.py` decide el backend a partir de `DATABASE_URL`:

- **Sin `DATABASE_URL`** → `sqlite:///data/db/hvac.db`. Es el modo por defecto;
  todo funciona sin Postgres.
- **`DATABASE_URL=postgresql+psycopg2://...`** → `is_postgres=True`. Todas las
  tablas viven en el schema `analytics`, fijado con `SET search_path` en cada
  conexión del pool.

Dos trampas reales que `src/db.py` documenta y evita (ambas específicas del
pooler de Supabase / Supavisor):

1. La opción de arranque de libpq (`-csearch_path=analytics`) la **descarta** el
   pooler → el `search_path` queda en `public` y las tablas de `analytics` no se
   ven.
2. `SET search_path` debe correr en **autocommit**. Dentro de una transacción,
   el `ROLLBACK` que el pool emite al devolver la conexión lo revierte → fallo
   intermitente donde solo la primera query de cada conexión ve `analytics`.

`scripts/migrate_sqlite_to_postgres.py` y `alembic/env.py` repiten esta misma
lógica de `search_path` por separado (no importan el listener de `src/db.py`).

## 5. Puntos frágiles conocidos

Estos son comportamientos reales del código, no hipótesis. Documentados para que
nadie se sorprenda.

### 5.1 `to_sql(if_exists="replace")` es destructivo y recrea el schema

Tres lugares reemplazan la tabla completa en cada corrida:

- `src/etl/load_facturas.py:120` — `df.to_sql("facturas", ..., if_exists="replace")`
- `src/models/client_score.py:211` — `tabla.to_sql("scores_clientes", ..., if_exists="replace")`
- `scripts/migrate_sqlite_to_postgres.py:110` — `df.to_sql(table, ..., if_exists="replace")`

Consecuencias:

- **`replace` hace DROP + CREATE.** Cualquier índice, constraint, primary key o
  grant que existiera sobre la tabla **se pierde** en cada carga. El flag
  `--limpiar` solo agrega un `DROP TABLE IF EXISTS` *adicional* antes; sin él, el
  comportamiento sigue siendo destructivo (ver el comentario del propio
  `cargar_en_db`: "Si False, reemplaza igualmente").
- **El schema lo dicta pandas, no Alembic.** `to_sql` infiere los tipos de
  columna desde los dtypes del DataFrame y recrea la tabla. Por lo tanto la
  tabla que vive en producción **no** es la que definió la migración 001; es la
  que pandas decidió. Ver `docs/DATA_FLOW.md` §"Tipos reales".
- En Postgres, `to_sql` respeta el `search_path`, así que escribe dentro de
  `analytics` — pero recrea la tabla ahí, pisando la versión creada por Alembic.

### 5.2 El schema de Alembic no tiene PK ni constraints, y el ETL lo pisa

`alembic/versions/001_initial_schema.py` crea ambas tablas con **todas las
columnas `nullable=True` y sin PRIMARY KEY ni UNIQUE**:

- `facturas`: ni PK en `folio`, ni `NOT NULL` en nada.
- `scores_clientes`: `cliente` **no** es primary key, pese a que `CLAUDE.md` lo
  describe como "Primary key". Es solo `Text NULL`.

Y como el ETL escribe con `if_exists="replace"` (§5.1), incluso esa definición
mínima sin constraints **se descarta** en la primera carga de datos. En la
práctica Alembic sirve para crear el schema `analytics` y la tabla
`alembic_version`, pero la forma final de `facturas`/`scores_clientes` la define
pandas. No confíes en las restricciones de la migración: en runtime no existen.

### 5.3 `st.cache_data` sin `ttl` en el dashboard

`src/dashboard/app.py:163` y `:170`:

```python
@st.cache_data
def load_facturas() -> pd.DataFrame: ...
@st.cache_data
def load_scores() -> pd.DataFrame: ...
```

Sin `ttl`, el caché de Streamlit es **indefinido**: persiste mientras viva el
proceso del servidor. Después de un `sync_drive.py` (que recarga `facturas` y
`scores_clientes`), el dashboard **sigue mostrando los datos viejos** hasta que
se reinicie la app o se limpie el caché manualmente. Como el sync programado
corre los lunes 07:00 pero el dashboard puede llevar días levantado, esto puede
hacer que la UI quede silenciosamente desactualizada.

### 5.4 Otros puntos a tener presentes

- **Matching de Drive por keywords**, no por nombre exacto
  (`sync_drive.py:62-66`). Si alguien sube un Excel cuyo nombre contiene
  "facturas" por casualidad, puede sobrescribir el archivo objetivo en
  `data/raw/`.
- **`DATABASE_MIGRATION_URL` declarada pero no usada.** `.env.example` define
  `DATABASE_MIGRATION_URL` (conexión directa, puerto 5432) "para la migración",
  pero `scripts/migrate_sqlite_to_postgres.py` lee `DATABASE_URL`
  (`migrate_sqlite_to_postgres.py:34`), que en `.env.example` es el **pooler**
  (6543). El nombre de la variable y su uso real no coinciden.
- **Sin pruebas que cubran el ETL ni los scores.** Existe el directorio `tests/`
  pero no hay suite asociada a estos módulos.
</content>
</invoke>
