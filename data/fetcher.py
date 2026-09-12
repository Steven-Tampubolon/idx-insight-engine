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

def _normalize_subsector(name):
    """Samakan konvensi nama sub-sektor: 'Banks' -> 'banks', 'Oil, Gas & Coal' -> 'oil-gas-coal'.

    company_reports mengembalikan pretty name di overview.sub_sector,
    sedangkan companies table memakai slug. Tanpa normalisasi, peer group
    di anomaly detection terfragmentasi jadi dua grup terpisah.
    """
    if not name:
        return name
    return (name.strip().lower()
                 .replace(",", "")
                 .replace(" & ", "-")
                 .replace("&", "-")
                 .replace(" ", "-"))

def _extract_metrics(data: dict) -> dict:
    """Ekstrak metrik dari response company/report/{symbol}/ v2.

    Defensif: mencoba beberapa path kemungkinan untuk ROE dan dividend yield,
    karena struktur response v2 bisa bervariasi antar endpoint/versi.
    Mengembalikan None (bukan exception) jika data tidak ditemukan.
    """
    data       = data or {}
    overview   = data.get("overview",   {}) or {}
    valuation  = data.get("valuation",  {}) or {}
    financials = data.get("financials", {}) or {}
    dividend   = data.get("dividend",   {}) or {}

    # Ambil historical_valuation tahun terbaru
    hist = valuation.get("historical_valuation", []) or []
    latest_hist = {}
    if isinstance(hist, list) and hist:
        latest_hist = sorted(hist, key=lambda x: x.get("year", 0), reverse=True)[0]

    # Ambil historical_financial_ratio tahun terbaru
    fin_ratios = financials.get("historical_financial_ratio", []) or []
    latest_ratio = {}
    if isinstance(fin_ratios, list) and fin_ratios:
        latest_ratio = sorted(fin_ratios, key=lambda x: x.get("year", 0), reverse=True)[0]

    # ── ROE: cari dari berbagai kemungkinan path ─────────────────────────
    roe = (
        # Path 1: financials.historical_financial_ratio[].profitability.roe
        (latest_ratio.get("profitability") or {}).get("roe")
        # Path 2: financials.historical_financial_ratio[].roe (flat)
        or latest_ratio.get("roe")
        # Path 3: financials.roe (flat di root financials)
        or financials.get("roe")
        # Path 4: overview.roe (kadang ada di overview)
        or overview.get("roe")
    )

    # ── Dividend yield: cari dari berbagai kemungkinan path ───────────────
    div_yield = (
        # Path 1: dividend.yield_ttm
        dividend.get("yield_ttm")
        # Path 2: dividend.yield (tanpa _ttm)
        or dividend.get("yield")
        # Path 3: overview.dividend_yield
        or overview.get("dividend_yield")
        # Path 4: historical valuation
        or latest_hist.get("yield")
    )

    return {
        "company_name"    : data.get("company_name"),
        "sub_sector"      : overview.get("sub_sector"),
        "market_cap"      : overview.get("market_cap"),
        "last_close_price": overview.get("last_close_price"),
        "daily_change"    : overview.get("daily_close_change"),
        "forward_pe"      : valuation.get("forward_pe"),
        "pe_ttm"          : latest_hist.get("pe"),
        "pb"              : latest_hist.get("pb"),
        "ps"              : latest_hist.get("ps"),
        "pb_peer_avg"     : latest_hist.get("pb_peer_avg"),
        "pe_peer_avg"     : latest_hist.get("pe_peer_avg"),
        "roe"             : roe,
        "dividend_yield"  : div_yield,
    }

# ── Public API ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_all_companies() -> pd.DataFrame:
    """Baca semua company dari SQLite cache.

    Prioritas nilai metrik:
      1. company_reports (paling lengkap, di-_extract_metrics)
      2. companies.data screener (roe_ttm / yield_ttm / pe_ttm / pb_mrq)
    """
    try:
        conn = _conn()
        rows = conn.execute(
            "SELECT c.symbol, c.subsector, c.data, cr.data as report_data "
            "FROM companies c "
            "LEFT JOIN company_reports cr ON c.symbol = cr.symbol"
        ).fetchall()
        conn.close()

        records = []
        corrupt = []
        for r in rows:
            try:
                base = {
                    "symbol"    : r[0],
                    "sub_sector": r[1],
                }
                # Data dasar dari screener
                raw = json.loads(r[2])
                base["company_name"] = raw.get("company_name", r[0])

                # Extract semua metrik yang mungkin ada di screener data
                # (tersedia jika companies di-fetch dengan order_by tertentu,
                #  misal order_by=-roe_ttm, atau hasil get_top_from_api)
                screener_roe   = raw.get("roe_ttm")   or raw.get("roe")
                screener_yield = raw.get("yield_ttm") or raw.get("dividend_yield")
                screener_pe    = raw.get("pe_ttm")    or raw.get("pe")
                screener_pb    = raw.get("pb_mrq")    or raw.get("pb")

                # Set sebagai nilai dasar — di-overwrite oleh company_report
                if screener_roe   is not None: base["roe"]            = screener_roe
                if screener_yield is not None: base["dividend_yield"] = screener_yield
                if screener_pe    is not None: base["pe_ttm"]         = screener_pe
                if screener_pb    is not None: base["pb"]             = screener_pb

                # Merge metrik dari company_report kalau ada
                if r[3]:
                    report  = json.loads(r[3])
                    metrics = _extract_metrics(report)
                    base.update({k: v for k, v in metrics.items() if v is not None})

                # Samakan konvensi nama sub-sektor (pretty vs slug)
                base["sub_sector"] = _normalize_subsector(base.get("sub_sector"))

                records.append(base)
            except Exception:
                # Satu row corrupt tidak boleh membunuh seluruh dataset
                corrupt.append(r[0])
                continue
        if corrupt:
            print(f"⚠️  {len(corrupt)} row corrupt di-skip: {corrupt[:5]}...")

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
    Untuk screener — baca dari SQLite.
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
            
            # Samakan konvensi nama sub-sektor (pretty vs slug)
            base["sub_sector"] = _normalize_subsector(base.get("sub_sector"))

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
            params={"sections": "overview,valuation,financials,dividend"},  # ← tambah sections
            timeout=10
        )
        r.raise_for_status()
        data = r.json()

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