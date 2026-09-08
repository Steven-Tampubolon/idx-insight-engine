# data/fetcher.py
"""
Data fetcher untuk IDX Insight Engine.
Semua query ke Sectors API v2, dengan SQLite cache (lazy caching).
"""
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import streamlit as st

# ── Config ─────────────────────────────────────────────────────────────────────
API_KEY = st.secrets.get("SECTORS_API_KEY", os.environ.get("SECTORS_API_KEY", ""))
BASE    = "https://api.sectors.app/v2"   # ← v2
HDR     = {"Authorization": API_KEY}
DB_PATH = Path("data/cache.db")

# Metric field mapping: nama pendek → nama field v2
METRIC_FIELD_MAP = {
    "roe":            "roe_ttm",
    "forward_pe":     "forward_pe",
    "pe":             "pe_ttm",
    "pb":             "pb_mrq",
    "dividend_yield": "yield_ttm",
}

# Side-effect log untuk ditampilkan di UI
_tool_calls_log: list[str] = []

# ── Helpers ────────────────────────────────────────────────────────────────────
def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)

def _unwrap_v2(raw) -> list:
    """v2 membungkus hasil dalam {'results': [...], 'pagination': {...}}."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        if "results" in raw and isinstance(raw["results"], list):
            return raw["results"]
        for val in raw.values():
            if isinstance(val, list):
                return val
    return []

def _get_nested(data, *keys):
    """Cari nilai dari nested dict/list berdasarkan beberapa kandidat key."""
    if isinstance(data, dict):
        for k, v in data.items():
            if k in keys and v is not None:
                return v
            found = _get_nested(v, *keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _get_nested(item, *keys)
            if found is not None:
                return found
    return None

def _extract_metrics(data: dict) -> dict:
    """Ekstrak metrik dari response company/report/{symbol}/ v2."""
    overview   = data.get("overview",   {}) or {}
    valuation  = data.get("valuation",  {}) or {}

    # Ambil historical_valuation tahun terbaru
    hist = valuation.get("historical_valuation", []) or []
    latest_hist = {}
    if isinstance(hist, list) and hist:
        # Sort by year descending, ambil yang terbaru
        latest_hist = sorted(hist, key=lambda x: x.get("year", 0), reverse=True)[0]

    return {
        "company_name"     : data.get("company_name"),
        "sub_sector"       : overview.get("sub_sector"),
        "market_cap"       : overview.get("market_cap"),
        "last_close_price" : overview.get("last_close_price"),
        "daily_change"     : overview.get("daily_change"),
        "forward_pe"       : valuation.get("forward_pe"),
        "pe_ttm"           : latest_hist.get("pe"),
        "pb"               : latest_hist.get("pb"),
        "ps"               : latest_hist.get("ps"),
        "pb_peer_avg"      : latest_hist.get("pb_peer_avg"),
        "pe_peer_avg"      : latest_hist.get("pe_peer_avg"),
        # roe & dividend_yield tidak tersedia di sections ini — hemat credits
        "roe"              : None,
        "dividend_yield"   : None,
    }

# ── Public API ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_all_companies() -> pd.DataFrame:
    """Baca semua company dari SQLite cache — 0 Sectors credits."""
    try:
        conn  = _conn()
        rows  = conn.execute(
            "SELECT c.symbol, c.subsector, c.data, cr.data as report_data "
            "FROM companies c "
            "LEFT JOIN company_reports cr ON c.symbol = cr.symbol"
        ).fetchall()
        conn.close()
        
        records = []
        for r in rows:
            base = {
                "symbol"    : r[0],
                "sub_sector": r[1],
            }
            # Data dasar dari screener
            raw = json.loads(r[2])
            base["company_name"] = raw.get("company_name", r[0])
            
            # Merge metrik dari company_report kalau ada
            if r[3]:
                report  = json.loads(r[3])
                metrics = _extract_metrics(report)
                base.update(metrics)
            
            records.append(base)
        
        if not records:
            return pd.DataFrame()
        
        df = pd.DataFrame(records)
        num_cols = ["forward_pe", "pe_ttm", "pb", "roe", "dividend_yield", "market_cap"]
        for col in num_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_companies_with_metrics(subsectors: list = None) -> pd.DataFrame:
    """
    Ambil data perusahaan dari cache + join dengan data metrik dari company_reports.
    Kalau company_reports kosong, fetch dari Sectors API (lazy, per-company).
    Untuk screener — baca dari SQLite, 0 credits.
    """
    try:
        conn = _conn()
        
        # Ambil data companies dasar
        if subsectors:
            placeholders = ",".join("?" * len(subsectors))
            rows = conn.execute(
                f"SELECT symbol, subsector, data FROM companies WHERE subsector IN ({placeholders})",
                subsectors
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT symbol, subsector, data FROM companies"
            ).fetchall()
        
        if not rows:
            conn.close()
            return pd.DataFrame()

        records = []
        for r in rows:
            base = {"symbol": r[0], "sub_sector": r[1]}
            # Data dari screener endpoint (hanya symbol + company_name)
            raw = json.loads(r[2])
            base["company_name"] = raw.get("company_name", r[0])
            
            # Cek apakah ada data metrik di company_reports
            report_row = conn.execute(
                "SELECT data FROM company_reports WHERE symbol=?", (r[0],)
            ).fetchone()
            
            if report_row:
                report = json.loads(report_row[0])
                metrics = _extract_metrics(report)
                base.update(metrics)
            
            records.append(base)
        
        conn.close()
        df = pd.DataFrame(records)
        
        # Konversi kolom numerik
        num_cols = ["forward_pe", "pe_ttm", "pb", "roe", "dividend_yield", "market_cap"]
        for col in num_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        
        return df
    except Exception:
        return pd.DataFrame()

def get_company_details(symbol: str) -> dict:
    symbol = symbol.upper().replace(".JK", "").strip()

    # 1. Cek company_reports DULU — ini yang punya metrik lengkap
    try:
        conn = _conn()
        row  = conn.execute(
            "SELECT data FROM company_reports WHERE symbol=?", (symbol,)
        ).fetchone()
        conn.close()
        if row:
            return _extract_metrics(json.loads(row[0]))
    except Exception:
        pass

    # 2. Cek companies table — hanya punya symbol + company_name, skip extract
    # (tidak berguna untuk metrik, langsung ke API)

    # 3. Fallback: hit Sectors API v2
    if not API_KEY:
        return {"error": "SECTORS_API_KEY tidak ditemukan"}
    try:
        r = requests.get(
            f"{BASE}/company/report/{symbol}/",
            headers=HDR,
            params={"sections": "overview,valuation"},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()

        # Simpan ke company_reports agar next time dari cache
        conn = _conn()
        conn.execute(
            "INSERT OR REPLACE INTO company_reports (symbol, data) VALUES (?,?)",
            (symbol, json.dumps(data))
        )
        conn.commit()
        conn.close()
        time.sleep(0.3)
        return _extract_metrics(data)
    except Exception as e:
        return {"error": str(e)}

def get_top_from_api(metric: str, subsector: str = "", n: int = 5) -> str:
    """
    Fetch top N perusahaan berdasarkan metrik dari Sectors API v2.
    Dipakai oleh agent — hasilnya juga di-cache ke SQLite.
    """
    order_field = METRIC_FIELD_MAP.get(metric, metric)
    params: dict = {"order_by": f"-{order_field}", "limit": n}
    if subsector:
        params["where"] = f"sub_sector='{subsector}'"

    if not API_KEY:
        return json.dumps({"error": "SECTORS_API_KEY tidak ditemukan"})
    try:
        r = requests.get(f"{BASE}/companies/", headers=HDR, params=params, timeout=15)
        r.raise_for_status()
        companies = _unwrap_v2(r.json())

        # Cache semua hasilnya sekalian
        conn = _conn()
        for c in companies:
            sym = c.get("symbol") or c.get("ticker") or c.get("stock_code")
            if sym:
                conn.execute(
                    "INSERT OR REPLACE INTO companies (symbol, subsector, data) VALUES (?,?,?)",
                    (sym, c.get("sub_sector", subsector), json.dumps(c))
                )
        conn.commit()
        conn.close()
        time.sleep(0.3)

        summary = [
            {"symbol": c.get("symbol", "").replace(".JK", ""), 
            "company_name": c.get("company_name", "")}
            for c in companies[:5]   # ← max 5 hasil
            if isinstance(c, dict) and c.get("symbol")
        ]
        return json.dumps(summary, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})