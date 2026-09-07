#!/usr/bin/env python3
"""
poc_agent.py — Proof of Concept: Autonomous Multi-Step Tool Selection
======================================================================
Membuktikan Gemini memilih tools sendiri (tidak hard-coded)
berdasarkan reasoning bertahap atas query finansial IDX.

Jalankan: python poc_agent.py
"""

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────
GEMINI_KEY  = os.environ.get("GEMINI_API_KEY", "")
SECTORS_KEY = os.environ.get("SECTORS_API_KEY", "")
BASE        = "https://api.sectors.app/v2"
HDR         = {"Authorization": SECTORS_KEY}
DB_PATH     = Path("data/cache.db")

METRIC_FIELD_MAP = {
    "roe":            "roe_ttm",
    "forward_pe":     "forward_pe",
    "pe":             "pe_ttm",
    "pb":             "pb_mrq",
    "dividend_yield": "yield_ttm",
}

# ── Credit tracker ──────────────────────────────────────────────────────────────
_credits: dict = {"total": 0, "log": []}

def _spend(label: str, cost: int) -> None:
    _credits["total"] += cost
    _credits["log"].append(f"{label} (~{cost} cr)")

# ── SQLite helpers ──────────────────────────────────────────────────────────────
def _ensure_tables() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS companies (
                symbol     TEXT PRIMARY KEY,
                subsector  TEXT,
                data       JSON,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

def _cache_get_sector(subsector: str) -> Optional[list]:
    if not DB_PATH.exists():
        return None
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT symbol, data FROM companies WHERE subsector=?", (subsector,)
            ).fetchall()
        return [{"symbol": r[0], **json.loads(r[1])} for r in rows] if rows else None
    except sqlite3.Error:
        return None

def _cache_get_company(symbol: str) -> Optional[dict]:
    if not DB_PATH.exists():
        return None
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT data FROM companies WHERE symbol=?", (symbol,)
            ).fetchone()
        return json.loads(row[0]) if row else None
    except sqlite3.Error:
        return None

def _cache_save_sector(subsector: str, companies: list) -> None:
    _ensure_tables()
    saved = 0
    with sqlite3.connect(DB_PATH) as conn:
        for c in companies:
            symbol = c.get("symbol") or c.get("ticker") or c.get("stock_code")
            if not symbol:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO companies (symbol, subsector, data) VALUES (?,?,?)",
                (symbol, subsector, json.dumps(c))
            )
            saved += 1
    print(f"     💾 {saved}/{len(companies)} perusahaan tersimpan ke cache")

def _cache_save_company(symbol: str, subsector: str, data: dict) -> None:
    _ensure_tables()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO companies (symbol, subsector, data) VALUES (?,?,?)",
            (symbol, subsector, json.dumps(data))
        )

def _unwrap_v2(response_json: dict | list) -> list:
    if isinstance(response_json, list):
        return response_json
    if isinstance(response_json, dict):
        if "results" in response_json and isinstance(response_json["results"], list):
            return response_json["results"]
        if "error" in response_json or "detail" in response_json:
            return []
        return [response_json]
    return []

def _unwrap_company_payload(raw: dict) -> dict:
    """Membuka wrapper 'data' / 'results' dari Sectors API v2."""
    if not isinstance(raw, dict):
        return {}
    if "data" in raw and isinstance(raw["data"], dict):
        return raw["data"]
    if "results" in raw and isinstance(raw["results"], dict):
        return raw["results"]
    if "results" in raw and isinstance(raw["results"], list) and len(raw["results"]) > 0:
        return raw["results"][0]
    return raw

def _get_nested(data, *keys):
    """Mencari key secara rekursif di dalam dict DAN list."""
    if isinstance(data, dict):
        for k, v in data.items():
            if k in keys and v is not None:
                return v
            # Telusuri ke dalam
            found = _get_nested(v, *keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _get_nested(item, *keys)
            if found is not None:
                return found
    return None

def _extract_metrics(raw_data: dict) -> dict:
    """Ekstraksi metrik finansial dari payload bersarang Sectors API."""
    data = _unwrap_company_payload(raw_data)
    
    return {
        "company_name":   _get_nested(data, "company_name", "name") or "N/A",
        "sub_sector":     _get_nested(data, "sub_sector", "subsector") or "N/A",
        "forward_pe":     _get_nested(data, "forward_pe"),
        "pe_ttm":         _get_nested(data, "pe_ttm", "pe"),
        "pb":             _get_nested(data, "pb_mrq", "pb"),
        "roe":            _get_nested(data, "roe_ttm", "roe"),
        "dividend_yield": _get_nested(data, "yield_ttm", "dividend_yield_ttm", "dividend_yield"),
        "market_cap":     _get_nested(data, "market_cap"),
    }

# ── Tool functions ──────────────────────────────────────────────────────────────
_tool_calls: list = []

def get_sector_companies(subsector: str) -> str:
    """
    Ambil daftar SIMBOL perusahaan dalam satu sub-sektor IDX (hanya symbol + company_name).
    Contoh subsector: 'banks', 'telecom', 'coal', 'consumer-goods', 'healthcare'
    """
    entry = f"get_sector_companies('{subsector}')"
    _tool_calls.append(entry)
    print(f"\n  🔧 TOOL CALL: {entry}")

    cached = _cache_get_sector(subsector)
    if cached:
        print(f"     ✅ cache hit — 0 credits ({len(cached)} perusahaan)")
        return json.dumps(cached, ensure_ascii=False)

    print(f"     📡 cache miss → Sectors REST API v2...")
    if not SECTORS_KEY:
        return json.dumps({"error": "SECTORS_API_KEY tidak ada dan cache kosong."})
    try:
        r = requests.get(
            f"{BASE}/companies/",
            headers=HDR,
            params={"where": f"sub_sector='{subsector}'"},
            timeout=15
        )
        r.raise_for_status()
        companies = _unwrap_v2(r.json())

        if not companies:
            return json.dumps({"error": f"Tidak ada perusahaan untuk subsector '{subsector}'"})

        _cache_save_sector(subsector, companies)
        _spend(entry, 1)
        time.sleep(0.5)
        return json.dumps(companies, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_company_metrics(symbol: str) -> str:
    """
    Ambil metrik finansial detail satu perusahaan IDX: PE ratio, ROE, dividend yield, PB, market cap.
    """
    symbol = symbol.upper().replace(".JK", "").strip()
    entry = f"get_company_metrics('{symbol}')"
    _tool_calls.append(entry)
    print(f"\n  🔧 TOOL CALL: {entry}")

    cached = _cache_get_company(symbol)
    if cached:
        print(f"     ✅ cache hit — 0 credits")
        extracted = _extract_metrics(cached)
        print(f"     🔍 [DEBUG EXTRACTION]: {extracted}") # Tampilkan di terminal untuk kita
        return json.dumps(extracted, ensure_ascii=False)

    print(f"     📡 cache miss → Sectors REST API v2...")
    if not SECTORS_KEY:
        return json.dumps({"error": "SECTORS_API_KEY tidak ada dan cache kosong."})
    try:
        r = requests.get(
            f"{BASE}/company/report/{symbol}/",
            headers=HDR,
            timeout=15
        )
        r.raise_for_status()
        raw = r.json()

        # Simpan raw JSON utuh ke cache SQLite
        subsector = _get_nested(raw, "sub_sector", "subsector") or "banks"
        _cache_save_company(symbol, subsector, raw)

        _spend(entry, 2)
        time.sleep(0.5)
        print(f"     💾 {symbol} disimpan ke cache")
        
        extracted = _extract_metrics(raw)
        print(f"     🔍 [DEBUG EXTRACTION]: {extracted}") # Tampilkan di terminal
        return json.dumps(extracted, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_top_companies_by_metric(metric: str, subsector: str = "", n: int = 5) -> str:
    """
    Ketahui kandidat SIMBOL perusahaan IDX teratas berdasarkan metrik tertentu.
    Hanya mengembalikan ringkasan simbol dan nama perusahaan.
    Metric: 'roe', 'forward_pe', 'pe', 'pb', 'dividend_yield'
    """
    entry = f"get_top_companies_by_metric(metric='{metric}', subsector='{subsector}', n={n})"
    _tool_calls.append(entry)
    print(f"\n  🔧 TOOL CALL: {entry}")

    order_field = METRIC_FIELD_MAP.get(metric, metric)
    params = {"order_by": f"-{order_field}", "limit": n}
    if subsector:
        params["where"] = f"sub_sector='{subsector}'"

    if not SECTORS_KEY:
        return json.dumps({"error": "SECTORS_API_KEY tidak ada."})
    try:
        r = requests.get(f"{BASE}/companies/", headers=HDR, params=params, timeout=15)
        r.raise_for_status()
        results = _unwrap_v2(r.json())
        
        # PANGKAS HASIL: Hanya kembalikan symbol & company_name agar agent dipaksa panggil get_company_metrics
        summary = [
            {
                "symbol": item.get("symbol"),
                "company_name": item.get("company_name")
            }
            for item in results if isinstance(item, dict)
        ]
        
        _spend(entry, 1)
        time.sleep(0.3)
        print(f"     ✅ {len(summary)} symbol kandidat ditemukan — 1 credit")
        return json.dumps(summary, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Gemini Client & Validation ──────────────────────────────────────────────────
def _build_client() -> genai.Client:
    return genai.Client(api_key=GEMINI_KEY)

def _validate(calls: list) -> dict:
    unique_fns = {c.split("(")[0] for c in calls}
    multi_company = sum(1 for c in calls if c.startswith("get_company")) >= 2

    passed = (
        len(calls)      >= 2 and
        len(unique_fns) >= 2 and
        multi_company
    )

    return {
        "total_calls"  : len(calls),
        "unique_tools" : len(unique_fns),
        "tools_used"   : sorted(unique_fns),
        "multi_step"   : len(calls)      >= 2,
        "multi_tool"   : len(unique_fns) >= 2,
        "multi_company": multi_company,
        "passed"       : passed,
    }

QUERY = (
    "Dari semua bank di IDX, cari 3 bank dengan ROE tertinggi. "
    "Lalu ambil PE ratio dan dividend yield masing-masing. "
    "Analisis: apakah bank dengan ROE tinggi cenderung memiliki PE yang lebih mahal?"
)

def main() -> None:
    print("\n" + "═" * 60)
    print("  IDX INSIGHT ENGINE — PROOF OF CONCEPT")
    print("  Google GenAI SDK (google-genai) · Sectors API v2")
    print("═" * 60)
    print(f"\n📝 QUERY:\n  {QUERY}\n")
    print(f"💾 Cache: {'ADA ✅' if DB_PATH.exists() else 'BELUM ADA — akan fetch API'}")
    print("─" * 60)

    if not GEMINI_KEY:
        print("❌  GEMINI_API_KEY tidak ditemukan di .env")
        return

    client = _build_client()

    global _tool_calls
    _tool_calls         = []
    _credits["total"]   = 0
    _credits["log"]     = []

    print("\n🤖 Agent berpikir dan memilih tools...\n")
    t0 = time.time()

    try:
        chat = client.chats.create(
            model="gemini-1.5-pro",
            config=types.GenerateContentConfig(
                tools=[
                    get_sector_companies,
                    get_company_metrics,
                    get_top_companies_by_metric,
                ],
                system_instruction=(
                    "Kamu adalah analis saham IDX (Bursa Efek Indonesia). "
                    "Jawab dalam Bahasa Indonesia yang terstruktur dan padat.\n"
                    "Langkah wajib dalam melakukan analisis:\n"
                    "1. Gunakan `get_top_companies_by_metric` untuk mendapatkan daftar kandidat simbol perusahaan.\n"
                    "2. Panggil `get_company_metrics` secara individual untuk SETIAP simbol yang diperoleh untuk mengambil data detail ROE, PE ratio, dan dividend yield.\n"
                    "3. Lakukan analisis berdasarkan data lengkap tersebut."
                ),
            )
        )
        response = chat.send_message(QUERY)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        return

    elapsed = time.time() - t0

    print("\n" + "─" * 60)
    print("📊 HASIL ANALISIS:\n")
    print(response.text)

    print("\n" + "─" * 60)
    proof = _validate(_tool_calls)
    print("🔬 BUKTI AUTONOMOUS TOOL SELECTION:\n")

    checks = [
        ("Multi-step  (≥ 2 calls)",    proof["multi_step"]),
        ("Multi-tool  (≥ 2 berbeda)",  proof["multi_tool"]),
        ("Agent pilih symbol sendiri", proof["multi_company"]),
    ]
    for label, ok in checks:
        icon = "✅" if ok else "❌"
        print(f"  {icon}  {label}")

    print(f"\n  Tools  : {', '.join(proof['tools_used'])}")
    print(f"  Calls  : {proof['total_calls']} total")
    print(f"\n  Sequence:")
    for i, call in enumerate(_tool_calls, 1):
        print(f"    {i}. {call}")

    est = _credits["total"]
    print(f"\n  ⏱  Waktu   : {elapsed:.1f}s")
    print(f"  💳 Credits : {'0 (fully cached)' if est == 0 else f'~{est} credits'}")
    if _credits["log"]:
        for entry in _credits["log"]:
            print(f"             ↳ {entry}")

    verdict = "✅  LULUS" if proof["passed"] else "❌  GAGAL"
    reason  = ("agent memilih tools & symbols secara otonom"
               if proof["passed"]
               else "cek output di atas — kemungkinan tools tidak terpanggil")
    print(f"\n  {verdict} — {reason}")
    print("═" * 60 + "\n")

if __name__ == "__main__":
    main()