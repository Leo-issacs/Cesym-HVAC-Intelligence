"""
Dashboard Cesym — Streamlit + Plotly

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

# ── Config ────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Cesym — Dashboard Operativo",
    page_icon="🌡️",
    layout="wide",
)

# ══════════════════════════════════════════════════════════════════════════════
# CSS global — inyectado vía st.html() (confirmado que funciona en este entorno)
# ══════════════════════════════════════════════════════════════════════════════

st.html("""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ── Variables ────────────────────────────────────────── */
:root {
  --color-primary:  #1B3A6B;
  --color-success:  #27AE60;
  --color-warning:  #E67E22;
  --color-danger:   #E74C3C;
  --color-bg:       #F0F2F5;
  --color-card:     #FFFFFF;
  --color-text:     #2C3E50;
  --color-muted:    #95A5A6;
  --shadow-sm:      0 2px 8px rgba(0,0,0,0.08);
  --shadow-md:      0 4px 16px rgba(0,0,0,0.14);
  --radius:         12px;
  --transition:     all 0.25s ease;
}

/* ── Base ─────────────────────────────────────────────── */
html, body, [class*="css"] { font-family:'Inter',Arial,sans-serif !important; }
.stApp, [data-testid="stAppViewContainer"] { background:var(--color-bg) !important; }
.block-container { padding:24px 32px !important; max-width:1400px !important; }

/* ── Header ───────────────────────────────────────────── */
.dash-header { border-bottom:3px solid var(--color-primary); padding-bottom:14px; margin-bottom:20px; }
.dash-header h1 { font-size:28px; font-weight:700; color:var(--color-text); margin:0 0 4px; }
.dash-header p  { font-size:13px; color:var(--color-muted); margin:0; }

/* ── Tabs ─────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
  background:#FFF; border:1px solid #E8ECF0; border-radius:10px; padding:4px; gap:4px;
}
.stTabs [data-baseweb="tab"] {
  border-radius:8px !important; padding:8px 20px !important;
  font-size:14px !important; font-weight:500 !important;
  color:var(--color-muted) !important; background:transparent !important;
  transition:var(--transition) !important;
}
.stTabs [data-baseweb="tab"]:hover {
  background:rgba(27,58,107,0.08) !important;
  color:var(--color-primary) !important;
  transform:translateY(-1px);
}
.stTabs [aria-selected="true"][data-baseweb="tab"] {
  background:var(--color-primary) !important; color:#FFF !important;
  font-weight:600 !important; border-bottom:3px solid var(--color-primary);
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display:none !important; }

/* ── Dividers ─────────────────────────────────────────── */
hr { border:none !important; border-top:1px solid #E8ECF0 !important; margin:24px 0 !important; }

/* ── KPI Cards ────────────────────────────────────────── */
.kpi-card {
  background:var(--color-card); border:1px solid #E8ECF0;
  border-radius:var(--radius); padding:18px 20px;
  box-shadow:var(--shadow-sm); display:flex; align-items:flex-start;
  gap:14px; transition:var(--transition); cursor:default;
}
.kpi-card:hover {
  transform:translateY(-4px); box-shadow:var(--shadow-md);
  border-color:rgba(27,58,107,0.4);
}
.kpi-card:hover .kpi-icon-wrap { background:var(--color-primary) !important; color:#FFF !important; }
.kpi-card:hover .kpi-badge     { font-weight:700; }
.kpi-icon-wrap {
  border-radius:10px; padding:10px; flex-shrink:0;
  display:flex; align-items:center; justify-content:center;
  width:44px; height:44px; transition:var(--transition);
  font-size:22px; line-height:1;
}
.kpi-body   { flex:1; min-width:0; }
.kpi-label  { font-size:11px; font-weight:600; color:var(--color-muted);
              text-transform:uppercase; letter-spacing:.7px; margin:0 0 5px; }
.kpi-value  { font-size:22px; font-weight:700; color:var(--color-text);
              line-height:1.2; margin:0 0 8px; white-space:nowrap;
              overflow:hidden; text-overflow:ellipsis; }
.kpi-badge  { display:inline-block; font-size:11px; font-weight:600;
              padding:3px 9px; border-radius:20px; transition:var(--transition); }
.kpi-success { background:#D5F5E3; color:#1A7A42; }
.kpi-danger  { background:#FADBD8; color:#C0392B; }
.kpi-neutral { background:#EBF5FB; color:#1A5276; }

/* ── Tabla custom ─────────────────────────────────────── */
.custom-table { width:100%; border-collapse:collapse; font-size:13px; }
.custom-table thead th {
  background:var(--color-primary); color:#FFF; font-weight:600;
  padding:12px 16px; text-align:left; position:sticky; top:0; white-space:nowrap;
}
.custom-table tbody tr { border-left:3px solid transparent; transition:var(--transition); }
.custom-table tbody tr:nth-child(even) { background:#F8F9FA; }
.custom-table tbody tr:hover {
  background:rgba(27,58,107,0.06) !important;
  border-left-color:var(--color-primary); cursor:pointer;
}
.custom-table td { padding:10px 16px; border-bottom:1px solid #F0F2F5; }
.folio-pill {
  background:#EEF2FF; color:var(--color-primary);
  border-radius:20px; padding:2px 10px; font-size:12px; font-weight:600;
}
.total-cell  { color:var(--color-primary); font-weight:600; }
.table-foot  { background:var(--color-primary) !important; }
.table-foot td { color:#FFF !important; font-weight:600; padding:11px 16px;
                 border-bottom:none !important; }

/* ── Progress bars (Score Pago) ───────────────────────── */
.bar-wrap { display:flex; align-items:center; gap:8px; }
.bar-track { flex:1; background:#ECEFF1; border-radius:10px; height:8px; overflow:hidden; min-width:80px; }
.bar-fill  { height:100%; border-radius:10px; animation:fillBar .7s ease forwards; }
@keyframes fillBar { from { width:0 !important; } }
.bar-label { font-size:12px; font-weight:600; color:var(--color-text); min-width:32px; text-align:right; }

/* ── Badges riesgo ────────────────────────────────────── */
.badge       { display:inline-block; font-size:11px; font-weight:700;
               padding:3px 9px; border-radius:20px; letter-spacing:.5px; }
.badge-high  { background:#FADBD8; color:#C0392B; }
.badge-mid   { background:#FDEBD0; color:#A04000; }
.badge-low   { background:#D5F5E3; color:#1A7A42; }

/* ── Headings ─────────────────────────────────────────── */
h2, h3 { color:var(--color-text) !important; }
</style>""")

# ══════════════════════════════════════════════════════════════════════════════
# Carga de datos
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data
def load_facturas() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql(
            "SELECT * FROM facturas WHERE total IS NOT NULL", con,
            parse_dates=["fecha_factura", "fecha_pago"],
        )

@st.cache_data
def load_scores() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql("SELECT * FROM scores_clientes", con)

if not DB_PATH.exists():
    st.error(
        f"Base de datos no encontrada en `{DB_PATH.relative_to(ROOT)}`.\n\n"
        "Ejecuta primero:\n```\npython -X utf8 scripts/cargar_bd.py --limpiar\n"
        "python -X utf8 src/models/client_score.py\n```"
    )
    st.stop()

facturas = load_facturas()
scores   = load_scores()

# Estado de paginación para tabla de pendientes
if "inv_page" not in st.session_state:
    st.session_state.inv_page = 0

# ══════════════════════════════════════════════════════════════════════════════
# Helpers de UI
# ══════════════════════════════════════════════════════════════════════════════

def kpi_card(icon_svg, icon_bg, icon_color, label, value, badge_text="", badge_cls="kpi-neutral"):
    badge = f'<span class="kpi-badge {badge_cls}">{badge_text}</span>' if badge_text else ""
    return (
        f'<div class="kpi-card">'
        f'<div class="kpi-icon-wrap" style="background:{icon_bg};color:{icon_color};">{icon_svg}</div>'
        f'<div class="kpi-body">'
        f'<p class="kpi-label">{label}</p>'
        f'<p class="kpi-value">{value}</p>'
        f'{badge}</div></div>'
    )

def score_bar_html(value: float) -> str:
    color = "#27AE60" if value >= 70 else "#E67E22" if value >= 40 else "#E74C3C"
    return (
        f'<div class="bar-wrap">'
        f'<div class="bar-track"><div class="bar-fill" style="width:{value:.1f}%;background:{color};"></div></div>'
        f'<span class="bar-label">{value:.1f}</span>'
        f'</div>'
    )

def risk_badge_html(value: float) -> str:
    if value > 70:
        return f'<span class="badge badge-high">ALTO</span>'
    elif value >= 40:
        return f'<span class="badge badge-mid">MEDIO</span>'
    return f'<span class="badge badge-low">BAJO</span>'

def pct_html(value: float) -> str:
    if value > 0.20:
        return f'<span style="color:#E74C3C;font-weight:600;">{value:.1%}</span>'
    return f'{value:.1%}'

def fmt_monto(v: float) -> str:
    return f"${v/1_000_000:.1f}M" if v >= 1_000_000 else f"${v/1_000:.0f}k"

def render_scores_table(df: pd.DataFrame) -> str:
    rows = ""
    for _, r in df.iterrows():
        rows += (
            f"<tr>"
            f"<td><strong>{r['cliente']}</strong></td>"
            f"<td style='text-align:center;'>{int(r['n_facturas'])}</td>"
            f"<td class='total-cell'>${r['monto_total']:,.0f}</td>"
            f"<td style='text-align:center;'>{r['avg_dias_pago']:.1f}</td>"
            f"<td>{pct_html(r['pct_impagadas'])}</td>"
            f"<td>{score_bar_html(r['score_pago'])}</td>"
            f"<td>{score_bar_html(r['score_valor'])}</td>"
            f"<td>{risk_badge_html(r['score_riesgo'])} <span style='font-size:11px;color:#95A5A6;'>{r['score_riesgo']:.1f}</span></td>"
            f"</tr>"
        )
    return (
        '<div style="overflow-x:auto;border-radius:12px;border:1px solid #E8ECF0;box-shadow:0 2px 8px rgba(0,0,0,0.06);">'
        '<table class="custom-table">'
        '<thead><tr>'
        '<th>Cliente</th><th style="text-align:center;"># Facturas</th>'
        '<th>Monto Total</th><th style="text-align:center;">Días Prom.</th>'
        '<th>% Impagadas</th><th>Score Pago</th>'
        '<th>Score Valor</th><th>Score Riesgo</th>'
        '</tr></thead>'
        f'<tbody>{rows}</tbody>'
        '</table></div>'
    )

def render_invoices_table(df: pd.DataFrame, total_sum: float) -> str:
    rows = ""
    for _, r in df.iterrows():
        concepto = str(r["Concepto"])
        concepto_short = concepto[:55] + "…" if len(concepto) > 55 else concepto
        rows += (
            f"<tr>"
            f"<td><span class='folio-pill'>{r['Folio']}</span></td>"
            f"<td><strong>{r['Cliente']}</strong></td>"
            f"<td style='white-space:nowrap;'>{r['Fecha Factura']}</td>"
            f"<td style='color:#7F8C8D;font-size:12px;' title='{concepto}'>{concepto_short}</td>"
            f"<td class='total-cell' style='white-space:nowrap;'>{r['Total ($)']}</td>"
            f"</tr>"
        )
    return (
        '<div style="overflow-x:auto;border-radius:12px;border:1px solid #E8ECF0;box-shadow:0 2px 8px rgba(0,0,0,0.06);">'
        '<table class="custom-table">'
        '<thead><tr>'
        '<th>Folio</th><th>Cliente</th><th>Fecha</th><th>Concepto</th><th>Total ($)</th>'
        '</tr></thead>'
        f'<tbody>{rows}</tbody>'
        '<tfoot>'
        f'<tr class="table-foot">'
        f'<td colspan="4"><strong>TOTAL PENDIENTE</strong></td>'
        f'<td style="white-space:nowrap;"><strong>${total_sum:,.2f}</strong></td>'
        '</tr></tfoot>'
        '</table></div>'
    )

# SVG icons compactos
ICON_FACTURA    = "🧾"
ICON_COBRADO    = "✅"
ICON_PENDIENTE  = "⏳"
ICON_CALENDARIO = "📅"

HOVER_LABEL = dict(
    bgcolor="white", bordercolor="#1B3A6B",
    font_size=13, font_family="Inter, Arial", font_color="#2C3E50",
)

# ── Cabecera ──────────────────────────────────────────────────────────────────
st.html(f"""
<div class="dash-header">
  <h1>🌡️ Cesym — Dashboard Operativo</h1>
  <p>Datos actualizados al {date.today().strftime('%d/%m/%Y')}</p>
</div>""")

tab1, tab2, tab3 = st.tabs(["📊 Resumen General", "🏆 Score de Clientes", "📈 Forecast de Caja"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Resumen General
# ══════════════════════════════════════════════════════════════════════════════

with tab1:
    # ── Métricas ──────────────────────────────────────────────────────────────
    total_facturado = facturas["total"].sum()
    total_cobrado   = facturas.loc[facturas["pagada"] == 1, "total"].sum()
    total_pendiente = facturas.loc[facturas["pagada"] == 0, "total"].sum()
    avg_dias_cobro  = facturas.loc[facturas["pagada"] == 1, "dias_pago"].mean()
    pct_cobrado     = total_cobrado / total_facturado * 100 if total_facturado else 0

    st.html(
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:8px;">'
        + kpi_card(ICON_FACTURA,    "#EEF1F8", "#1B3A6B",
                   "Total Facturado",       f"${total_facturado:,.0f}")
        + kpi_card(ICON_COBRADO,    "#E8F8F0", "#1A7A42",
                   "Total Cobrado",         f"${total_cobrado:,.0f}",
                   f"↑ {pct_cobrado:.1f}% del facturado", "kpi-success")
        + kpi_card(ICON_PENDIENTE,  "#FEF5EC", "#C0392B",
                   "Total Pendiente",       f"${total_pendiente:,.0f}",
                   f"↑ {100 - pct_cobrado:.1f}% sin cobrar", "kpi-danger")
        + kpi_card(ICON_CALENDARIO, "#EEF1F8", "#1B3A6B",
                   "Días Promedio de Cobro", f"{avg_dias_cobro:.1f} días",
                   "promedio histórico", "kpi-neutral")
        + '</div>'
    )

    st.markdown("---")

    # ── Gráfica barras apiladas — Top 10 ──────────────────────────────────────
    st.subheader("Facturado vs. Cobrado — Top 10 Clientes")

    cobrado_xc   = facturas[facturas["pagada"]==1].groupby("cliente")["total"].sum().rename("cobrado")
    facturado_xc = facturas.groupby("cliente")["total"].sum().rename("facturado")
    pc = pd.concat([facturado_xc, cobrado_xc], axis=1).fillna(0)
    pc["pendiente"] = pc["facturado"] - pc["cobrado"]
    pc = pc.sort_values("facturado", ascending=False).reset_index()
    top10 = pc.head(10).copy()
    top10["pct_cobrado"] = (top10["cobrado"] / top10["facturado"] * 100).fillna(0)

    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        name="Cobrado", x=top10["cliente"], y=top10["cobrado"],
        marker_color="#27AE60", marker_line_width=0,
        customdata=np.column_stack([top10["pendiente"], top10["facturado"], top10["pct_cobrado"]]),
        hovertemplate=(
            "<b>%{x}</b><br>"
            "Cobrado: $%{y:,.0f}<br>"
            "Pendiente: $%{customdata[0]:,.0f}<br>"
            "Total: $%{customdata[1]:,.0f}<br>"
            "% Cobrado: %{customdata[2]:.1f}%"
            "<extra></extra>"
        ),
    ))
    fig_bar.add_trace(go.Bar(
        name="Pendiente", x=top10["cliente"], y=top10["pendiente"],
        marker_color="#E67E22", marker_line_width=0,
        text=[fmt_monto(v) for v in top10["facturado"]],
        textposition="outside",
        textfont=dict(size=11, color="#2C3E50", family="Inter, Arial"),
        cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>Pendiente: $%{y:,.0f}<extra></extra>",
    ))
    fig_bar.update_layout(
        barmode="stack",
        hoverlabel=HOVER_LABEL,
        yaxis_tickformat="$,.0f", yaxis_title="Monto ($)",
        legend=dict(orientation="h", y=1.08, x=0),
        height=400, margin=dict(t=50, b=20, l=10, r=10),
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(family="Inter, Arial"),
        xaxis=dict(tickfont=dict(size=9, color="#2C3E50"), tickangle=-30, showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="rgba(0,0,0,0.06)", gridwidth=1, zeroline=False),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    st.markdown("---")

    # ── Tabla de facturas pendientes con paginación ───────────────────────────
    st.subheader("Facturas Pendientes de Cobro")

    pend_raw = (
        facturas[facturas["pagada"]==0].dropna(subset=["cliente"])
        .sort_values("fecha_factura", ascending=False)
        [["folio","cliente","fecha_factura","concepto","total"]].copy()
    )
    total_pend_sum = pend_raw["total"].sum()
    pend_raw["fecha_factura"] = pend_raw["fecha_factura"].dt.strftime("%d/%m/%Y")
    pend_raw["total_fmt"] = pend_raw["total"].map("${:,.2f}".format)
    pend_raw.columns = ["Folio","Cliente","Fecha Factura","Concepto","_total","Total ($)"]

    PAGE_SIZE = 15
    total_rows  = len(pend_raw)
    total_pages = max(1, (total_rows + PAGE_SIZE - 1) // PAGE_SIZE)
    st.session_state.inv_page = min(st.session_state.inv_page, total_pages - 1)
    p_start = st.session_state.inv_page * PAGE_SIZE
    p_end   = min(p_start + PAGE_SIZE, total_rows)
    page_df = pend_raw.iloc[p_start:p_end]

    # Contador + controles de paginación
    ci, cp, cn = st.columns([5, 1, 1])
    ci.caption(f"Mostrando **{p_start+1}–{p_end}** de **{total_rows}** facturas pendientes")
    if cp.button("◀ Anterior", disabled=st.session_state.inv_page == 0, use_container_width=True):
        st.session_state.inv_page -= 1
        st.rerun()
    if cn.button("Siguiente ▶", disabled=st.session_state.inv_page >= total_pages - 1, use_container_width=True):
        st.session_state.inv_page += 1
        st.rerun()

    st.html(render_invoices_table(page_df, total_pend_sum))


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Score de Clientes
# ══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.subheader("Scores de Clientes")

    df_sc = scores.copy()

    if "tipo_cliente" in df_sc.columns:
        tipos    = ["Todos"] + sorted(df_sc["tipo_cliente"].dropna().unique().tolist())
        tipo_sel = st.selectbox("Filtrar por tipo de cliente", tipos)
        if tipo_sel != "Todos":
            df_sc = df_sc[df_sc["tipo_cliente"] == tipo_sel]
    else:
        sel = st.multiselect(
            "Filtrar clientes (vacío = todos)",
            options=sorted(df_sc["cliente"].unique().tolist()),
            default=[],
        )
        if sel:
            df_sc = df_sc[df_sc["cliente"].isin(sel)]

    df_sc = df_sc.sort_values("score_valor", ascending=False)
    st.html(render_scores_table(df_sc))

    st.markdown("""
    | Score | Interpretación |
    |---|---|
    | **Score Pago** | 100 = paga al instante, 0 = nunca pagó |
    | **Score Valor** | 100 = cliente más valioso del portafolio |
    | **Score Riesgo** | ALTO > 70 · MEDIO 40–70 · BAJO < 40 |
    """)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Forecast de Caja
# ══════════════════════════════════════════════════════════════════════════════

with tab3:
    st.subheader("Ingresos Históricos y Proyección de Caja")

    # ── Serie mensual (lógica sin cambios) ────────────────────────────────────
    pagadas = facturas[facturas["pagada"]==1].dropna(subset=["fecha_pago"]).copy()
    pagadas["mes"] = pagadas["fecha_pago"].dt.to_period("M").dt.to_timestamp()
    mensual_total = pagadas.groupby("mes")["total"].sum()
    hoy = pd.Timestamp(date.today()).normalize()

    hist_raw = mensual_total[mensual_total.index <= hoy]
    prog_raw = mensual_total[mensual_total.index > hoy]

    if len(hist_raw) >= 2:
        idx_hist   = pd.date_range(hist_raw.index.min(), hist_raw.index.max(), freq="MS")
        hist_serie = hist_raw.reindex(idx_hist, fill_value=0)
    else:
        hist_serie = hist_raw

    N_MESES = min(6, len(hist_serie))
    ventana  = hist_serie.tail(N_MESES)
    pesos    = np.exp(np.linspace(0, 1, N_MESES)); pesos /= pesos.sum()
    media    = float(np.dot(ventana.values, pesos))
    pend_lin = float(np.polyfit(np.arange(N_MESES), ventana.values, 1)[0])

    ultimo   = mensual_total.index.max() if len(mensual_total) else hoy
    meses_fc = pd.date_range(ultimo + pd.DateOffset(months=1), periods=3, freq="MS")
    fc_vals  = [max(0.0, media + pend_lin * (i+1)) for i in range(3)]
    std_h    = float(ventana.std()) if len(ventana) > 1 else media * 0.2
    ci_upper = [v + 1.5*std_h for v in fc_vals]
    ci_lower = [max(0.0, v - 1.5*std_h) for v in fc_vals]

    # ── Figura ────────────────────────────────────────────────────────────────
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=list(meses_fc) + list(meses_fc[::-1]),
        y=ci_upper + ci_lower[::-1],
        fill="toself", fillcolor="rgba(230,126,34,0.10)",
        line=dict(color="rgba(0,0,0,0)"),
        name="Intervalo ±1.5σ", hoverinfo="skip", showlegend=True,
    ))
    fig.add_trace(go.Scatter(
        x=hist_serie.index, y=hist_serie.values,
        mode="lines+markers", name="Cobrado (histórico)",
        line=dict(color="#1B3A6B", width=2.5),
        marker=dict(size=7, color="#1B3A6B"),
        hovertemplate="<b>%{x|%b %Y}</b><br>Cobrado: $%{y:,.0f}<extra>Histórico</extra>",
    ))
    if not prog_raw.empty:
        fig.add_trace(go.Scatter(
            x=prog_raw.index, y=prog_raw.values,
            mode="lines+markers", name="Programado (fecha asignada)",
            line=dict(color="#27AE60", width=2, dash="dot"),
            marker=dict(size=8, symbol="diamond", color="#27AE60"),
            hovertemplate="<b>%{x|%b %Y}</b><br>Programado: $%{y:,.0f}<extra>Programado</extra>",
        ))
    fig.add_trace(go.Scatter(
        x=meses_fc, y=fc_vals,
        mode="lines+markers", name="Proyección estadística",
        line=dict(color="#E67E22", width=2.5, dash="dash"),
        marker=dict(size=9, symbol="triangle-up", color="#E67E22"),
        customdata=list(zip(ci_lower, ci_upper)),
        hovertemplate=(
            "<b>%{x|%b %Y}</b><br>"
            "Proyección: $%{y:,.0f}<br>"
            "Rango: $%{customdata[0]:,.0f} – $%{customdata[1]:,.0f}"
            "<extra>Proyección</extra>"
        ),
    ))

    hoy_ms = int(hoy.timestamp() * 1000)
    fig.add_shape(type="line", x0=hoy_ms, x1=hoy_ms, y0=0, y1=1,
                  xref="x", yref="paper", line=dict(width=1.5, dash="dot", color="#95A5A6"))
    fig.add_annotation(x=hoy_ms, y=1, xref="x", yref="paper",
                       text="Hoy", showarrow=False, xanchor="left",
                       font=dict(color="#95A5A6", size=11))

    fig.update_layout(
        hoverlabel=HOVER_LABEL, hovermode="x unified",
        xaxis_title="Mes", yaxis_title="Ingresos ($)", yaxis_tickformat="$,.0f",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        height=460, margin=dict(t=60, b=40),
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(family="Inter, Arial"),
        xaxis=dict(showgrid=True, gridcolor="rgba(0,0,0,0.05)"),
        yaxis=dict(showgrid=True, gridcolor="rgba(0,0,0,0.05)", zeroline=False),
    )
    fig.update_xaxes(
        showspikes=True, spikecolor="#1B3A6B",
        spikesnap="cursor", spikemode="across", spikedash="dot", spikethickness=1,
    )
    fig.update_yaxes(showspikes=True, spikecolor="#E0E0E0", spikethickness=1)

    st.plotly_chart(fig, use_container_width=True)

    # ── Tabla forecast ────────────────────────────────────────────────────────
    st.markdown("#### Proyección mensual detallada")
    MESES = {1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
             7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"}
    df_fc = pd.DataFrame({
        "Mes":            [f"{MESES[m.month]} {m.year}" for m in meses_fc],
        "Proyección":     [f"${v:,.0f}" for v in fc_vals],
        "Escenario bajo": [f"${v:,.0f}" for v in ci_lower],
        "Escenario alto": [f"${v:,.0f}" for v in ci_upper],
    })
    st.dataframe(df_fc, use_container_width=True, hide_index=True)

    with st.expander("ℹ️ Metodología del forecast"):
        st.markdown(f"""
**Modelo:** Promedio ponderado exponencial de los últimos **{N_MESES} meses** + tendencia lineal.
**Intervalo de confianza:** ±1.5σ del histórico reciente.
Con ~{len(hist_serie)} meses de historia, el intervalo es amplio por diseño.
        """)
