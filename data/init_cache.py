# data/init_cache.py
"""
python -m data.init_cache
Inisialisasi SQLite cache dengan data dari Sectors API v2.
Estimasi biaya:
- 1 credit untuk GET /v2/subsectors/
- ~1 credit per subsector untuk GET /v2/companies/ (screener)
- 4 credits per company untuk GET /v2/company/report/{sym}/ (terkonfirmasi)
- Total jika fetch 100 company reports: ~421 credits
- Jalankan SEKALI saja — jangan ulangi tanpa hitung credit dulu.Jalankan SEKALI sebelum demo.
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

def _unwrap_v2(raw) -> list:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and "results" in raw:
        return raw["results"]
    return []

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            symbol      TEXT PRIMARY KEY,
            subsector   TEXT,
            data        JSON,
            fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS company_reports (
            symbol      TEXT PRIMARY KEY,
            data        JSON,
            fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS anomaly_scores (
            symbol          TEXT PRIMARY KEY,
            anomaly_score   REAL,
            flags           JSON,
            computed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

def fetch_valid_subsectors() -> list[str]:
    """
    Ambil daftar slug subsector yang VALID dari API.
    1 credit — hindari salah ejaan yang bikin query return 0 hasil.
    """
    print("📋 Mengambil daftar subsector valid dari API... (1 credit)")
    r = requests.get(f"{BASE}/subsectors/", headers=HDR, timeout=15)
    r.raise_for_status()
    data = r.json()
    # Response: [{"sector": "financials", "subsector": "banks"}, ...]
    slugs = [item["subsector"] for item in data if "subsector" in item]
    print(f"   ✅ {len(slugs)} subsector ditemukan")
    return slugs

def fetch_subsector_companies(subsector: str) -> list:
    """
    Ambil perusahaan + metrik per subsector.
    Pakai order_by agar data sudah terurut saat masuk cache.
    1 credit per call.
    """
    r = requests.get(
        f"{BASE}/companies/",
        headers=HDR,
        params={
            "where"   : f"sub_sector='{subsector}'",
            "order_by": "-market_cap",   # urutkan by market cap descending
            "limit"   : 200,             # ambil semua
        },
        timeout=15
    )
    r.raise_for_status()
    return _unwrap_v2(r.json())

def main() -> None:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # Step 1: ambil daftar subsector yang valid (1 credit)
    try:
        all_subsectors = fetch_valid_subsectors()
        time.sleep(0.3)
    except Exception as e:
        print(f"❌ Gagal ambil subsectors: {e}")
        return

    # Step 2: filter hanya subsector yang relevan untuk app kita
    # Kalau mau semua, hapus filter ini
    TARGET_KEYWORDS = [
        "banks", "financing", "food", "telecom", "coal",
        "retail", "health", "property", "infrastructure",
        "consumer", "plantation", "pharma", "auto", "cement", "tech",
        "insurance", "energy", "tobacco", "media", "hotel"
    ]
    target_subsectors = [
        s for s in all_subsectors
        if any(kw in s for kw in TARGET_KEYWORDS)
    ]
    print(f"\n🎯 Target: {len(target_subsectors)} subsector dari {len(all_subsectors)} total")

    # Step 3: fetch per subsector dan simpan ke cache
    total = 0
    failed = []
    for sub in target_subsectors:
        try:
            companies = fetch_subsector_companies(sub)
            saved = 0
            for c in companies:
                symbol = c.get("symbol", "")
                if not symbol:
                    continue
                # Bersihkan symbol: hapus .JK suffix
                symbol_clean = symbol.upper().replace(".JK", "").strip()
                conn.execute(
                    "INSERT OR REPLACE INTO companies (symbol, subsector, data) VALUES (?,?,?)",
                    (symbol_clean, sub, json.dumps(c))
                )
                saved += 1
            conn.commit()
            total += saved
            status = f"— {saved} perusahaan" if saved > 0 else "— ⚠️  0 hasil"
            print(f"✓ {sub:35s} {status}")
            time.sleep(0.4)
        except Exception as e:
            failed.append(sub)
            print(f"✗ {sub}: {e}")

    print(f"\n{'='*55}")
    print(f"✅ {total} perusahaan tersimpan di {DB_PATH}")
    print(f"💡 Credit terpakai: ~{1 + len(target_subsectors)} credits")
    if failed:
        print(f"⚠️  Gagal: {failed}")

    # Tambahkan ini di main() setelah loop subsector berhasil, sebelum anomaly step:

    # Step 4: Pre-fetch company report untuk top 5 per subsector (hemat credit)
    print("\n📊 Pre-fetching company reports untuk top companies...")
    conn2   = sqlite3.connect(DB_PATH)
    symbols = [r[0] for r in conn2.execute(
        "SELECT DISTINCT symbol FROM companies LIMIT 100"   # top 100 saja
    ).fetchall()]
    conn2.close()

    fetched_reports = 0
    for sym in symbols[:100]:
        # Cek dulu apakah sudah ada di company_reports
        conn2 = sqlite3.connect(DB_PATH)
        exists = conn2.execute(
            "SELECT 1 FROM company_reports WHERE symbol=?", (sym,)
        ).fetchone()
        conn2.close()
        if exists:
            continue
        
        try:
            r = requests.get(
                f"{BASE}/company/report/{sym}/",
                headers=HDR,
                params={"sections": "overview,valuation,financials,dividend"},
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                conn2 = sqlite3.connect(DB_PATH)
                conn2.execute(
                    "INSERT OR REPLACE INTO company_reports (symbol, data) VALUES (?,?)",
                    (sym, json.dumps(data))
                )
                conn2.commit()
                conn2.close()
                fetched_reports += 1
            time.sleep(0.3)
        except Exception:
            pass

    print(f"   ✅ {fetched_reports} company reports di-cache (~{fetched_reports * 2} credits)")
    # Step 5: pre-compute anomaly — 0 credit tambahan
    try:
        from core.anomaly import detect_anomalies
        import pandas as pd
        rows   = conn.execute("SELECT symbol, data FROM companies").fetchall()
        df     = pd.DataFrame([{"symbol": r[0], **json.loads(r[1])} for r in rows])
        scored = detect_anomalies(df)
        anomaly_rows = scored[scored["is_anomaly"]]
        for _, row in anomaly_rows.iterrows():
            conn.execute(
                "INSERT OR REPLACE INTO anomaly_scores (symbol, anomaly_score, flags) VALUES (?,?,?)",
                (row["symbol"], row["anomaly_score"], json.dumps(row.get("anomaly_flags", [])))
            )
        conn.commit()
        print(f"🎯 {len(anomaly_rows)} anomaly scores pre-computed")
    except Exception as e:
        print(f"⚠️  Anomaly pre-compute skip: {e}")

    conn.close()

if __name__ == "__main__":
    main()