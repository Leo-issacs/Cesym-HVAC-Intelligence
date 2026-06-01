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
    page_title="Cesym — Dashboard Operativo",
    page_icon="🌡️",
    layout="wide",
)

# ══════════════════════════════════════════════════════════════════════════════
# Estilos globales
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ── Tipografía y fondo ─────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', Arial, sans-serif !important;
}
.stApp {
    background-color: #F8F9FA !important;
}
.block-container {
    padding-left: 32px !important;
    padding-right: 32px !important;
    padding-top: 24px !important;
}

/* ── Header ─────────────────────────────────────────────────────────────── */
.dash-header {
    border-bottom: 3px solid #2C3E7A;
    padding-bottom: 14px;
    margin-bottom: 20px;
}
.dash-header h1 {
    font-size: 28px;
    font-weight: 700;
    color: #2C3E50;
    margin: 0 0 4px 0;
    line-height: 1.2;
}
.dash-header p {
    font-size: 13px;
    color: #7F8C8D;
    margin: 0;
}

/* ── KPI Cards ──────────────────────────────────────────────────────────── */
.kpi-card {
    background: #FFFFFF;
    border: 1px solid #E8ECF0;
    border-radius: 12px;
    padding: 18px 20px;
    box-shadow: 0 2px 10px rgba(44,62,122,0.07);
    display: flex;
    align-items: flex-start;
    gap: 14px;
    height: 100%;
}
.kpi-icon-wrap {
    border-radius: 10px;
    padding: 10px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
}
.kpi-body { flex: 1; min-width: 0; }
.kpi-label {
    font-size: 11px;
    font-weight: 600;
    color: #7F8C8D;
    text-transform: uppercase;
    letter-spacing: 0.7px;
    margin: 0 0 5px 0;
}
.kpi-value {
    font-size: 22px;
    font-weight: 700;
    color: #2C3E50;
    line-height: 1.2;
    margin: 0 0 8px 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.kpi-badge {
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 9px;
    border-radius: 20px;
}
.kpi-success { background: #D5F5E3; color: #1A7A42; }
.kpi-danger  { background: #FADBD8; color: #C0392B; }
.kpi-neutral { background: #EBF5FB; color: #1A5276; }

/* ── Dividers ───────────────────────────────────────────────────────────── */
hr {
    border: none !important;
    border-top: 1px solid #E8ECF0 !important;
    margin: 20px 0 !important;
}

/* ── Tabs ───────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background: #FFFFFF;
    border: 1px solid #E8ECF0;
    border-radius: 10px;
    padding: 4px;
    gap: 4px;
    margin-bottom: 4px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 7px !important;
    padding: 8px 20px !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    color: #7F8C8D !important;
    background: transparent !important;
    transition: all 0.15s ease;
}
.stTabs [aria-selected="true"][data-baseweb="tab"] {
    background: #2C3E7A !important;
    color: #FFFFFF !important;
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] {
    display: none !important;
}

/* ── Headings ───────────────────────────────────────────────────────────── */
h2, h3 { color: #2C3E50 !important; }
</style>
""", unsafe_allow_html=True)

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

# ══════════════════════════════════════════════════════════════════════════════
# Helper: KPI card
# ══════════════════════════════════════════════════════════════════════════════

def kpi_card(icon_svg: str, icon_bg: str, icon_color: str,
             label: str, value: str,
             badge_text: str = "", badge_cls: str = "kpi-neutral") -> str:
    """Genera HTML de una KPI card. SVG debe ser una cadena compacta (sin saltos de línea)."""
    badge = f'<span class="kpi-badge {badge_cls}">{badge_text}</span>' if badge_text else ""
    return (
        f'<div class="kpi-card">'
        f'<div class="kpi-icon-wrap" style="background:{icon_bg};color:{icon_color};">{icon_svg}</div>'
        f'<div class="kpi-body">'
        f'<p class="kpi-label">{label}</p>'
        f'<p class="kpi-value">{value}</p>'
        f'{badge}'
        f'</div></div>'
    )


# SVG icons compactos (Feather-style, sin saltos de línea para evitar
# que el parser de markdown de Streamlit rompa el HTML al renderizar)
ICON_FACTURA = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>'

ICON_COBRADO = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'

ICON_PENDIENTE = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>'

ICON_CALENDARIO = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>'


# ── Cabecera ──────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="dash-header">
  <h1>🌡️ Cesym — Dashboard Operativo</h1>
  <p>Datos actualizados al {date.today().strftime('%d/%m/%Y')}</p>
</div>
""", unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs([
    "📊 Resumen General",
    "🏆 Score de Clientes",
    "📈 Forecast de Caja",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Resumen General
# ══════════════════════════════════════════════════════════════════════════════

with tab1:
    # ── Cálculo de métricas (lógica sin cambios) ──────────────────────────────
    total_facturado = facturas["total"].sum()
    total_cobrado   = facturas.loc[facturas["pagada"] == 1, "total"].sum()
    total_pendiente = facturas.loc[facturas["pagada"] == 0, "total"].sum()
    avg_dias_cobro  = facturas.loc[facturas["pagada"] == 1, "dias_pago"].mean()
    pct_cobrado     = total_cobrado / total_facturado * 100 if total_facturado else 0

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    # Un único bloque HTML con CSS grid evita el bug de Streamlit donde el
    # parser de markdown parte el HTML en columnas separadas y deja tags sueltos.
    cards_html = (
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:8px;">'
        + kpi_card(ICON_FACTURA,    "#EEF1F8", "#2C3E7A",
                   "Total Facturado",    f"${total_facturado:,.0f}")
        + kpi_card(ICON_COBRADO,    "#E8F8F0", "#1A7A42",
                   "Total Cobrado",      f"${total_cobrado:,.0f}",
                   f"↑ {pct_cobrado:.1f}% del facturado", "kpi-success")
        + kpi_card(ICON_PENDIENTE,  "#FEF5EC", "#C0392B",
                   "Total Pendiente",    f"${total_pendiente:,.0f}",
                   f"↑ {100 - pct_cobrado:.1f}% sin cobrar", "kpi-danger")
        + kpi_card(ICON_CALENDARIO, "#EEF1F8", "#2C3E7A",
                   "Días Promedio de Cobro", f"{avg_dias_cobro:.1f} días",
                   "promedio histórico", "kpi-neutral")
        + '</div>'
    )
    st.markdown(cards_html, unsafe_allow_html=True)

    st.markdown("---")

    # ── Gráfica Facturado vs. Cobrado (top 10 clientes) ───────────────────────
    st.subheader("Facturado vs. Cobrado — Top 10 Clientes")

    # Cálculo (lógica sin cambios)
    cobrado_x_cliente   = (facturas[facturas["pagada"] == 1]
                           .groupby("cliente")["total"].sum().rename("cobrado"))
    facturado_x_cliente = facturas.groupby("cliente")["total"].sum().rename("facturado")
    por_cliente = pd.concat([facturado_x_cliente, cobrado_x_cliente], axis=1).fillna(0)
    por_cliente["pendiente"] = por_cliente["facturado"] - por_cliente["cobrado"]
    por_cliente = por_cliente.sort_values("facturado", ascending=False).reset_index()

    # UI: limitar a top 10 para no pisar etiquetas en el eje X
    top10 = por_cliente.head(10).copy()

    def fmt_monto(v: float) -> str:
        """Formato compacto: $X.XM o $XXXk."""
        if v >= 1_000_000:
            return f"${v/1_000_000:.1f}M"
        return f"${v/1_000:.0f}k"

    fig_bar = go.Figure()

    fig_bar.add_trace(go.Bar(
        name="Cobrado",
        x=top10["cliente"],
        y=top10["cobrado"],
        marker_color="#27AE60",
        marker_line_width=0,
    ))
    fig_bar.add_trace(go.Bar(
        name="Pendiente",
        x=top10["cliente"],
        y=top10["pendiente"],
        marker_color="#E67E22",
        marker_line_width=0,
        # Etiqueta del total sobre cada barra (encima del segmento superior)
        text=[fmt_monto(v) for v in top10["facturado"]],
        textposition="outside",
        textfont=dict(size=11, color="#2C3E50", family="Inter, Arial"),
        cliponaxis=False,
    ))

    fig_bar.update_layout(
        barmode="stack",
        yaxis_tickformat="$,.0f",
        yaxis_title="Monto ($)",
        legend=dict(orientation="h", y=1.08, x=0),
        height=400,
        margin=dict(t=50, b=20, l=10, r=10),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Inter, Arial"),
        xaxis=dict(
            tickfont=dict(size=9, color="#2C3E50"),
            tickangle=-30,
            showgrid=False,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(0,0,0,0.06)",
            gridwidth=1,
            zeroline=False,
        ),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # ── Tabla de facturas pendientes (lógica sin cambios) ─────────────────────
    st.markdown("---")
    st.subheader("Facturas Pendientes de Cobro")

    pendientes = (
        facturas[facturas["pagada"] == 0]
        .dropna(subset=["cliente"])
        .sort_values("fecha_factura", ascending=False)
        [["folio", "cliente", "fecha_factura", "concepto", "total"]]
    ).copy()
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
        clientes_disp = sorted(df_sc["cliente"].unique().tolist())
        sel = st.multiselect(
            "Filtrar clientes (vacío = mostrar todos)",
            options=clientes_disp,
            default=[],
        )
        if sel:
            df_sc = df_sc[df_sc["cliente"].isin(sel)]

    # ── Preparar tabla de display ─────────────────────────────────────────────
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

    def colorear_riesgo(row: pd.Series):
        """Fondo rojo claro para clientes con Score Riesgo > 70."""
        if row["Score Riesgo"] > 70:
            return ["background-color: #ffe0e0; color: #8b0000"] * len(row)
        return [""] * len(row)

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
        .bar(subset=["Score Pago"],   color=["#ef9a9a", "#a5d6a7"], vmin=0, vmax=100)
        .bar(subset=["Score Valor"],  color=["#fff9c4", "#1565c0"], vmin=0, vmax=100)
        .bar(subset=["Score Riesgo"], color=["#c8e6c9", "#e53935"], vmin=0, vmax=100)
    )

    st.dataframe(styled, use_container_width=True, hide_index=True)

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

    # ── Construir serie mensual completa (lógica sin cambios) ─────────────────
    pagadas = facturas[facturas["pagada"] == 1].dropna(subset=["fecha_pago"]).copy()
    pagadas["mes"] = pagadas["fecha_pago"].dt.to_period("M").dt.to_timestamp()

    mensual_total = pagadas.groupby("mes")["total"].sum()

    hoy = pd.Timestamp(date.today()).normalize()

    hist_raw = mensual_total[mensual_total.index <= hoy]
    prog_raw = mensual_total[mensual_total.index > hoy]

    if len(hist_raw) >= 2:
        idx_hist = pd.date_range(hist_raw.index.min(), hist_raw.index.max(), freq="MS")
        hist_serie = hist_raw.reindex(idx_hist, fill_value=0)
    else:
        hist_serie = hist_raw

    N_MESES = min(6, len(hist_serie))
    ventana  = hist_serie.tail(N_MESES)

    pesos_exp   = np.exp(np.linspace(0, 1, N_MESES))
    pesos_exp  /= pesos_exp.sum()
    media_ponderada = float(np.dot(ventana.values, pesos_exp))

    x_vals    = np.arange(N_MESES)
    pendiente = float(np.polyfit(x_vals, ventana.values, 1)[0])

    ultimo_mes_conocido = mensual_total.index.max() if len(mensual_total) else hoy
    meses_fc = pd.date_range(
        ultimo_mes_conocido + pd.DateOffset(months=1),
        periods=3,
        freq="MS",
    )

    fc_vals  = [max(0.0, media_ponderada + pendiente * (i + 1)) for i in range(3)]
    std_hist = float(ventana.std()) if len(ventana) > 1 else media_ponderada * 0.2
    ci_upper = [v + 1.5 * std_hist for v in fc_vals]
    ci_lower = [max(0.0, v - 1.5 * std_hist) for v in fc_vals]

    # ── Gráfica ───────────────────────────────────────────────────────────────
    fig = go.Figure()

    # Banda de confianza
    x_banda = list(meses_fc) + list(meses_fc[::-1])
    y_banda = ci_upper + ci_lower[::-1]
    fig.add_trace(go.Scatter(
        x=x_banda, y=y_banda,
        fill="toself",
        fillcolor="rgba(230,126,34,0.10)",
        line=dict(color="rgba(0,0,0,0)"),
        name="Intervalo ±1.5σ",
        hoverinfo="skip",
        showlegend=True,
    ))

    # Serie histórica
    fig.add_trace(go.Scatter(
        x=hist_serie.index, y=hist_serie.values,
        mode="lines+markers",
        name="Cobrado (histórico)",
        line=dict(color="#2C3E7A", width=2.5),
        marker=dict(size=7, color="#2C3E7A"),
    ))

    # Pagos programados
    if not prog_raw.empty:
        fig.add_trace(go.Scatter(
            x=prog_raw.index, y=prog_raw.values,
            mode="lines+markers",
            name="Programado (fecha asignada)",
            line=dict(color="#27AE60", width=2, dash="dot"),
            marker=dict(size=8, symbol="diamond", color="#27AE60"),
        ))

    # Proyección estadística
    fig.add_trace(go.Scatter(
        x=meses_fc, y=fc_vals,
        mode="lines+markers",
        name="Proyección estadística",
        line=dict(color="#E67E22", width=2.5, dash="dash"),
        marker=dict(size=9, symbol="triangle-up", color="#E67E22"),
    ))

    # Línea vertical "hoy" (add_shape + add_annotation — ver nota en Tab 3)
    hoy_ms = int(hoy.timestamp() * 1000)
    fig.add_shape(
        type="line",
        x0=hoy_ms, x1=hoy_ms, y0=0, y1=1,
        xref="x", yref="paper",
        line=dict(width=1.5, dash="dot", color="#95A5A6"),
    )
    fig.add_annotation(
        x=hoy_ms, y=1, xref="x", yref="paper",
        text="Hoy", showarrow=False,
        xanchor="left", font=dict(color="#95A5A6", size=11, family="Inter, Arial"),
    )

    fig.update_layout(
        xaxis_title="Mes",
        yaxis_title="Ingresos ($)",
        yaxis_tickformat="$,.0f",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified",
        height=460,
        margin=dict(t=60, b=40),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Inter, Arial"),
        xaxis=dict(showgrid=True, gridcolor="rgba(0,0,0,0.05)"),
        yaxis=dict(showgrid=True, gridcolor="rgba(0,0,0,0.05)", zeroline=False),
    )

    st.plotly_chart(fig, use_container_width=True)

    # ── Tabla resumen del forecast (lógica sin cambios) ───────────────────────
    st.markdown("#### Proyección mensual detallada")

    nombres_mes = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
        5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
        9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
    }

    df_fc = pd.DataFrame({
        "Mes":              [f"{nombres_mes[m.month]} {m.year}" for m in meses_fc],
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
