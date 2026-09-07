"""
python -m data.init_cache
Biaya: ~75-150 Sectors credits. Jalankan sekali sebelum demo.
"""
import sqlite3, requests, json, time, os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.environ["SECTORS_API_KEY"]
BASE    = "https://api.sectors.app/v1"
HDR     = {"Authorization": API_KEY}
DB_PATH = Path("data/cache.db")

TARGET_SUBSECTORS = [
    "banks", "financing-service", "food-and-beverage", "telecom",
    "coal", "retail-trade", "healthcare", "property",
    "infrastructure", "consumer-goods", "plantation",
    "pharmaceutical", "auto", "cement", "tech"
]  # 15 sub-sektor utama IDX

def init_db(conn: sqlite3.Connection):
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

def fetch_subsector(subsector: str) -> list:
    """Satu API call per sub-sektor — batch dan murah."""
    r = requests.get(f"{BASE}/companies/", headers=HDR,
                     params={"sub_sector": subsector}, timeout=15)
    r.raise_for_status()
    return r.json()

def main():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    total = 0

    for sub in TARGET_SUBSECTORS:
        try:
            companies = fetch_subsector(sub)
            for c in companies:
                conn.execute(
                    "INSERT OR REPLACE INTO companies (symbol, subsector, data) VALUES (?,?,?)",
                    (c["symbol"], sub, json.dumps(c))
                )
                total += 1
            conn.commit()
            print(f"✓ {sub:30s} — {len(companies)} perusahaan")
            time.sleep(0.5)  # rate limiting
        except Exception as e:
            print(f"✗ {sub}: {e}")

    print(f"\n{'='*50}")
    print(f"✅ {total} perusahaan tersimpan di {DB_PATH}")
    print(f"💡 Estimasi credit: {total // 10 * 5}–{total // 10 * 10}")

    # Pre-compute anomaly scores dari data yang sudah di-cache (0 credit)
    from core.anomaly import detect_anomalies
    import pandas as pd
    rows = conn.execute("SELECT symbol, data FROM companies").fetchall()
    df   = pd.DataFrame([{"symbol": r[0], **json.loads(r[1])} for r in rows])
    scored = detect_anomalies(df)
    for _, row in scored[scored["is_anomaly"]].iterrows():
        conn.execute(
            "INSERT OR REPLACE INTO anomaly_scores (symbol, anomaly_score, flags) VALUES (?,?,?)",
            (row["symbol"], row["anomaly_score"], json.dumps(row["anomaly_flags"]))
        )
    conn.commit()
    conn.close()
    print(f"🎯 Anomaly scores pre-computed — siap demo tanpa API call")

if __name__ == "__main__":
    main()