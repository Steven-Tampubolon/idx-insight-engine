import sqlite3, json, requests, os
import pandas as pd
import streamlit as st
from pathlib import Path

API_KEY = st.secrets.get("SECTORS_API_KEY", os.environ.get("SECTORS_API_KEY"))
BASE    = "https://api.sectors.app/v1"
HDR     = {"Authorization": API_KEY}
DB_PATH = Path("data/cache.db")

def _conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)

@st.cache_data(ttl=3600)
def get_all_companies() -> pd.DataFrame:
    """Baca SEMUA company dari SQLite — 0 credits."""
    conn = _conn()
    rows = conn.execute("SELECT symbol, subsector, data FROM companies").fetchall()
    conn.close()
    records = [{"symbol": r[0], "sub_sector": r[1], **json.loads(r[2])} for r in rows]
    return pd.DataFrame(records)

def get_company_details(symbol: str) -> dict:
    """
    Cek company_reports cache dulu. Baru hit API jika belum ada.
    Lazy caching: setiap company hanya di-fetch SEKALI (~7 credits),
    setelah itu gratis selamanya.
    """
    conn = _conn()
    row  = conn.execute(
        "SELECT data FROM company_reports WHERE symbol=?", (symbol,)
    ).fetchone()

    if row:
        conn.close()
        return json.loads(row[0])   # 0 credits ✓

    # Fallback — hit API dan langsung cache
    r    = requests.get(f"{BASE}/companies/{symbol}/", headers=HDR, timeout=10)
    data = r.json()
    conn.execute(
        "INSERT OR REPLACE INTO company_reports (symbol, data) VALUES (?,?)",
        (symbol, json.dumps(data))
    )
    conn.commit()
    conn.close()
    return data   # ~7 credits, tapi sekali saja