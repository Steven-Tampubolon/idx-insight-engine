# pages/1_📊_Screener.py
import streamlit as st

# Import fresh setiap kali page di-load
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from data.fetcher  import get_all_companies
from core.screener import build_score

st.set_page_config(page_title="Screener — IDX Insight Engine",
                   page_icon="📊", layout="wide")

st.title("📊 Custom Stock Screener")
st.caption("Buat formula scoring sendiri · Data dari SQLite cache")

# ── Konfigurasi metrik ────────────────────────────────────────────────────────
# (label, default_lower_is_better, default_weight)
METRICS = {
    "forward_pe"     : ("Forward PE",         True,  70),
    "pe_ttm"         : ("PE (TTM)",           True,  65),
    "pb"             : ("Price / Book",       True,  60),
    "ps"             : ("Price / Sales",      True,  40),
    "roe"            : ("ROE (%)",            False, 80),
    "dividend_yield" : ("Dividend Yield (%)", False, 50),
    "market_cap"     : ("Market Cap",         False, 30),
}

# ── Load data ─────────────────────────────────────────────────────────────────
df_raw = get_all_companies()

if df_raw.empty:
    st.error("⚠️ Cache kosong — jalankan `python -m data.init_cache` terlebih dahulu.")
    st.stop()

if "company_name" not in df_raw.columns:
    df_raw["company_name"] = df_raw["symbol"]

all_subs    = sorted(df_raw["sub_sector"].dropna().unique())
avail_mets  = [m for m in METRICS if m in df_raw.columns]

# ── Sidebar: Formula Builder ──────────────────────────────────────────────────
with st.sidebar:
    st.header("🧮 Formula Builder")

    # ── Preset strategi ──────────────────────────────────────────────────────
    PRESETS = {
        "💎 Value Investing" : {"forward_pe": 70, "pb": 60, "roe": 80},
        "💰 Dividend Focus"  : {"dividend_yield": 80, "forward_pe": 50, "pb": 40},
        "📈 Quality Growth"  : {"roe": 80, "ps": 50, "forward_pe": 60},
    }
    st.caption("Quick start — pilih preset atau atur manual:")
    p_cols = st.columns(3)
    for i, (label, weights_preset) in enumerate(PRESETS.items()):
        if p_cols[i].button(label, use_container_width=True, key=f"preset_{i}"):
            for metric, val in weights_preset.items():
                st.session_state[f"w_{metric}"] = val
            st.session_state["sel_metrics_preset"] = list(weights_preset.keys())
    st.divider()
    # ── End preset ───────────────────────────────────────────────────────────

    sel_subs = st.multiselect("Sub-sektor", all_subs,
                              default=list(all_subs), placeholder="Semua")

    default_metrics = st.session_state.get("sel_metrics_preset", avail_mets[:3])
    default_metrics = [m for m in default_metrics if m in avail_mets] or avail_mets[:3]

    sel_metrics = st.multiselect(
        "Metrik formula",
        avail_mets,
        default=default_metrics,
        format_func=lambda x: METRICS[x][0],
    )

    weights = {}
    inverts = {}
    if sel_metrics:
        st.markdown("---")
        st.markdown("**Bobot & Arah:**")
        for m in sel_metrics:
            label, def_inv, def_w = METRICS[m]
            col_a, col_b = st.columns([3, 2])
            weights[m] = col_a.slider(
                label, 0, 100, def_w,
                key=f"w_{m}", label_visibility="collapsed"
            )
            col_a.caption(f"{label} — bobot **{weights[m]}**")
            inverts[m] = col_b.checkbox("⬇ Lower better", def_inv, key=f"inv_{m}")

    st.markdown("---")
    norm_method = st.radio(
        "Normalisasi", ["minmax", "zscore"],
        format_func=lambda x: "Min-Max (0–1)" if x == "minmax" else "Z-Score",
    )
    top_n = st.slider("Tampilkan top N", 10, 50, 20, 5)

# ── Guard ─────────────────────────────────────────────────────────────────────
if not sel_subs or not sel_metrics:
    st.info("Pilih minimal satu sub-sektor dan satu metrik di sidebar.")
    st.stop()

if not any(weights.values()):
    st.warning("Semua bobot 0 — atur minimal satu bobot > 0.")
    st.stop()

# ── Hitung score ──────────────────────────────────────────────────────────────
df_f        = df_raw[df_raw["sub_sector"].isin(sel_subs)].copy()
invert_list = [m for m, v in inverts.items() if v]
df_scored   = build_score(df_f, sel_metrics, weights, norm_method, invert_list)
df_scored["rank"] = df_scored["score"].rank(ascending=False, method="first").fillna(0).astype(int)
df_top      = df_scored.nsmallest(top_n, "rank").reset_index(drop=True)

# ── Metric cards ──────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
valid = df_scored[df_scored["score"].notna()]
if valid.empty:
    st.warning("Tidak ada data metrik untuk sub-sektor yang dipilih.")
    st.stop()
best = valid.loc[valid["score"].idxmax()]
c1.metric("Perusahaan dianalisis", len(df_scored))
c2.metric("Sub-sektor aktif",       len(sel_subs))
c3.metric("🥇 Top company",  best.get("company_name", best["symbol"]))
c4.metric("Top score",             f"{best['score']:.4f}")

st.divider()

# ── Layout: chart kiri | detail kanan ────────────────────────────────────────
chart_col, detail_col = st.columns([1.4, 1], gap="large")

# ─── Ranking bar chart ─────────────────────────────────────────────────────
with chart_col:
    st.subheader(f"🏆 Top {top_n} Ranking")
    df_top["display"] = df_top.apply(
        lambda r: f"{r.get('company_name', r['symbol'])} ({r['symbol']})", axis=1
    )
    fig = px.bar(
        df_top.sort_values("score"),
        x="score", y="display", orientation="h",
        color="score",
        color_continuous_scale=[[0,"#ef4444"],[0.5,"#f59e0b"],[1,"#22c55e"]],
        height=max(300, top_n * 24),
        labels={"score": "Score", "display": ""},
        hover_data={
            k: True for k in ["sub_sector","score"] if k in df_top.columns
        } | {"display": False},
    )
    fig.update_layout(
        coloraxis_showscale=False,
        margin=dict(l=0, r=40, t=10, b=20),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)

# ─── Detail perusahaan ─────────────────────────────────────────────────────
with detail_col:
    st.subheader("🔍 Detail Perusahaan")
    ranked_symbols = df_scored.sort_values("rank")["symbol"].tolist()
    sel_sym = st.selectbox("Pilih perusahaan", ranked_symbols)
    row     = df_scored[df_scored["symbol"] == sel_sym].iloc[0]

    # Kontribusi bobot (formula weight breakdown)
    total_w = sum(weights.values()) or 1
    contribs = {METRICS[m][0]: round(weights[m] / total_w * 100, 1)
                for m in sel_metrics}

    fig2 = go.Figure(go.Bar(
        x=list(contribs.values()),
        y=list(contribs.keys()),
        orientation="h",
        marker_color="#6366f1",
        text=[f"{v:.0f}%" for v in contribs.values()],
        textposition="outside",
    ))
    fig2.update_layout(
        title="Bobot formula (%)",
        height=30 + 50 * len(sel_metrics),
        margin=dict(l=0, r=60, t=35, b=0),
        xaxis_range=[0, 105],
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.markdown(f"**Rank #{int(row['rank'])} · Score: `{row['score']:.4f}`**")
    for m in sel_metrics:
        val = row.get(m)
        if val is not None and not pd.isna(val):
            direction = "⬇ lower better" if inverts.get(m) else "⬆ higher better"
            st.caption(f"{METRICS[m][0]}: **{val:.2f}** · {direction}")

st.divider()

# ── Full ranked table ─────────────────────────────────────────────────────────
st.subheader("📋 Semua Perusahaan — Ranked")

show_cols = ["rank","symbol","company_name","sub_sector","score"] + sel_metrics
disp_cols = [c for c in show_cols if c in df_scored.columns]
df_disp   = df_scored.sort_values("rank")[disp_cols].reset_index(drop=True)

col_cfg = {
    "rank"          : st.column_config.NumberColumn("🏅", format="%d", width="small"),
    "score"         : st.column_config.ProgressColumn("Score", format="%.4f", min_value=0, max_value=1),
    "symbol"        : st.column_config.TextColumn("Kode"),
    "company_name"  : st.column_config.TextColumn("Perusahaan"),
    "sub_sector"    : st.column_config.TextColumn("Sub-sektor"),
    "forward_pe"    : st.column_config.NumberColumn("PE",    format="%.1f"),
    "pb"            : st.column_config.NumberColumn("P/B",   format="%.2f"),
    "roe"           : st.column_config.NumberColumn("ROE (%)", format="%.1f%%", help="Return on Equity — kosong jika data belum tersedia"),
    "dividend_yield": st.column_config.NumberColumn("Div. Yield", format="%.2f%%", help="Dividend Yield — kosong jika data belum tersedia"),
    "market_cap"    : st.column_config.NumberColumn("Mkt Cap"),
}

st.dataframe(df_disp, column_config=col_cfg,
             use_container_width=True, hide_index=True, height=420)

st.download_button(
    "⬇ Download CSV", df_disp.to_csv(index=False),
    file_name="idx_screener.csv", mime="text/csv"
)