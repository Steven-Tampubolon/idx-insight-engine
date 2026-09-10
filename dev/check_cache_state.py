# dev/check_cache_state.py
# Jalankan dari root: python dev/check_cache_state.py
# TIDAK memanggil API sama sekali — hanya baca SQLite.
import sqlite3
import json
from pathlib import Path

DB = Path("data/cache.db")
if not DB.exists():
    print("❌ cache.db tidak ada — perlu init_cache dulu")
    raise SystemExit(1)

conn = sqlite3.connect(DB)

# 1. Hitung jumlah records
n_companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
n_reports   = conn.execute("SELECT COUNT(*) FROM company_reports").fetchone()[0]
n_anomaly   = conn.execute("SELECT COUNT(*) FROM anomaly_scores").fetchone()[0]
print(f"companies       : {n_companies} records")
print(f"company_reports : {n_reports} records")
print(f"anomaly_scores  : {n_anomaly} records (0 = normal, dihitung in-memory)")
print()

# 2. Cek apakah ROE ada di company_reports
has_roe = conn.execute(
    "SELECT COUNT(*) FROM company_reports WHERE data LIKE '%financial_ratio%'"
).fetchone()[0]
has_div = conn.execute(
    "SELECT COUNT(*) FROM company_reports WHERE data LIKE '%yield_ttm%'"
).fetchone()[0]
print(f"Reports dengan financials (ROE source): {has_roe}/{n_reports}")
print(f"Reports dengan dividend yield          : {has_div}/{n_reports}")
print()

# 3. Cek apakah ROE ada di companies (screener data)
sample_company = conn.execute("SELECT symbol, data FROM companies LIMIT 1").fetchone()
if sample_company:
    d = json.loads(sample_company[1])
    print(f"companies.data keys (sample '{sample_company[0]}'):")
    print(f"  {list(d.keys())}")
    print(f"  roe_ttm   : {d.get('roe_ttm')}")
    print(f"  yield_ttm : {d.get('yield_ttm')}")
    print(f"  pe_ttm    : {d.get('pe_ttm')}")
print()

# 4. Cek berapa companies punya roe_ttm di screener data
n_roe = conn.execute(
    "SELECT COUNT(*) FROM companies WHERE data LIKE '%roe_ttm%'"
).fetchone()[0]
n_yld = conn.execute(
    "SELECT COUNT(*) FROM companies WHERE data LIKE '%yield_ttm%'"
).fetchone()[0]
print(f"companies.data dengan roe_ttm   : {n_roe}/{n_companies}")
print(f"companies.data dengan yield_ttm : {n_yld}/{n_companies}")
print()

# 5. Cek sample report yang punya financials
sample_report = conn.execute(
    "SELECT symbol, data FROM company_reports "
    "WHERE data LIKE '%financial_ratio%' LIMIT 1"
).fetchone()
if sample_report:
    d2 = json.loads(sample_report[1])
    fin = d2.get("financials", {})
    ratios = fin.get("historical_financial_ratio", [])
    if ratios:
        latest = sorted(ratios, key=lambda x: x.get("year", 0), reverse=True)[0]
        prof = latest.get("profitability", {})
        print(f"Sample report dengan financials: {sample_report[0]}")
        print(f"  ROE dari financial_ratio: {prof.get('roe')}")
else:
    print("⚠️  TIDAK ADA report yang punya financial_ratio")
    print("   ROE dari company_reports = None untuk semua companies")

conn.close()