# core/agent.py
import google.generativeai as genai
import json, os
from data.fetcher import get_all_companies, get_company_details

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

_tool_log: list[str] = []   # di-reset tiap run_query, di-isi oleh setiap tool

def get_company_metrics(symbol: str) -> str:
    """Ambil metrik finansial satu perusahaan IDX dari cache lokal."""
    _tool_log.append(f"get_company_metrics(symbol='{symbol}')")
    data = get_company_details(symbol)
    keys = ["company_name", "sub_sector", "forward_pe", "pb",
            "roe", "dividend_yield", "market_cap"]
    return json.dumps({k: data.get(k) for k in keys}, ensure_ascii=False)

def get_sector_companies(subsector: str) -> str:
    """Ambil semua perusahaan dalam sub-sektor IDX dari cache lokal."""
    _tool_log.append(f"get_sector_companies(subsector='{subsector}')")
    df   = get_all_companies()
    cols = [c for c in ["symbol","company_name","forward_pe","roe","dividend_yield"]
            if c in df.columns]
    return (df[df["sub_sector"] == subsector][cols]
            .head(15)
            .to_json(orient="records", force_ascii=False))

def get_top_by_metric(metric: str, n: int = 10) -> str:
    """Ranking perusahaan IDX berdasarkan satu metrik dari cache lokal."""
    _tool_log.append(f"get_top_by_metric(metric='{metric}', n={n})")
    df = get_all_companies()
    if metric not in df.columns:
        return json.dumps({"error": f"Metrik '{metric}' tidak ditemukan"})
    cols = [c for c in ["symbol","company_name","sub_sector", metric] if c in df.columns]
    return df.nlargest(n, metric)[cols].to_json(orient="records", force_ascii=False)

_model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    tools=[get_company_metrics, get_sector_companies, get_top_by_metric],
    system_instruction=(
        "Kamu adalah asisten analisis saham IDX (Bursa Efek Indonesia). "
        "Jawab dalam Bahasa Indonesia, ringkas dan padat. "
        "Selalu gunakan tools untuk mengambil data dari cache lokal. "
        "Ini untuk keperluan analisis, bukan rekomendasi investasi."
    )
)

def run_query(user_input: str) -> tuple[str, list[str]]:
    """
    Jalankan AI query. Tool functions mencatat ke _tool_log via side-effect.
    Returns: (jawaban, daftar tool calls)
    """
    global _tool_log
    _tool_log = []
    try:
        chat     = _model.start_chat(enable_automatic_function_calling=True)
        response = chat.send_message(user_input)
        return response.text, list(_tool_log)
    except Exception as e:
        return f"⚠️ Gemini error: {e}", list(_tool_log)