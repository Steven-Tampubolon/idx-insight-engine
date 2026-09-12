# core/agent.py
"""
Agent AI untuk IDX Insight Engine.
Menggunakan Groq API (Qwen) dengan manual tool-calling loop.
Semua data diambil dari SQLite cache atau API v2 (lazy cache).
"""
import json
import os
import time

import pandas as pd
from groq import Groq
from data.fetcher import (
    get_all_companies,
    get_company_details,
    get_top_from_api,
)

_client    = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
MODEL_NAME = "qwen/qwen3.8-27b"

_tool_log: list[str] = []

# ── Tool implementations ───────────────────────────────────────────────────────
def _get_company_metrics(symbol: str) -> str:
    _tool_log.append(f"get_company_metrics(symbol='{symbol}')")
    data = get_company_details(symbol)
    return json.dumps(data, ensure_ascii=False)

def _get_sector_companies(subsector: str) -> str:
    """
    Ambil daftar perusahaan dalam sub-sektor IDX beserta metrik finansial utama.
    Data dibaca dari SQLite cache.
    Contoh subsector: 'banks', 'telecom', 'coal', 'consumer-goods'
    """
    _tool_log.append(f"get_sector_companies('{subsector}')")

    df = get_all_companies()
    if df.empty:
        return json.dumps({"error": "Cache kosong — jalankan init_cache dulu"})

    # Normalisasi input agar 'Banks' dan 'banks' sama-sama cocok
    mask = df["sub_sector"].str.lower() == subsector.strip().lower()
    filtered = df[mask]

    if filtered.empty:
        # Coba partial match jika exact match gagal
        mask2 = df["sub_sector"].str.lower().str.contains(subsector.strip().lower(), na=False)
        filtered = df[mask2]

    if filtered.empty:
        available = df["sub_sector"].dropna().unique().tolist()[:10]
        return json.dumps({
            "error"    : f"Sub-sektor '{subsector}' tidak ditemukan",
            "tersedia" : available,
        }, ensure_ascii=False)

    # Pilih kolom yang ada (hindari KeyError jika kolom tertentu null semua)
    want_cols = ["symbol", "company_name", "pe_ttm", "forward_pe",
                 "roe", "dividend_yield", "pb", "market_cap"]
    show_cols = [c for c in want_cols if c in filtered.columns]

    result = (
        filtered[show_cols]
        .head(20)
        .to_dict(orient="records")
    )
    return json.dumps(result, ensure_ascii=False, default=str)

def _get_top_companies_by_metric(metric: str, subsector: str = "", n: int = 5) -> str:
    _tool_log.append(
        f"get_top_companies_by_metric(metric='{metric}', subsector='{subsector}', n={n})"
    )
    return get_top_from_api(metric=metric, subsector=subsector, n=min(n, 5))

def _get_subsector_summary(metric: str) -> str:
    """Rata-rata metrik per sub-sektor dari cache."""
    _tool_log.append(f"get_subsector_summary(metric='{metric}')")
    df = get_all_companies()
    if df.empty:
        return json.dumps({"error": "Cache kosong"})
    if metric not in df.columns:
        return json.dumps({"error": f"Metrik '{metric}' tidak tersedia. Tersedia: {list(df.select_dtypes('number').columns)}"})

    df[metric] = pd.to_numeric(df[metric], errors="coerce")
    summary = (
        df.groupby("sub_sector")[metric]
        .agg(["mean", "count"])
        .round(2)
        .sort_values("mean")
        .reset_index()
        .rename(columns={
            "mean" : f"rata_rata_{metric}",
            "count": "jumlah_perusahaan",
        })
        .head(15)
        .to_dict(orient="records")
    )
    return json.dumps(summary, ensure_ascii=False)

# ── Tool registry ──────────────────────────────────────────────────────────────
_available_tools = {
    "get_company_metrics"        : _get_company_metrics,
    "get_sector_companies"       : _get_sector_companies,
    "get_top_companies_by_metric": _get_top_companies_by_metric,
    "get_subsector_summary"      : _get_subsector_summary,
}

_groq_tools = [
    {
        "type": "function",
        "function": {
            "name"       : "get_top_companies_by_metric",
            "description": "Ranking perusahaan IDX teratas berdasarkan metrik. Gunakan PERTAMA untuk dapat kandidat simbol.",
            "parameters" : {
                "type"      : "object",
                "properties": {
                    "metric"   : {"type": "string", "description": "Contoh: 'pe_ttm', 'pb', 'ps', 'market_cap', 'forward_pe'"},
                    "subsector": {"type": "string", "description": "Opsional, filter per sub-sektor misal 'banks'"},
                    "n"        : {"type": "integer", "description": "Jumlah teratas, default 5"},
                },
                "required": ["metric"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name"       : "get_company_metrics",
            "description": "Ambil metrik finansial detail satu perusahaan IDX: PE, PB, PS, market cap, harga saham terakhir.",
            "parameters" : {
                "type"      : "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Simbol saham tanpa .JK, contoh: 'BBCA', 'BMRI', 'TLKM'"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name"       : "get_sector_companies",
            "description": "Ambil daftar SEMUA perusahaan dalam satu sub-sektor IDX LENGKAP dengan metrik finansial: pe_ttm, forward_pe, pb, roe, dividend_yield, market_cap. GUNAKAN INI untuk perbandingan dalam satu sub-sektor — hasil sudah cukup, tidak perlu get_company_metrics lagi.",
            "parameters" : {
                "type"      : "object",
                "properties": {
                    "subsector": {"type": "string", "description": "Contoh: 'banks', 'coal', 'telecommunication'"},
                },
                "required": ["subsector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name"       : "get_subsector_summary",
            "description": "Rata-rata metrik per sub-sektor IDX. Gunakan untuk query perbandingan ANTAR sub-sektor.",
            "parameters" : {
                "type"      : "object",
                "properties": {
                    "metric": {"type": "string", "description": "Contoh: 'pb', 'pe_ttm', 'ps', 'market_cap'"},
                },
                "required": ["metric"],
            },
        },
    },
]

_SYSTEM = (
    "Kamu adalah analis saham IDX (Bursa Efek Indonesia). "
    "Jawab dalam Bahasa Indonesia yang terstruktur dan padat.\n\n"
    "Tools yang tersedia:\n"
    "- `get_sector_companies`: daftar SEMUA perusahaan di satu sub-sektor LENGKAP dengan PE, ROE, PB, dividend_yield, market_cap. "
    "Gunakan ini untuk perbandingan dalam satu sub-sektor — TIDAK perlu panggil get_company_metrics setelahnya.\n"
    "- `get_top_companies_by_metric`: ranking/top N perusahaan. Gunakan untuk query 'terbaik' atau 'teratas'.\n"
    "- `get_company_metrics`: detail SATU perusahaan spesifik. Gunakan HANYA jika user tanya satu simbol tertentu.\n"
    "- `get_subsector_summary`: perbandingan rata-rata metrik ANTAR sub-sektor.\n\n"
    "Aturan wajib:\n"
    "1. JANGAN jawab dari memori — selalu gunakan tools.\n"
    "2. Untuk perbandingan dalam satu sub-sektor, CUKUP panggil get_sector_companies SATU KALI — data PE/ROE/PB sudah lengkap di dalamnya.\n"
    "3. JANGAN panggil get_company_metrics berulang untuk banyak saham — itu boros dan lambat.\n"
    "4. Format jawaban: tabel markdown + analisis singkat.\n"
    "5. Tambahkan disclaimer: 'Ini analisis data, bukan rekomendasi investasi.'\n"
)

# ── Main entry point ───────────────────────────────────────────────────────────
def run_query(user_input: str) -> tuple[str, list[str]]:
    global _tool_log
    _tool_log = []

    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user",   "content": user_input},
    ]

    import re

    try:
        for _ in range(8):
            response      = _client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=_groq_tools,
                tool_choice="auto",
                max_tokens=800,
            )
            msg           = response.choices[0].message
            finish_reason = response.choices[0].finish_reason

            messages.append({
                "role"      : "assistant",
                "content"   : msg.content,
                "tool_calls": [
                    {
                        "id"      : tc.id,
                        "type"    : "function",
                        "function": {
                            "name"     : tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in (msg.tool_calls or [])
                ] or None,
            })

            if finish_reason == "stop" or not msg.tool_calls:
                final = msg.content or ""
                final = re.sub(r"<think>.*?</think>", "", final, flags=re.DOTALL).strip()
                if "<think>" in final:
                    final = final.split("<think>")[0].strip()
                return final, list(_tool_log)

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                output = (
                    _available_tools[fn_name](**fn_args)
                    if fn_name in _available_tools
                    else json.dumps({"error": f"Tool '{fn_name}' tidak ditemukan"})
                )
                messages.append({
                    "role"        : "tool",
                    "tool_call_id": tc.id,
                    "name"        : fn_name,
                    "content"     : output,
                })
            time.sleep(0.2)

        return "⚠️ Agent mencapai batas iterasi.", list(_tool_log)

    except Exception as e:
        return f"⚠️ Groq error: {e}", list(_tool_log)