import google.generativeai as genai
import json, os
from data.fetcher import get_company_details

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
_model = genai.GenerativeModel("gemini-1.5-flash")

def explain_anomaly(symbol: str, anomaly_row: dict) -> str:
    """
    Ambil konteks dari SQLite (0 credits), kirim ke Gemini (gratis).
    Jika company_reports belum di-cache → 1x API call ~7 credits.
    """
    company  = get_company_details(symbol)   # SQLite-first
    flagged  = anomaly_row.get("anomaly_flags", [])
    z_scores = {m: round(anomaly_row.get(f"z_{m}", 0), 2) for m in flagged}

    prompt = f"""Kamu adalah analis pasar IDX yang menulis untuk investor ritel Indonesia.

Perusahaan : {company.get('company_name')} ({symbol})
Sub-sektor : {company.get('sub_sector')}
Market cap : {company.get('market_cap')}

Metrik anomali (z-score vs median sub-sektor):
{json.dumps(z_scores, indent=2)}

Nilai aktual:
- PE  : {company.get('forward_pe')}
- PB  : {company.get('pb')}
- ROE : {company.get('roe')}
- DY  : {company.get('dividend_yield')}

Tulis 2–3 paragraf dalam Bahasa Indonesia:
1. Mengapa saham ini anomali secara statistik
2. Kemungkinan alasan fundamental
3. Yang perlu diperhatikan investor

Ini analisis data, bukan rekomendasi investasi."""

    response = _model.generate_content(prompt)
    return response.text