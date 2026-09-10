# dev/enrich_from_screener.py
"""
Enrich companies.data dengan roe_ttm/yield_ttm/pe_ttm/pb_mrq dari screener endpoint.
Biaya: ~1 credit per subsector.

PRASYARAT: python dev/test_one_screener_call.py sudah dijalankan & field roe_ttm
           TERKONFIRMASI ADA di response. Jika tidak ada -> JANGAN jalankan script ini.
"""
import json
import os
import re
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

ENRICH_FIELDS = ["roe_ttm", "yield_ttm", "pe_ttm", "pb_mrq", "market_cap"]


def _normalize_subsector(name):
    """Samakan dengan slug API: 'Basic Materials' -> 'basic-materials'."""
    if not name:
        return name
    return (name.strip().lower()
                 .replace(",", "")
                 .replace(" & ", "-")
                 .replace("&", "-")
                 .replace(" ", "-"))


def _normalize_symbol(sym):
    return (sym or "").upper().replace(".JK", "").strip()


def _merge_screener_fields(old: dict, new: dict):
    """Hanya isi field yang masih kosong — tidak menimpa data report."""
    merged, changed = dict(old), False
    for f in ENRICH_FIELDS:
        if new.get(f) is not None and merged.get(f) is None:
            merged[f] = new[f]
            changed = True
    return merged, changed


def _field_coverage(conn):
    cov, rows = {}, conn.execute("SELECT data FROM companies").fetchall()
    for f in ENRICH_FIELDS:
        cov[f] = sum(1 for (d,) in rows
                     if isinstance(d, str)
                     and (lambda x: x is not None)(_try_get(d, f)))
    return cov, len(rows)


def _try_get(raw, field):
    try:
        return json.loads(raw).get(field)
    except Exception:
        return None


def main():
    conn = sqlite3.connect(DB_PATH)

    subsectors = sorted({
        _normalize_subsector(r[0]) for r in conn.execute(
            "SELECT DISTINCT subsector FROM companies "
            "WHERE subsector IS NOT NULL AND subsector != ''"
        ).fetchall()
    })
    print(f"Subsectors unik (ternormalisasi): {len(subsectors)}")
    print(f"Estimasi biaya: ~{len(subsectors)} credits")
    before, total = _field_coverage(conn)
    print("Coverage SEBELUM: " +
          ", ".join(f"{f}={before[f]}/{total}" for f in ENRICH_FIELDS))

    if input("\nKetik 'ya' untuk konfirmasi: ").strip().lower() != "ya":
        print("Dibatalkan. 0 credit terpakai.")
        conn.close()
        return

    enriched, failed, empty = 0, 0, 0
    for sub in subsectors:
        try:
            r = requests.get(
                f"{BASE}/companies/",
                headers=HDR,
                params={
                    "order_by": "-roe_ttm",
                    "where"   : f"sub_sector='{sub}'",
                    "limit"   : 200,
                },
                timeout=15,
            )
            r.raise_for_status()
            raw = r.json()
            companies = raw.get("results", raw) if isinstance(raw, dict) else raw

            # ── DIAGNOSIS: lapor jumlah hasil & field yang benar-benar ada ──
            if not companies:
                empty += 1
                print(f"  ⚠️  {sub}: 0 hasil — where/order_by tidak cocok?")
                time.sleep(0.4)
                continue
            n_fields = sum(1 for c in companies[:5]
                           if isinstance(c, dict) and c.get("roe_ttm") is not None)
            print(f"  ✓ {sub}: {len(companies)} hasil, "
                  f"{n_fields}/5 sample punya roe_ttm")

            for c in companies:
                sym = _normalize_symbol(c.get("symbol"))
                if not sym:
                    continue
                row = conn.execute(
                    "SELECT data FROM companies WHERE symbol=?", (sym,)
                ).fetchone()
                if not row:
                    continue
                try:
                    old = json.loads(row[0])
                except Exception:
                    continue
                merged, changed = _merge_screener_fields(old, c)
                if changed:
                    conn.execute(
                        "UPDATE companies SET data=? WHERE symbol=?",
                        (json.dumps(merged), sym),
                    )
                    enriched += 1

            conn.commit()
            time.sleep(0.4)
        except Exception as e:
            failed += 1
            print(f"  ✗ {sub}: {e}")

    after, total = _field_coverage(conn)
    print("\nCoverage SESUDAH: " +
          ", ".join(f"{f}={after[f]}/{total}" for f in ENRICH_FIELDS))
    print(f"\n✅ Selesai. {enriched} records di-enrich "
          f"({failed} gagal, {empty} subsector return kosong)")
    print(f"   Credit terpakai: ~{len(subsectors) - failed} call")

    conn.close()


if __name__ == "__main__":
    main()