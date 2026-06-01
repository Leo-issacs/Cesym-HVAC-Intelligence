"""
Dashboard HVAC — Streamlit

Tres tabs:
  📊 Resumen General  → métricas globales + tabla de pendientes
  🏆 Score Clientes   → tabla con colores + filtros
  📈 Forecast de Caja → serie histórica + programado + proyección a 3 meses

Para correr:
    streamlit run src/dashboard/app.py
"""

import pathlib
import sqlite3
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ── Rutas ─────────────────────────────────────────────────────────────────────
ROOT    = pathlib.Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "db" / "hvac.db"

# ── Configuración de la página ─────────────────────────────────────────────────
st.set_page_config(
    page_title="HVAC — Dashboard Operativo",
    page_icon="🌡️",
    layout="wide",
)

# ══════════════════════════════════════════════════════════════════════════════
# Carga de datos con caché
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data
def load_facturas() -> pd.DataFrame:
    """
    Lee la tabla `facturas` desde SQLite.

    @st.cache_data guarda el resultado en memoria: la primera llamada accede
    al disco, las siguientes devuelven el DataFrame almacenado. Streamlit
    invalida el caché automáticamente si cambia el hash del argumento
    (aquí no hay argumentos, así que dura toda la sesión).
    """
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql(
            "SELECT * FROM facturas WHERE total IS NOT NULL",
            con,
            parse_dates=["fecha_factura", "fecha_pago"],
        )


@st.cache_data
def load_scores() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql("SELECT * FROM scores_clientes", con)


# ── Guardia: la DB debe existir antes de renderizar ──────────────────────────
if not DB_PATH.exists():
    st.error(
        f"Base de datos no encontrada en `{DB_PATH.relative_to(ROOT)}`.\n\n"
        "Ejecuta primero:\n```\npython -X utf8 scripts/cargar_bd.py --limpiar\n"
        "python -X utf8 src/models/client_score.py\n```"
    )
    st.stop()

facturas = load_facturas()
scores   = load_scores()

# ── Cabecera ──────────────────────────────────────────────────────────────────
st.title("🌡️ HVAC — Dashboard Operativo")
st.caption(f"Datos actualizados al {date.today().strftime('%d/%m/%Y')}")

tab1, tab2, tab3 = st.tabs([
    "📊 Resumen General",
    "🏆 Score de Clientes",
    "📈 Forecast de Caja",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Resumen General
# ══════════════════════════════════════════════════════════════════════════════

with tab1:
    # ── Métricas globales ─────────────────────────────────────────────────────
    total_facturado = facturas["total"].sum()
    total_cobrado   = facturas.loc[facturas["pagada"] == 1, "total"].sum()
    total_pendiente = facturas.loc[facturas["pagada"] == 0, "total"].sum()
    avg_dias_cobro  = facturas.loc[facturas["pagada"] == 1, "dias_pago"].mean()
    pct_cobrado     = total_cobrado / total_facturado * 100 if total_facturado else 0

    c1, c2, c3, c4 = st.columns(4)

    # st.metric(label, value, delta)
    # delta_color="normal"  → verde si positivo, rojo si negativo
    # delta_color="inverse" → rojo si positivo (útil cuando "más es peor")
    c1.metric(
        label="Total Facturado",
        value=f"${total_facturado:,.0f}",
    )
    c2.metric(
        label="Total Cobrado",
        value=f"${total_cobrado:,.0f}",
        delta=f"{pct_cobrado:.1f}% del facturado",
    )
    c3.metric(
        label="Total Pendiente",
        value=f"${total_pendiente:,.0f}",
        delta=f"{100 - pct_cobrado:.1f}% sin cobrar",
        delta_color="inverse",   # positivo = malo aquí
    )
    c4.metric(
        label="Días Promedio de Cobro",
        value=f"{avg_dias_cobro:.1f} días",
    )

    st.markdown("---")

    # ── Desglose por cliente ──────────────────────────────────────────────────
    st.subheader("Facturado vs. Cobrado por Cliente")

    por_cliente = (
        facturas.groupby("cliente")
        .agg(
            facturado=("total", "sum"),
            cobrado=("total", lambda s: s[facturas.loc[s.index, "pagada"] == 1].sum()),
        )
        .reset_index()
        .sort_values("facturado", ascending=False)
    )

    # Recalcular cobrado correctamente (el lambda anterior pierde el contexto)
    cobrado_x_cliente = (
        facturas[facturas["pagada"] == 1]
        .groupby("cliente")["total"].sum()
        .rename("cobrado")
    )
    facturado_x_cliente = facturas.groupby("cliente")["total"].sum().rename("facturado")
    por_cliente = pd.concat([facturado_x_cliente, cobrado_x_cliente], axis=1).fillna(0)
    por_cliente["pendiente"] = por_cliente["facturado"] - por_cliente["cobrado"]
    por_cliente = por_cliente.sort_values("facturado", ascending=False).reset_index()

    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        name="Cobrado",
        x=por_cliente["cliente"],
        y=por_cliente["cobrado"],
        marker_color="#2196F3",
    ))
    fig_bar.add_trace(go.Bar(
        name="Pendiente",
        x=por_cliente["cliente"],
        y=por_cliente["pendiente"],
        marker_color="#FF7043",
    ))
    fig_bar.update_layout(
        barmode="stack",
        xaxis_tickangle=-35,
        yaxis_tickformat="$,.0f",
        yaxis_title="Monto ($)",
        legend=dict(orientation="h", y=1.05),
        height=380,
        margin=dict(t=40, b=80),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # ── Tabla de facturas pendientes ──────────────────────────────────────────
    st.subheader("Facturas Pendientes de Cobro")

    pendientes = (
        facturas[facturas["pagada"] == 0]
        .dropna(subset=["cliente"])
        .sort_values("fecha_factura", ascending=False)
        [["folio", "cliente", "fecha_factura", "concepto", "total"]]
    )
    pendientes = pendientes.copy()
    pendientes["fecha_factura"] = pendientes["fecha_factura"].dt.strftime("%d/%m/%Y")
    pendientes["total"]         = pendientes["total"].map("${:,.2f}".format)
    pendientes.columns          = ["Folio", "Cliente", "Fecha Factura", "Concepto", "Total ($)"]

    st.dataframe(pendientes, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Score de Clientes
# ══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.subheader("Scores de Clientes")

    df_sc = scores.copy()

    # ── Filtro por tipo de cliente (si la columna existe) ─────────────────────
    if "tipo_cliente" in df_sc.columns:
        tipos    = ["Todos"] + sorted(df_sc["tipo_cliente"].dropna().unique().tolist())
        tipo_sel = st.selectbox("Filtrar por tipo de cliente", tipos)
        if tipo_sel != "Todos":
            df_sc = df_sc[df_sc["tipo_cliente"] == tipo_sel]
    else:
        # Alternativa: filtro por nombre de cliente
        clientes_disp = sorted(df_sc["cliente"].unique().tolist())
        sel = st.multiselect(
            "Filtrar clientes (vacío = mostrar todos)",
            options=clientes_disp,
            default=[],
        )
        if sel:
            df_sc = df_sc[df_sc["cliente"].isin(sel)]

    # ── Preparar tabla de display ─────────────────────────────────────────────
    # Mantenemos los scores como numéricos aquí; el Styler formatea la vista
    # sin modificar los valores subyacentes que usa style.apply() para colorear.
    display = df_sc[[
        "cliente", "n_facturas", "monto_total",
        "avg_dias_pago", "pct_impagadas",
        "score_pago", "score_valor", "score_riesgo",
    ]].copy()

    display.columns = [
        "Cliente", "# Facturas", "Monto Total",
        "Días Prom.", "% Impagadas",
        "Score Pago", "Score Valor", "Score Riesgo",
    ]

    # ── Función de coloreado ──────────────────────────────────────────────────
    # style.apply(func, axis=1) llama a func con cada fila como pd.Series.
    # Los valores en la fila son los NUMÉRICOS originales (format() no los cambia).
    def colorear_riesgo(row: pd.Series):
        """Fondo rojo claro para clientes con Score Riesgo > 70."""
        if row["Score Riesgo"] > 70:
            return ["background-color: #ffe0e0; color: #8b0000"] * len(row)
        return [""] * len(row)

    # Barra de progreso en los tres scores (0–100 es el rango natural)
    styled = (
        display.style
        .apply(colorear_riesgo, axis=1)
        .format({
            "Monto Total":   "${:,.0f}",
            "Días Prom.":    "{:.1f}",
            "% Impagadas":   "{:.1%}",
            "Score Pago":    "{:.1f}",
            "Score Valor":   "{:.1f}",
            "Score Riesgo":  "{:.1f}",
        })
        # Barras de color en los tres scores: verde→rojo según magnitud
        .bar(
            subset=["Score Pago"],
            color=["#ef9a9a", "#a5d6a7"],   # rojo barra vacía, verde barra llena
            vmin=0, vmax=100,
        )
        .bar(
            subset=["Score Valor"],
            color=["#fff9c4", "#1565c0"],
            vmin=0, vmax=100,
        )
        .bar(
            subset=["Score Riesgo"],
            color=["#c8e6c9", "#e53935"],   # verde vacío, rojo lleno (riesgo)
            vmin=0, vmax=100,
        )
    )

    st.dataframe(styled, use_container_width=True, hide_index=True)

    # Leyenda
    st.markdown(
        """
        | Score | Interpretación |
        |---|---|
        | **Score Pago** | 100 = paga en días, 0 = nunca ha pagado |
        | **Score Valor** | 100 = el cliente más valioso del portafolio |
        | **Score Riesgo** | 100 = máximo riesgo de no cobrar · **rojo = riesgo > 70** |
        """
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Forecast de Caja
# ══════════════════════════════════════════════════════════════════════════════

with tab3:
    st.subheader("Ingresos Históricos y Proyección de Caja")

    # ── Construir serie mensual completa ──────────────────────────────────────
    # Separamos en tres capas:
    #   hist      → pagada=1 y fecha_pago ≤ hoy (cobros ya realizados)
    #   programado → pagada=1 y fecha_pago > hoy (fechas de pago ya asignadas)
    #   Para la proyección estadística solo usamos "hist"
    pagadas = facturas[facturas["pagada"] == 1].dropna(subset=["fecha_pago"]).copy()
    pagadas["mes"] = pagadas["fecha_pago"].dt.to_period("M").dt.to_timestamp()

    mensual_total = pagadas.groupby("mes")["total"].sum()

    hoy = pd.Timestamp(date.today()).normalize()

    hist_raw = mensual_total[mensual_total.index <= hoy]
    prog_raw = mensual_total[mensual_total.index > hoy]

    # Rellenar meses vacíos en el histórico para que el modelo vea todos los meses
    if len(hist_raw) >= 2:
        idx_hist = pd.date_range(hist_raw.index.min(), hist_raw.index.max(), freq="MS")
        hist_serie = hist_raw.reindex(idx_hist, fill_value=0)
    else:
        hist_serie = hist_raw

    # ── Modelo de proyección: promedio ponderado exponencial + tendencia ──────
    # Usamos los últimos N_MESES meses del histórico para la proyección.
    # Pesos exponenciales: el mes más reciente pesa más que el más antiguo.
    N_MESES = min(6, len(hist_serie))
    ventana  = hist_serie.tail(N_MESES)

    # Pesos: np.linspace(0,1,N) genera valores equiespaciados 0→1;
    # np.exp() los convierte en exponenciales; normalizamos a suma=1.
    pesos_exp   = np.exp(np.linspace(0, 1, N_MESES))
    pesos_exp  /= pesos_exp.sum()
    media_ponderada = float(np.dot(ventana.values, pesos_exp))

    # Tendencia lineal: np.polyfit devuelve [pendiente, intercepto]
    # Solo usamos la pendiente para proyectar cuánto crece/decrece por mes.
    x_vals    = np.arange(N_MESES)
    pendiente = float(np.polyfit(x_vals, ventana.values, 1)[0])

    # Los 3 meses de forecast comienzan después del último mes con cualquier dato
    ultimo_mes_conocido = mensual_total.index.max() if len(mensual_total) else hoy
    meses_fc = pd.date_range(
        ultimo_mes_conocido + pd.DateOffset(months=1),
        periods=3,
        freq="MS",
    )

    fc_vals    = [max(0.0, media_ponderada + pendiente * (i + 1)) for i in range(3)]
    std_hist   = float(ventana.std()) if len(ventana) > 1 else media_ponderada * 0.2
    ci_upper   = [v + 1.5 * std_hist for v in fc_vals]
    ci_lower   = [max(0.0, v - 1.5 * std_hist) for v in fc_vals]

    # ── Gráfica ───────────────────────────────────────────────────────────────
    fig = go.Figure()

    # 1. Banda de confianza (± 1.5σ)
    # El truco del polígono cerrado: concatenar x de ida y vuelta con y upper+lower
    x_banda = list(meses_fc) + list(meses_fc[::-1])
    y_banda = ci_upper + ci_lower[::-1]
    fig.add_trace(go.Scatter(
        x=x_banda,
        y=y_banda,
        fill="toself",
        fillcolor="rgba(255, 140, 0, 0.12)",
        line=dict(color="rgba(0,0,0,0)"),
        name="Intervalo ±1.5σ",
        hoverinfo="skip",
        showlegend=True,
    ))

    # 2. Serie histórica
    fig.add_trace(go.Scatter(
        x=hist_serie.index,
        y=hist_serie.values,
        mode="lines+markers",
        name="Cobrado (histórico)",
        line=dict(color="#1565C0", width=2.5),
        marker=dict(size=7, color="#1565C0"),
    ))

    # 3. Pagos programados (fecha_pago ya asignada pero en el futuro)
    if not prog_raw.empty:
        fig.add_trace(go.Scatter(
            x=prog_raw.index,
            y=prog_raw.values,
            mode="lines+markers",
            name="Programado (fecha asignada)",
            line=dict(color="#2E7D32", width=2, dash="dot"),
            marker=dict(size=8, symbol="diamond", color="#2E7D32"),
        ))

    # 4. Proyección estadística
    fig.add_trace(go.Scatter(
        x=meses_fc,
        y=fc_vals,
        mode="lines+markers",
        name="Proyección estadística",
        line=dict(color="#E65100", width=2.5, dash="dash"),
        marker=dict(size=9, symbol="triangle-up", color="#E65100"),
    ))

    # Línea vertical "hoy"
    # plotly 6.x + pandas 3.x no acepta pd.Timestamp directamente → convertir a string ISO
    fig.add_vline(
        x=hoy.strftime("%Y-%m-%d"),
        line_width=1.5,
        line_dash="dot",
        line_color="#757575",
        annotation_text="  Hoy",
        annotation_position="top right",
        annotation_font_color="#757575",
    )

    fig.update_layout(
        xaxis_title="Mes",
        yaxis_title="Ingresos ($)",
        yaxis_tickformat="$,.0f",
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="left",   x=0,
        ),
        hovermode="x unified",
        height=460,
        margin=dict(t=60, b=40),
        plot_bgcolor="white",
        paper_bgcolor="white",
        xaxis=dict(showgrid=True, gridcolor="#f0f0f0"),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0"),
    )

    st.plotly_chart(fig, use_container_width=True)

    # ── Tabla resumen del forecast ────────────────────────────────────────────
    st.markdown("#### Proyección mensual detallada")

    nombres_mes = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
        5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
        9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
    }

    df_fc = pd.DataFrame({
        "Mes": [f"{nombres_mes[m.month]} {m.year}" for m in meses_fc],
        "Proyección":       [f"${v:,.0f}" for v in fc_vals],
        "Escenario bajo":   [f"${v:,.0f}" for v in ci_lower],
        "Escenario alto":   [f"${v:,.0f}" for v in ci_upper],
    })
    st.dataframe(df_fc, use_container_width=True, hide_index=True)

    with st.expander("ℹ️ Metodología del forecast"):
        st.markdown(f"""
**Modelo:** Promedio ponderado exponencial de los últimos **{N_MESES} meses** + tendencia lineal.

- Los pesos crecen exponencialmente: el mes más reciente tiene mayor influencia.
- La tendencia se calcula con regresión lineal sobre la ventana histórica.
- `Proyección[i] = media_ponderada + pendiente × i`

**Intervalo de confianza:** ±1.5 desviaciones estándar del histórico reciente.

**Nota:** Con ~{len(hist_serie)} meses de historia, el intervalo es amplio por diseño.
A medida que crezca el histórico, la proyección será más precisa.
        """)
