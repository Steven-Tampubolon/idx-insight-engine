"""
dev/enrich_roe_yield.py
Enrich company_reports yang sudah ada dengan data financials + dividend.
Jalankan dari root: python dev/enrich_roe_yield.py

PERINGATAN: Biaya AKTUAL adalah 4 credits per company (bukan 1).
162 companies × 4 = 648 credits. JANGAN jalankan tanpa cek saldo dulu.
Alternatif lebih murah: gunakan dev/enrich_from_screener.py (~20 credits).
"""
import json
import os
import sqlite3
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["SECTORS_API_KEY"]
BASE    = "https://api.sectors.app/v2"
HDR     = {"Authorization": API_KEY}
DB_PATH = Path("data/cache.db")


def main():
    conn = sqlite3.connect(DB_PATH)

    # Ambil semua symbol yang sudah punya company_reports
    # tapi belum punya data financials (roe masih null)
    symbols = [
        r[0] for r in conn.execute(
            "SELECT symbol FROM company_reports "
            "WHERE data NOT LIKE '%financial_ratio%'"  # belum punya financials
        ).fetchall()
    ]
    print(f"Perlu enrich: {len(symbols)} symbols")

    ok, fail = 0, 0
    for i, sym in enumerate(symbols):
        try:
            r = requests.get(
                f"{BASE}/company/report/{sym}/",
                headers=HDR,
                params={"sections": "overview,valuation,financials,dividend"},
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                conn.execute(
                    "INSERT OR REPLACE INTO company_reports (symbol, data) VALUES (?,?)",
                    (sym, json.dumps(data))
                )
                conn.commit()
                ok += 1
            elif r.status_code == 429:
                print(f"  ⚠️  Rate limit di [{i+1}] — tunggu 10s...")
                time.sleep(10)
                # Retry sekali
                r2 = requests.get(
                    f"{BASE}/company/report/{sym}/",
                    headers=HDR,
                    params={"sections": "overview,valuation,financials,dividend"},
                    timeout=10
                )
                if r2.status_code == 200:
                    conn.execute(
                        "INSERT OR REPLACE INTO company_reports (symbol, data) VALUES (?,?)",
                        (sym, json.dumps(r2.json()))
                    )
                    conn.commit()
                    ok += 1
            elif r.status_code == 404:
                fail += 1
            time.sleep(0.5)
        except Exception as e:
            fail += 1
            print(f"  ✗ {sym}: {e}")

        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(symbols)}] ok={ok} fail={fail}")

    conn.close()
    print(f"\nSelesai! ok={ok} fail={fail} (~{ok} credits terpakai)")


if __name__ == "__main__":
    main()