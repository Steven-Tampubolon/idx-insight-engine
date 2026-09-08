# pages/2_🔍_Anomaly.py
import streamlit as st
import pandas as pd
import plotly.express as px
from data.fetcher    import get_all_companies
from core.anomaly    import detect_anomalies
from core.explainer  import explain_anomaly

st.set_page_config(
    page_title = "Anomaly Dashboard — IDX Insight Engine",
    page_icon  = "🔍",
    layout     = "wide",
)

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🔍 Anomaly Dashboard")
st.caption(
    "Saham IDX yang berperilaku berbeda dari median sub-sektornya · "
    "Semua kalkulasi dari cache lokal — **0 Sectors credits**"
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
METRIC_LABELS = {
    "forward_pe"     : "PE Ratio",
    "pb"             : "Price / Book",
    "roe"            : "Return on Equity",
    "dividend_yield" : "Dividend Yield",
}

with st.sidebar:
    st.header("⚙️ Filter Anomali")

    df_all = get_all_companies()

    # Pastikan kolom company_name selalu ada
    if "company_name" not in df_all.columns:
        df_all["company_name"] = df_all["symbol"]

    all_subsectors = sorted(df_all["sub_sector"].dropna().unique().tolist())

    selected_subsectors = st.multiselect(
        "Sub-sektor",
        options      = all_subsectors,
        default      = all_subsectors,
        placeholder  = "Pilih sub-sektor...",
    )

    threshold = st.slider(
        "Ambang anomali (z-score)",
        min_value = 1.0, max_value = 3.5,
        value     = 2.0, step      = 0.1,
        help      = "Perusahaan dengan |z-score| > nilai ini → flagged",
    )

    selected_metrics = st.multiselect(
        "Metrik yang dicek",
        options      = list(METRIC_LABELS.keys()),
        default      = list(METRIC_LABELS.keys()),
        format_func  = lambda x: METRIC_LABELS[x],
    )

    st.divider()
    st.markdown("**Cara pakai:**\n1. Atur filter\n2. Klik **Explain ✨** di tabel\n3. Baca narasi AI →")

# ── Guard ─────────────────────────────────────────────────────────────────────
if not selected_subsectors or not selected_metrics:
    st.warning("Pilih minimal satu sub-sektor dan satu metrik di sidebar.")
    st.stop()

# ── Hitung anomali (dari SQLite cache, 0 credits) ─────────────────────────────
df_in      = df_all[df_all["sub_sector"].isin(selected_subsectors)].copy()
df_scored  = detect_anomalies(df_in, metrics=selected_metrics, threshold=threshold)
df_anomaly = (
    df_scored[df_scored["is_anomaly"]]
    .sort_values("anomaly_score", ascending=False)
    .reset_index(drop=True)
)
df_normal  = df_scored[~df_scored["is_anomaly"]]

# ── Session state ─────────────────────────────────────────────────────────────
st.session_state.setdefault("selected_symbol", None)
st.session_state.setdefault("explanations", {})

# ── Metrics row ───────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total perusahaan",    len(df_scored))
c2.metric("Anomali terdeteksi",  len(df_anomaly))
c3.metric("Sub-sektor aktif",    len(selected_subsectors))
c4.metric("Anomaly rate",        f"{len(df_anomaly)/max(len(df_scored),1)*100:.1f}%")

st.divider()

# ── Scatter chart (full width) ────────────────────────────────────────────────
st.subheader("📊 Peta Anomali per Sub-sektor")

_plot_df       = df_scored.copy()
_plot_df["size_val"] = (_plot_df["anomaly_score"] + 0.5).clip(lower=0.5)

fig = px.scatter(
    _plot_df,
    x                    = "sub_sector",
    y                    = "anomaly_score",
    color                = "anomaly_score",
    size                 = "size_val",
    size_max             = 22,
    color_continuous_scale = [
        [0.0, "#94a3b8"],
        [0.4, "#f59e0b"],
        [1.0, "#ef4444"],
    ],
    hover_data           = {
        "symbol"        : True,
        "company_name"  : True,
        "anomaly_score" : ":.2f",
        "is_anomaly"    : True,
        "sub_sector"    : False,
        "size_val"      : False,
    },
    labels               = {
        "sub_sector"    : "",
        "anomaly_score" : "Anomaly Score",
        "company_name"  : "Perusahaan",
        "is_anomaly"    : "Anomali",
    },
    height               = 300,
)
fig.add_hline(
    y                    = threshold,
    line_dash            = "dash",
    line_color           = "#f59e0b",
    annotation_text      = f"Threshold z = {threshold}",
    annotation_position  = "top right",
)
fig.update_layout(
    xaxis_tickangle      = -25,
    coloraxis_showscale  = False,
    plot_bgcolor         = "rgba(0,0,0,0)",
    paper_bgcolor        = "rgba(0,0,0,0)",
    margin               = dict(l=0, r=0, t=10, b=60),
)
st.plotly_chart(fig, use_container_width=True)

st.divider()

# ── Two-column: tabel kiri | explainer kanan ──────────────────────────────────
left_col, right_col = st.columns([1, 1.1], gap="large")

# ─── LEFT: Tabel anomali ──────────────────────────────────────────────────────
with left_col:
    st.subheader(f"🚨 {len(df_anomaly)} Perusahaan Anomali")

    if df_anomaly.empty:
        st.success("✅ Tidak ada anomali pada setting ini — coba turunkan threshold.")
    else:
        for _, row in df_anomaly.iterrows():
            symbol  = row["symbol"]
            score   = row["anomaly_score"]
            flags   = row.get("anomaly_flags", [])
            name    = row.get("company_name", symbol)
            sub     = row.get("sub_sector", "—")

            badge      = "🔴" if score > 4 else "🟠" if score > 2.5 else "🟡"
            is_chosen  = st.session_state.selected_symbol == symbol

            with st.container(border=True):
                info_col, btn_col = st.columns([3, 1])

                with info_col:
                    prefix = "▶ " if is_chosen else ""
                    st.markdown(f"**{prefix}{badge} {name}**")
                    flag_str = " ".join(
                        f"`{METRIC_LABELS.get(f, f)}`" for f in flags
                    ) if flags else "—"
                    st.caption(
                        f"`{symbol}` · {sub} · "
                        f"Score **{score:.2f}** · {flag_str}"
                    )

                with btn_col:
                    if is_chosen:
                        st.button("✅ Dipilih", key=f"btn_{symbol}",
                                  use_container_width=True, disabled=True)
                    else:
                        if st.button("Explain ✨", key=f"btn_{symbol}",
                                     use_container_width=True):
                            st.session_state.selected_symbol = symbol
                            st.rerun()

    # Normal companies — collapsed
    with st.expander(f"📋 {len(df_normal)} perusahaan normal (tidak anomali)"):
        show_cols = ["symbol", "company_name", "sub_sector"] + [
            f"z_{m}" for m in selected_metrics
            if f"z_{m}" in df_normal.columns
        ]
        st.dataframe(
            df_normal[[c for c in show_cols if c in df_normal.columns]],
            use_container_width = True,
            hide_index          = True,
        )

# ─── RIGHT: Explainer ─────────────────────────────────────────────────────────
with right_col:
    st.subheader("🤖 Penjelasan AI")

    if st.session_state.selected_symbol is None:
        st.info("← Pilih perusahaan anomali di kiri, lalu klik **Explain ✨**")

    else:
        symbol = st.session_state.selected_symbol
        match  = df_anomaly[df_anomaly["symbol"] == symbol]

        if match.empty:
            st.warning(f"Data {symbol} tidak ditemukan di daftar anomali.")
            if st.button("← Reset"):
                st.session_state.selected_symbol = None
                st.rerun()
        else:
            row_data = match.iloc[0].to_dict()
            name     = row_data.get("company_name", symbol)
            sub      = row_data.get("sub_sector", "—")
            flags    = row_data.get("anomaly_flags", [])
            score    = row_data["anomaly_score"]

            # Header perusahaan
            st.markdown(f"### {name}")
            st.caption(f"`{symbol}` · {sub} · Anomaly Score: **{score:.2f}**")

            # Z-score cards per metrik yang flagged
            if flags:
                z_cols = st.columns(len(flags))
                for i, m in enumerate(flags):
                    z    = row_data.get(f"z_{m}", 0)
                    dire = "↑ jauh di atas" if z > 0 else "↓ jauh di bawah"
                    z_cols[i].metric(
                        label       = METRIC_LABELS.get(m, m),
                        value       = f"z = {z:+.2f}",
                        delta       = f"{dire} median",
                        delta_color = "inverse",
                    )

            st.divider()

            # Generate atau load dari session cache (Groq, gratis)
            if symbol not in st.session_state.explanations:
                with st.spinner("Groq menganalisis anomali... ⏳"):
                    try:
                        narasi = explain_anomaly(symbol, row_data)
                        st.session_state.explanations[symbol] = narasi
                    except Exception as e:
                        st.error(f"Gagal memanggil Groq: {e}")
                        st.stop()

            st.markdown(st.session_state.explanations[symbol])

            st.caption(
                "⚠️ Analisis statistik + interpretasi AI — "
                "bukan rekomendasi investasi."
            )
            st.divider()

            b1, b2 = st.columns(2)
            with b1:
                if st.button("← Pilih lain", use_container_width=True):
                    st.session_state.selected_symbol = None
                    st.rerun()
            with b2:
                if st.button("🔄 Refresh narasi", use_container_width=True,
                             help="Hapus cache dan generate ulang dari Groq"):
                    st.session_state.explanations.pop(symbol, None)
                    st.rerun()