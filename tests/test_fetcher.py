# tests/test_fetcher.py
# Jalankan dari root: python -m pytest tests/test_fetcher.py -v
# Semua test: (mock SQLite, tidak ada HTTP request).
import json
import sqlite3
import sys
import os

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.fetcher as fetcher
from data.fetcher import _extract_metrics, get_all_companies


# ── Fixtures: response palsu ala Sectors API v2 ───────────────────────────────
def make_report(roe_path="nested", div_path="yield_ttm"):
    """Bangun response company report v2 dengan struktur ROE/dividend tertentu."""
    report = {
        "company_name": "PT Bank Test Tbk",
        "overview": {"sub_sector": "banks", "market_cap": 100_000},
        "valuation": {"forward_pe": 12.5,
                      "historical_valuation": [{"year": 2025, "pe": 15.0, "pb": 2.0}]},
        "financials": {},
        "dividend": {},
    }
    if roe_path == "nested":
        report["financials"]["historical_financial_ratio"] = [
            {"year": 2024, "profitability": {"roe": 18.5}},
            {"year": 2025, "profitability": {"roe": 20.1}},
        ]
    elif roe_path == "flat_ratio":
        report["financials"]["historical_financial_ratio"] = [
            {"year": 2025, "roe": 17.3}
        ]
    elif roe_path == "flat_financials":
        report["financials"]["roe"] = 16.0
    elif roe_path == "overview":
        report["overview"]["roe"] = 15.2
    # roe_path == "none" → tidak ada ROE sama sekali

    if div_path == "yield_ttm":
        report["dividend"]["yield_ttm"] = 4.5
    elif div_path == "yield":
        report["dividend"]["yield"] = 3.8
    elif div_path == "overview":
        report["overview"]["dividend_yield"] = 2.9
    elif div_path == "hist_val":
        report["valuation"]["historical_valuation"][0]["yield"] = 3.1
    # div_path == "none" → tidak ada yield
    return report


# ── Unit tests: _extract_metrics ──────────────────────────────────────────────
class TestExtractMetrics:
    def test_empty_dict_no_exception(self):
        out = _extract_metrics({})
        assert out["roe"] is None
        assert out["dividend_yield"] is None
        assert out["pe_ttm"] is None

    def test_none_input_no_exception(self):
        out = _extract_metrics(None)
        assert out["roe"] is None

    def test_nested_profitability_roe(self):
        out = _extract_metrics(make_report(roe_path="nested"))
        assert out["roe"] == 20.1  # tahun terbaru (2025), bukan 2024

    def test_flat_ratio_roe(self):
        out = _extract_metrics(make_report(roe_path="flat_ratio"))
        assert out["roe"] == 17.3

    def test_flat_financials_roe(self):
        out = _extract_metrics(make_report(roe_path="flat_financials"))
        assert out["roe"] == 16.0

    def test_overview_roe_fallback(self):
        out = _extract_metrics(make_report(roe_path="overview"))
        assert out["roe"] == 15.2

    def test_roe_none_when_missing(self):
        out = _extract_metrics(make_report(roe_path="none"))
        assert out["roe"] is None

    def test_div_yield_ttm(self):
        out = _extract_metrics(make_report(div_path="yield_ttm"))
        assert out["dividend_yield"] == 4.5

    def test_div_yield_flat(self):
        out = _extract_metrics(make_report(div_path="yield"))
        assert out["dividend_yield"] == 3.8

    def test_div_yield_overview_fallback(self):
        out = _extract_metrics(make_report(div_path="overview"))
        assert out["dividend_yield"] == 2.9

    def test_div_yield_hist_val_fallback(self):
        out = _extract_metrics(make_report(div_path="hist_val"))
        assert out["dividend_yield"] == 3.1


# ── Unit tests: get_all_companies (mock SQLite) ───────────────────────────────
@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Ganti DB_PATH fetcher dengan SQLite sementara berisi data uji."""
    db_file = tmp_path / "cache.db"
    conn = sqlite3.connect(db_file)
    conn.executescript("""
        CREATE TABLE companies (
            symbol TEXT PRIMARY KEY, subsector TEXT, data JSON,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE company_reports (
            symbol TEXT PRIMARY KEY, data JSON,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    """)

    # A: punya roe_ttm di screener data, tidak punya report
    conn.execute(
        "INSERT INTO companies VALUES (?,?,?,CURRENT_TIMESTAMP)",
        ("BANKA", "banks",
         json.dumps({"company_name": "Bank A", "roe_ttm": 22.5,
                     "yield_ttm": 5.1, "pe_ttm": 8.2, "pb_mrq": 1.5})))

    # B: punya report (ROE 20.1) + roe_ttm screener (22.5) → report menang
    conn.execute(
        "INSERT INTO companies VALUES (?,?,?,CURRENT_TIMESTAMP)",
        ("BANKB", "banks",
         json.dumps({"company_name": "Bank B", "roe_ttm": 22.5})))
    conn.execute(
        "INSERT INTO company_reports VALUES (?,?,CURRENT_TIMESTAMP)",
        ("BANKB", json.dumps(make_report(roe_path="nested", div_path="yield_ttm"))))

    # C: tidak punya apa-apa
    conn.execute(
        "INSERT INTO companies VALUES (?,?,?,CURRENT_TIMESTAMP)",
        ("BANKC", "banks", json.dumps({"company_name": "Bank C"})))

    # D: data corrupt (bukan JSON) → tidak boleh crash seluruh fungsi
    conn.execute(
        "INSERT INTO companies VALUES (?,?,?,CURRENT_TIMESTAMP)",
        ("BANKD", "banks", "{corrupt-json"))

    conn.commit()
    conn.close()

    monkeypatch.setattr(fetcher, "DB_PATH", db_file)
    get_all_companies.clear()  # bersihkan cache streamlit antar-test
    return db_file


class TestGetAllCompanies:
    def test_screener_roe_extracted(self, temp_db):
        df = get_all_companies()
        row = df[df["symbol"] == "BANKA"].iloc[0]
        assert row["roe"] == 22.5
        assert row["dividend_yield"] == 5.1
        assert row["pe_ttm"] == 8.2

    def test_report_overrides_screener(self, temp_db):
        df = get_all_companies()
        row = df[df["symbol"] == "BANKB"].iloc[0]
        assert row["roe"] == 20.1          # dari report, bukan 22.5 dari screener
        assert row["dividend_yield"] == 4.5

    def test_nulls_when_no_data(self, temp_db):
        df = get_all_companies()
        row = df[df["symbol"] == "BANKC"].iloc[0]
        assert pd.isna(row["roe"])
        assert pd.isna(row["dividend_yield"])

    def test_corrupt_row_skipped_others_survive(self, temp_db):
        df = get_all_companies()
        assert "BANKD" not in set(df["symbol"])
        assert {"BANKA", "BANKB", "BANKC"} <= set(df["symbol"])

    def test_non_null_counts(self, temp_db):
        df = get_all_companies()
        if not df.empty:
            assert df["roe"].notna().sum() >= 2        # BANKA + BANKB
            assert df["dividend_yield"].notna().sum() >= 2
    def test_sub_sector_normalized_when_report_pretty(self, temp_db):
        # BANKB punya report dengan overview.sub_sector = "Banks" (pretty)
        # harus ternormalisasi jadi "banks" (slug), sama dengan BANKA/BANKC
        df = get_all_companies()
        assert (df["sub_sector"] == "banks").all()

# Tambahan class untuk normalisasi sub-sector
class TestNormalizeSubsector:
    def test_pretty_name(self):
        assert fetcher._normalize_subsector("Banks") == "banks"

    def test_pretty_name_ampersand_comma(self):
        assert fetcher._normalize_subsector("Oil, Gas & Coal") == "oil-gas-coal"

    def test_long_pretty_name(self):
        assert fetcher._normalize_subsector(
            "Pharmaceuticals & Health Care Research"
        ) == "pharmaceuticals-health-care-research"

    def test_slug_passthrough(self):
        assert fetcher._normalize_subsector("banks") == "banks"

    def test_none_passthrough(self):
        assert fetcher._normalize_subsector(None) is None