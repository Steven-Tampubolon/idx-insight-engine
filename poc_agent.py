#!/usr/bin/env python3
"""
poc_agent.py (Groq Version) — Proof of Concept: Autonomous Multi-Step Tool Selection
====================================================================================
Menggunakan Groq API (Llama-3.3-70b) untuk otonomi tool-calling IDX financial analysis.

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
from groq import Groq

load_dotenv()

# ── Config ────────────────────────────────────────────────________________─────
GROQ_KEY    = os.environ.get("GROQ_API_KEY", "")
SECTORS_KEY = os.environ.get("SECTORS_API_KEY", "")
BASE        = "https://api.sectors.app/v2"
HDR         = {"Authorization": SECTORS_KEY}
DB_PATH     = Path("data/cache.db")
MODEL_NAME  = "qwen/qwen3.8-27b"

METRIC_FIELD_MAP = {
    "roe":            "roe_ttm",
    "forward_pe":     "forward_pe",
    "pe":             "pe_ttm",
    "pb":             "pb_mrq",
    "dividend_yield": "yield_ttm",
}

# ── Credit/Request tracker ──────────────────────────────────────────────────────
_credits: dict = {"total": 0, "log": []}

def _spend(label: str, cost: int) -> None:
    _credits["total"] += cost
    _credits["log"].append(f"{label} (~{cost} cr)")

# ── SQLite helpers (Sama seperti sebelumnya) ───────────────────────────────────
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

def _get_nested(data, *keys):
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
    return {
        "company_name":   _get_nested(data, "company_name", "name"),
        "sub_sector":     _get_nested(data, "sub_sector", "subsector"),
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
    """Ambil daftar SIMBOL perusahaan dalam satu sub-sektor IDX."""
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
    """Ambil metrik finansial detail satu perusahaan IDX: PE ratio, ROE, dividend yield, PB, market cap."""
    symbol = symbol.upper().replace(".JK", "").strip()
    entry = f"get_company_metrics('{symbol}')"
    _tool_calls.append(entry)
    print(f"\n  🔧 TOOL CALL: {entry}")

    cached = _cache_get_company(symbol)
    if cached:
        print(f"     ✅ cache hit — 0 credits")
        return json.dumps(_extract_metrics(cached), ensure_ascii=False)

    print(f"     📡 cache miss → Sectors REST API v2...")
    if not SECTORS_KEY:
        return json.dumps({"error": "SECTORS_API_KEY tidak ada dan cache kosong."})
    try:
        r = requests.get(f"{BASE}/company/report/{symbol}/", headers=HDR, timeout=15)
        r.raise_for_status()
        raw  = r.json()
        data = raw.get("results", raw) if isinstance(raw, dict) and "results" in raw else raw
        if isinstance(data, list) and len(data) > 0:
            data = data[0]

        subsector = _get_nested(data, "sub_sector", "subsector") or ""
        _cache_save_company(symbol, subsector, data)
        _spend(entry, 2)
        time.sleep(0.5)
        return json.dumps(_extract_metrics(data), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_top_companies_by_metric(metric: str, subsector: str = "", n: int = 5) -> str:
    """Ketahui kandidat SIMBOL perusahaan IDX teratas berdasarkan metrik tertentu (roe, pe, dll)."""
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
        summary = [{"symbol": item.get("symbol"), "company_name": item.get("company_name")} for item in results if isinstance(item, dict)]
        _spend(entry, 1)
        time.sleep(0.3)
        return json.dumps(summary, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})

# Mapping fungsi lokal untuk dieksekusi oleh agent loop
available_tools = {
    "get_sector_companies": get_sector_companies,
    "get_company_metrics": get_company_metrics,
    "get_top_companies_by_metric": get_top_companies_by_metric,
}

# Definisi JSON Schema Tools untuk Groq OpenAI-compatible format
groq_tools = [
    {
        "type": "function",
        "function": {
            "name": "get_sector_companies",
            "description": "Ambil daftar SIMBOL perusahaan dalam satu sub-sektor IDX.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subsector": {"type": "string", "description": "Contoh: 'banks', 'telecom', 'coal'"}
                },
                "required": ["subsector"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_metrics",
            "description": "Ambil metrik finansial detail satu perusahaan IDX: PE ratio, ROE, dividend yield, PB.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Simbol saham, contoh: 'BMRI', 'BBCA'"}
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_companies_by_metric",
            "description": "Ketahui kandidat SIMBOL perusahaan IDX teratas berdasarkan metrik tertentu.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string", "description": "Contoh: 'roe', 'pe', 'dividend_yield'"},
                    "subsector": {"type": "string", "description": "Opsional, misal 'banks'"},
                    "n": {"type": "integer", "description": "Jumlah perusahaan teratas"}
                },
                "required": ["metric"]
            }
        }
    }
]

def _validate(calls: list) -> dict:
    unique_fns = {c.split("(")[0] for c in calls}
    multi_company = sum(1 for c in calls if c.startswith("get_company")) >= 2
    passed = len(calls) >= 2 and len(unique_fns) >= 2 and multi_company
    return {
        "total_calls": len(calls),
        "unique_tools": len(unique_fns),
        "tools_used": sorted(unique_fns),
        "multi_step": len(calls) >= 2,
        "multi_tool": len(unique_fns) >= 2,
        "multi_company": multi_company,
        "passed": passed,
    }

QUERY = (
    "Dari semua bank di IDX, cari 3 bank dengan ROE tertinggi. "
    "Lalu ambil PE ratio dan dividend yield masing-masing. "
    "Analisis: apakah bank dengan ROE tinggi cenderung memiliki PE yang lebih mahal?"
)

def main() -> None:
    print("\n" + "═" * 60)
    print("  IDX INSIGHT ENGINE — GROQ AGENT PROOF OF CONCEPT")
    print("  Groq SDK (llama-3.3-70b-versatile) · Sectors API v2")
    print("═" * 60)
    print(f"\n📝 QUERY:\n  {QUERY}\n")
    print(f"💾 Cache: {'ADA ✅' if DB_PATH.exists() else 'BELUM ADA'}")
    print("─" * 60)

    if not GROQ_KEY:
        print("❌ GROQ_API_KEY tidak ditemukan di .env")
        return

    client = Groq(api_key=GROQ_KEY)
    global _tool_calls
    _tool_calls = []
    _credits["total"] = 0
    _credits["log"] = []

    messages = [
        {
            "role": "system",
            "content": (
                "Kamu adalah analis saham IDX (Bursa Efek Indonesia). "
                "Jawab dalam Bahasa Indonesia yang terstruktur dan padat.\n"
                "Langkah wajib dalam melakukan analisis:\n"
                "1. Gunakan `get_top_companies_by_metric` untuk mendapatkan daftar kandidat simbol perusahaan.\n"
                "2. Panggil `get_company_metrics` secara individual untuk SETIAP simbol yang diperoleh untuk mengambil data detail.\n"
                "3. Lakukan analisis berdasarkan data lengkap tersebut."
            )
        },
        {"role": "user", "content": QUERY}
    ]

    print("\n🤖 Groq Agent berpikir dan memanggil tools (Multi-step loop)...\n")
    t0 = time.time()

    try:
        # Step 1: First request to model
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=groq_tools,
            tool_choice="auto"
        )
        
        response_message = response.choices[0].message
        messages.append(response_message)

        # Step 2: Handle tool calls loop if requested by model
        while response_message.tool_calls:
            for tool_call in response_message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)
                
                if fn_name in available_tools:
                    tool_output = available_tools[fn_name](**fn_args)
                else:
                    tool_output = json.dumps({"error": f"Tool {fn_name} tidak ditemukan"})

                # Append tool response back to messages history
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": fn_name,
                    "content": tool_output,
                })

            # Follow-up request to model after tool results are provided
            second_response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=groq_tools,
                tool_choice="auto"
            )
            response_message = second_response.choices[0].message
            messages.append(response_message)

        final_text = response_message.content

    except Exception as e:
        print(f"\n❌ Error: {e}")
        return

    elapsed = time.time() - t0

    print("\n" + "─" * 60)
    print("📊 HASIL ANALISIS (Groq):\n")
    print(final_text)

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

    print(f"\n  ⏱  Waktu   : {elapsed:.1f}s")
    print(f"  💳 Credits/Calls: ~{_credits['total']} API hits")
    
    verdict = "✅  LULUS" if proof["passed"] else "❌  GAGAL"
    print(f"\n  {verdict} — Groq autonomous tool orchestration.")
    print("═" * 60 + "\n")

if __name__ == "__main__":
    main()