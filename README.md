# Cesym HVAC Intelligence

Sistema de inteligencia de datos para una empresa de servicios de climatizaciÃ³n (HVAC). Transforma datos operativos crudos en Excel en un pipeline completo de analÃ­tica e IA: desde la ingestiÃ³n y limpieza hasta modelos predictivos y un dashboard interactivo.

---

## Â¿QuÃ© hace este proyecto?

| MÃ³dulo | DescripciÃ³n |
|--------|-------------|
| **ETL Pipeline** | Extrae facturas, cartera y registros de instalaciÃ³n desde Excel, los limpia y los carga en SQLite |
| **Clasificador NLP** | Categoriza automÃ¡ticamente los conceptos de servicio en 4 tipos usando TF-IDF + RegresiÃ³n LogÃ­stica (83.7% precisiÃ³n) |
| **Forecast de Flujo de Caja** | Proyecta ingresos a 3 meses con Holt-Winters Exponential Smoothing e intervalos de confianza |
| **Scoring de Clientes** | Calcula tres scores por cliente (pago, valor, riesgo) para priorizar cobranza y ventas |
| **Dashboard Interactivo** | VisualizaciÃ³n en Streamlit con resumen operativo, tabla de scores y grÃ¡fica de forecast |
| **EDA Notebook** | AnÃ¡lisis exploratorio completo con 8 grÃ¡ficas sobre los datasets fuente |

---

## Arquitectura

```
data/raw/              â† Archivos Excel fuente (no incluidos en el repo)
    â”‚
    â–¼
scripts/cargar_bd.py   â† ETL: limpia y carga en SQLite
    â”‚
    â–¼
data/db/hvac.db        â† Base de datos SQLite
    â”‚
    â”œâ”€â”€â–¶ src/models/classifier.py    â† NLP: clasifica conceptos de servicio
    â”œâ”€â”€â–¶ src/models/forecasting.py   â† Series de tiempo: forecast de caja
    â”œâ”€â”€â–¶ src/models/client_score.py  â† Scoring de clientes
    â”‚
    â–¼
src/dashboard/app.py   â† Dashboard Streamlit
```

---

## Stack tecnolÃ³gico

- **Lenguaje:** Python 3.11
- **Datos:** pandas, SQLAlchemy, openpyxl, SQLite
- **ML / NLP:** scikit-learn (TF-IDF + Logistic Regression)
- **Series de tiempo:** statsmodels (Holt-Winters)
- **VisualizaciÃ³n:** Streamlit, Plotly, matplotlib, seaborn
- **AnÃ¡lisis:** Jupyter Notebook

---

## CÃ³mo ejecutar

### 1. Instalar dependencias

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Cargar la base de datos

Coloca los archivos Excel en `data/raw/` y ejecuta:

```powershell
python -X utf8 scripts/cargar_bd.py --limpiar
```

### 3. Entrenar modelos

```powershell
# Clasificador NLP
python -X utf8 src/models/classifier.py

# Scoring de clientes
python -X utf8 src/models/client_score.py

# Forecast de flujo de caja
python -X utf8 src/models/forecasting.py
```

### 4. Lanzar el dashboard

```powershell
streamlit run src/dashboard/app.py
```

---

## Estructura del proyecto

```
â”œâ”€â”€ data/
â”‚   â”œâ”€â”€ raw/                        # Excel fuente (excluidos del repo)
â”‚   â”œâ”€â”€ processed/
â”‚   â”‚   â””â”€â”€ conceptos_clasificados.csv   # Etiquetas NLP curadas manualmente
â”‚   â””â”€â”€ db/                         # SQLite (excluido del repo)
â”‚
â”œâ”€â”€ src/
â”‚   â”œâ”€â”€ etl/
â”‚   â”‚   â””â”€â”€ load_facturas.py        # ExtracciÃ³n y limpieza de facturas
â”‚   â”œâ”€â”€ models/
â”‚   â”‚   â”œâ”€â”€ classifier.py           # Clasificador NLP de conceptos
â”‚   â”‚   â”œâ”€â”€ forecasting.py          # Forecast Holt-Winters
â”‚   â”‚   â””â”€â”€ client_score.py         # Scoring de clientes
â”‚   â””â”€â”€ dashboard/
â”‚       â””â”€â”€ app.py                  # Dashboard Streamlit
â”‚
â”œâ”€â”€ scripts/
â”‚   â””â”€â”€ cargar_bd.py                # Entry point del ETL
â”‚
â”œâ”€â”€ notebooks/
â”‚   â”œâ”€â”€ 01_exploracion_datos.ipynb  # EDA completo (8 grÃ¡ficas)
â”‚   â””â”€â”€ _build_eda.py               # Generador del notebook
â”‚
â”œâ”€â”€ requirements.txt
â””â”€â”€ CLAUDE.md                       # GuÃ­a para Claude Code
```

---

## CategorÃ­as de servicio (NLP)

El clasificador distingue cuatro tipos de trabajo:

| CategorÃ­a | DescripciÃ³n | Ejemplo |
|-----------|-------------|---------|
| `mantenimiento_preventivo` | Servicio programado de limpieza/revisiÃ³n | *Mantenimiento preventivo trimestral a chiller York* |
| `mantenimiento_correctivo` | ReparaciÃ³n por falla o averÃ­a | *ReparaciÃ³n de compresor en equipo split 5 ton* |
| `instalacion_nueva` | InstalaciÃ³n de equipo nuevo | *InstalaciÃ³n de sistema VRF en edificio corporativo* |
| `venta_refaccion` | Venta de pieza o refacciÃ³n | *Compresor Danfoss scrolla para chiller Carrier* |

---

## Datos

Los archivos Excel fuente contienen informaciÃ³n confidencial de clientes y estÃ¡n excluidos del repositorio. Para reproducir el proyecto necesitas:

- `reporteMensual_FACTURAS.xlsx` â€” Facturas con fecha, cliente, concepto y monto
- `CARTERA AL 11032026.xlsx` â€” Cuentas por cobrar y cotizaciones pendientes
- `CONTROL DE INST. MINISPLIT 2026.xlsx` â€” Registro de instalaciones

El Ãºnico archivo de datos incluido en el repo es `data/processed/conceptos_clasificados.csv`, que contiene las 73 etiquetas curadas manualmente para entrenar el clasificador NLP.

---

*Proyecto en desarrollo activo. PrÃ³ximas fases: agentes de cobranza automatizados, integraciÃ³n de API REST y expansiÃ³n del dashboard.*