# dev/test_one_screener_call.py
# Test SATU panggilan screener sebelum batch enrichment.
# Tujuan: konfirmasi (a) field roe_ttm/yield_ttm benar-benar ada di response,
#         (b) biaya aktual per call (cek dashboard Sectors setelah run!).
# Jalankan dari root: python dev/test_one_screener_call.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.environ["SECTORS_API_KEY"]
BASE    = "https://api.sectors.app/v2"
HDR     = {"Authorization": API_KEY}

r = requests.get(
    f"{BASE}/companies/",
    headers=HDR,
    params={"order_by": "-roe_ttm", "where": "sub_sector='banks'", "limit": 10},
    timeout=15,
)
print(f"Status: {r.status_code}")
r.raise_for_status()
data = r.json()

if "results" in data:
    results = data["results"]
else:
    results = data if isinstance(data, list) else []

print(f"Jumlah hasil: {len(results)}")
if results:
    sample = results[0]
    print(f"\nFields di response: {sorted(sample.keys())}")
    print(f"  roe_ttm   ada: {'roe_ttm' in sample}   -> {sample.get('roe_ttm')}")
    print(f"  yield_ttm ada: {'yield_ttm' in sample} -> {sample.get('yield_ttm')}")
    print(f"  pe_ttm    ada: {'pe_ttm' in sample}    -> {sample.get('pe_ttm')}")
    print(f"  pb_mrq    ada: {'pb_mrq' in sample}    -> {sample.get('pb_mrq')}")
    print("\nTop 3 by ROE:")
    for c in results[:3]:
        print(f"  {c.get('symbol'):8} roe_ttm={c.get('roe_ttm')}")

print("\n⚠️  SEKARANG cek dashboard Sectors: berapa credit terpakai untuk 1 call ini?")
print("    Jika <= 2 credits -> lanjut python dev/enrich_from_screener.py")
print("    Jika > 2 credits  -> batalkan TASK 2, pakai data reports saja.")