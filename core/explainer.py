# core/explainer.py
import json
import os
import re

from groq import Groq
from data.fetcher import get_company_details

_client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))


def explain_anomaly(symbol: str, anomaly_row: dict) -> str:
    company  = get_company_details(symbol)
    flagged  = anomaly_row.get("anomaly_flags", [])
    z_scores = {m: round(anomaly_row.get(f"z_{m}", 0), 2) for m in flagged}

    prompt = (
        f"Perusahaan: {company.get('company_name')} ({symbol})\n"
        f"Sub-sektor: {company.get('sub_sector')}\n"
        f"Metrik anomali (z-score): {json.dumps(z_scores)}\n"
        f"PE: {company.get('forward_pe')} | PB: {company.get('pb')}\n\n"
        f"Tulis 2 paragraf singkat dalam Bahasa Indonesia:\n"
        f"1. Mengapa saham ini anomali secara statistik\n"
        f"2. Yang perlu diperhatikan investor\n"
        f"Ini analisis data, bukan rekomendasi investasi."
    )

    try:
        response = _client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        raw = response.choices[0].message.content or ""

        # Kalau ada </think>, ambil teks setelahnya
        if "</think>" in raw:
            raw = raw.split("</think>", 1)[-1].strip()
        # Kalau ada <think> tanpa penutup, buang dari sana ke atas
        elif "<think>" in raw:
            raw = raw.split("<think>", 1)[0].strip()

        return raw if raw else "Tidak ada penjelasan yang dapat dibuat."

    except Exception as e:
        return f"⚠️ Tidak dapat membuat penjelasan: {e}"