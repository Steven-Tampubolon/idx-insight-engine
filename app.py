# app.py
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="IDX Insight Engine", page_icon="📊", layout="wide")

if not Path("data/cache.db").exists():
    st.error(
        "⚠️ **Cache belum dibuat.** "
        "Jalankan `python -m data.init_cache` di terminal untuk mengambil data "
        "dari **Sectors REST API** (~75–150 credits), lalu jalankan ulang app ini."
    )
    st.stop()

st.title("📊 IDX Insight Engine")
st.caption("Pilih halaman di sidebar untuk mulai menganalisis saham IDX.")