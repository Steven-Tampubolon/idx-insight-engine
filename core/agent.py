# core/agent.py
"""
Agent AI untuk IDX Insight Engine.
Menggunakan Groq API (Qwen 3.8B) dengan manual tool-calling loop.
Semua data diambil dari SQLite cache (0 Sectors credits) atau API v2 (lazy cache).
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

# ── Groq client ────────────────────────────────────────────────────────────────
_client    = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
MODEL_NAME = "qwen/qwen3.8-27b"

# ── Tool log (diisi oleh fetcher via side-effect) ──────────────────────────────
_tool_log: list[str] = []

# ── Tool implementations ───────────────────────────────────────────────────────
def _get_company_metrics(symbol: str) -> str:
    """Ambil metrik finansial satu perusahaan IDX."""
    _tool_log.append(f"get_company_metrics(symbol='{symbol}')")
    data = get_company_details(symbol)
    return json.dumps(data, ensure_ascii=False)

def _get_sector_companies(subsector: str) -> str:
    """Ambil daftar SIMBOL perusahaan dalam satu sub-sektor IDX."""
    _tool_log.append(f"get_sector_companies(subsector='{subsector}')")
    df = get_all_companies()
    if df.empty:
        return json.dumps({"error": "Cache kosong"})
    
    mask = df.get("sub_sector", pd.Series(dtype=str)) == subsector
    # ← Hanya return symbol + company_name, cukup untuk agent tahu siapa saja
    result = df[mask][["symbol", "company_name"]].head(20).to_dict(orient="records")
    return json.dumps(result, ensure_ascii=False)


def _get_top_companies_by_metric(metric: str, subsector: str = "", n: int = 5) -> str:
    """Ranking perusahaan IDX berdasarkan metrik tertentu."""
    _tool_log.append(
        f"get_top_companies_by_metric(metric='{metric}', subsector='{subsector}', n={n})"
    )
    return get_top_from_api(metric=metric, subsector=subsector, n=min(n, 5))  # ← max 5

# ── Tool registry ──────────────────────────────────────────────────────────────
_available_tools = {
    "get_company_metrics":        _get_company_metrics,
    "get_sector_companies":       _get_sector_companies,
    "get_top_companies_by_metric": _get_top_companies_by_metric,
}

_groq_tools = [
    {
        "type": "function",
        "function": {
            "name": "get_sector_companies",
            "description": "Ambil daftar SIMBOL perusahaan dalam satu sub-sektor IDX.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subsector": {
                        "type": "string",
                        "description": "Contoh: 'banks', 'telecom', 'coal'"
                    }
                },
                "required": ["subsector"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_metrics",
            "description": "Ambil metrik finansial detail satu perusahaan IDX: PE ratio, ROE, dividend yield, PB, market cap.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Simbol saham, contoh: 'BMRI', 'BBCA', 'TLKM'"
                    }
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_companies_by_metric",
            "description": "Ketahui kandidat SIMBOL perusahaan IDX teratas berdasarkan metrik tertentu (roe, pe, dividend_yield, dll).",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "description": "Contoh: 'roe', 'pe', 'dividend_yield', 'pb'"
                    },
                    "subsector": {
                        "type": "string",
                        "description": "Opsional, filter per sub-sektor misal 'banks'"
                    },
                    "n": {
                        "type": "integer",
                        "description": "Jumlah perusahaan teratas, default 5"
                    }
                },
                "required": ["metric"]
            }
        }
    }
]

_SYSTEM = (
    "Kamu adalah analis saham IDX (Bursa Efek Indonesia). "
    "Jawab dalam Bahasa Indonesia yang terstruktur dan padat.\n"
    "Langkah wajib:\n"
    "1. Gunakan `get_top_companies_by_metric` untuk mendapatkan kandidat simbol.\n"
    "2. Panggil `get_company_metrics` secara individual untuk SETIAP simbol.\n"
    "3. Lakukan analisis berdasarkan data lengkap tersebut.\n"
    "Ini untuk keperluan analisis data, bukan rekomendasi investasi."
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
        for _ in range(8):  # max 8 iterasi
            response      = _client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=_groq_tools,
                tool_choice="auto",
                max_tokens=800,
            )
            msg           = response.choices[0].message
            finish_reason = response.choices[0].finish_reason

            # Append sebagai dict — BUKAN object langsung
            messages.append({
                "role": "assistant",
                "content": msg.content,  # boleh None
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in (msg.tool_calls or [])
                ] or None,
            })

            # Tidak ada tool call → selesai
            if finish_reason == "stop" or not msg.tool_calls:
                final = msg.content or ""
                final = re.sub(r"<think>.*?</think>", "", final, flags=re.DOTALL).strip()
                if "<think>" in final:
                    final = final.split("<think>")[0].strip()
                return final, list(_tool_log)

            # Eksekusi semua tool calls
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
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "name":         fn_name,
                    "content":      output,
                })
            time.sleep(0.2)

        return "⚠️ Agent mencapai batas iterasi.", list(_tool_log)

    except Exception as e:
        return f"⚠️ Groq error: {e}", list(_tool_log)