# Cesym HVAC Intelligence

[![tests](https://github.com/Leo-issacs/Cesym-HVAC-Intelligence/actions/workflows/tests.yml/badge.svg)](https://github.com/Leo-issacs/Cesym-HVAC-Intelligence/actions/workflows/tests.yml)

Sistema de inteligencia de datos para una empresa de servicios de climatización (HVAC). Transforma datos operativos crudos en Excel en un pipeline completo de analítica e IA: desde la ingestión y limpieza hasta modelos predictivos y un dashboard interactivo.

---

## ¿Qué hace este proyecto?

| Módulo | Descripción |
|--------|-------------|
| **ETL Pipeline** | Extrae facturas, cartera y registros de instalación desde Excel, los limpia y los carga en SQLite |
| **Clasificador NLP** | Categoriza automáticamente los conceptos de servicio en 4 tipos usando TF-IDF + Regresión Logística (83.7% precisión) |
| **Forecast de Flujo de Caja** | Proyecta ingresos a 3 meses con Holt-Winters Exponential Smoothing e intervalos de confianza |
| **Scoring de Clientes** | Calcula tres scores por cliente (pago, valor, riesgo) para priorizar cobranza y ventas |
| **Dashboard Interactivo** | Visualización en Streamlit con resumen operativo, tabla de scores y gráfica de forecast |
| **EDA Notebook** | Análisis exploratorio completo con 8 gráficas sobre los datasets fuente |
| **Sync Drive** | Descarga automática de Excels desde Google Drive (lunes 7am vía tarea de Windows) |

---

## Arquitectura

```
data/raw/              ← Archivos Excel fuente (no incluidos en el repo)
    │
    ▼
scripts/cargar_bd.py   ← ETL: limpia y carga en SQLite
    │
    ▼
data/db/hvac.db        ← Base de datos SQLite
    │
    ├──▶ src/models/classifier.py    ← NLP: clasifica conceptos de servicio
    ├──▶ src/models/forecasting.py   ← Series de tiempo: forecast de caja
    ├──▶ src/models/client_score.py  ← Scoring de clientes
    │
    ▼
src/dashboard/app.py   ← Dashboard Streamlit
```

---

## Stack tecnológico

- **Lenguaje:** Python 3.11
- **Datos:** pandas, SQLAlchemy, openpyxl, SQLite
- **ML / NLP:** scikit-learn (TF-IDF + Logistic Regression)
- **Series de tiempo:** statsmodels (Holt-Winters)
- **Visualización:** Streamlit, Plotly, matplotlib, seaborn
- **Análisis:** Jupyter Notebook
- **Integración:** Google Drive API (Service Account)

---

## Cómo ejecutar

### 1. Instalar dependencias

```powershell
python -m venv cesym_data_analytics
cesym_data_analytics\Scripts\activate
pip install -r requirements.txt
```

### 2. Sincronizar archivos desde Drive

```powershell
python -X utf8 scripts/sync_drive.py             # descarga los Excel
python -X utf8 scripts/sync_drive.py --dry-run   # muestra qué descargaría sin tocar nada
```

### 3. Cargar la base de datos

```powershell
python -X utf8 scripts/cargar_bd.py --limpiar
```

### 4. Entrenar modelos

```powershell
python -X utf8 src/models/classifier.py
python -X utf8 src/models/client_score.py
python -X utf8 src/models/forecasting.py
```

### 5. Lanzar el dashboard

```powershell
streamlit run src/dashboard/app.py
```

---

## Estructura del proyecto

```
├── data/
│   ├── raw/                             # Excel fuente (excluidos del repo)
│   ├── processed/
│   │   └── conceptos_clasificados.csv   # Etiquetas NLP curadas manualmente
│   └── db/                              # SQLite (excluido del repo)
│
├── src/
│   ├── etl/
│   │   └── load_facturas.py        # Extracción y limpieza de facturas
│   ├── models/
│   │   ├── classifier.py           # Clasificador NLP de conceptos
│   │   ├── forecasting.py          # Forecast Holt-Winters
│   │   └── client_score.py         # Scoring de clientes
│   └── dashboard/
│       └── app.py                  # Dashboard Streamlit
│
├── scripts/
│   ├── sync_drive.py               # Descarga Excels desde Google Drive
│   ├── sync_maestro.ps1            # Sincroniza HVAC + Chatbot en una tarea
│   └── cargar_bd.py                # Entry point del ETL
│
├── credentials/
│   └── service_account.json        # Credenciales Google Drive (excluidas del repo)
│
├── notebooks/
│   ├── 01_exploracion_datos.ipynb  # EDA completo (8 gráficas)
│   └── _build_eda.py               # Generador del notebook
│
├── setup_tarea_semanal.ps1         # Registra la tarea automática de Windows
├── requirements.txt
└── CLAUDE.md
```

---

## Automatización

La tarea de Windows `Cesym-SyncDrive` corre cada **lunes a las 7am** y ejecuta `sync_maestro.ps1`, que sincroniza este proyecto y el Cesym Chatbot desde la misma carpeta de Drive compartida.

Para registrar o actualizar la tarea (ejecutar como administrador):

```powershell
.\setup_tarea_semanal.ps1
```

---

## Categorías de servicio (NLP)

El clasificador distingue cuatro tipos de trabajo:

| Categoría | Descripción | Ejemplo |
|-----------|-------------|---------|
| `mantenimiento_preventivo` | Servicio programado de limpieza/revisión | *Mantenimiento preventivo trimestral a chiller York* |
| `mantenimiento_correctivo` | Reparación por falla o avería | *Reparación de compresor en equipo split 5 ton* |
| `instalacion_nueva` | Instalación de equipo nuevo | *Instalación de sistema VRF en edificio corporativo* |
| `venta_refaccion` | Venta de pieza o refacción | *Compresor Danfoss scrolla para chiller Carrier* |

---

## Datos

Los archivos Excel fuente contienen información confidencial de clientes y están excluidos del repositorio. Para reproducir el proyecto necesitas:

- `reporteMensual_FACTURAS.xlsx` — Facturas con fecha, cliente, concepto y monto
- `CARTERA AL 11032026.xlsx` — Cuentas por cobrar y cotizaciones pendientes
- `CONTROL DE INST. MINISPLIT 2026.xlsx` — Registro de instalaciones

El único archivo de datos incluido en el repo es `data/processed/conceptos_clasificados.csv`, con las 73 etiquetas curadas manualmente para entrenar el clasificador NLP.

---

*Proyecto en desarrollo activo. Próximas fases: agentes de cobranza automatizados, integración de API REST y expansión del dashboard.*
