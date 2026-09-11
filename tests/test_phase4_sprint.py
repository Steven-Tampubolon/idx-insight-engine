# tests/test_phase4_sprint.py
"""
Unit tests untuk Sprint Phase 4.
Semua test berjalan offline — tidak ada Sectors API call, tidak ada Groq call.
Jalankan: pytest tests/test_phase4_sprint.py -v
"""
import json
import math
import unittest
from unittest.mock import patch, MagicMock

import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — fake DataFrame yang mewakili output get_all_companies()
# ─────────────────────────────────────────────────────────────────────────────
def _make_df():
    return pd.DataFrame([
        {"symbol": "BBCA", "company_name": "Bank BCA",        "sub_sector": "banks",
         "pe_ttm": 22.1, "forward_pe": 20.5, "roe": 18.2, "dividend_yield": 2.1, "pb": 4.5, "market_cap": 900e12},
        {"symbol": "BMRI", "company_name": "Bank Mandiri",    "sub_sector": "banks",
         "pe_ttm": 11.3, "forward_pe": 10.8, "roe": 16.4, "dividend_yield": 4.5, "pb": 2.1, "market_cap": 450e12},
        {"symbol": "TLKM", "company_name": "Telkom",          "sub_sector": "telecom",
         "pe_ttm": 15.0, "forward_pe": 14.0, "roe": None,  "dividend_yield": None, "pb": 3.0, "market_cap": 300e12},
        {"symbol": "ADRO", "company_name": "Adaro Energy",    "sub_sector": "coal",
         "pe_ttm": 5.2,  "forward_pe": 4.9,  "roe": 30.1, "dividend_yield": 8.0, "pb": 1.1, "market_cap": 150e12},
    ])


# ─────────────────────────────────────────────────────────────────────────────
# TASK 1 — _get_sector_companies
# ─────────────────────────────────────────────────────────────────────────────
class TestGetSectorCompanies(unittest.TestCase):

    def _call(self, subsector: str) -> dict | list:
        """Patch get_all_companies dan panggil fungsi langsung."""
        with patch("core.agent.get_all_companies", return_value=_make_df()):
            from core.agent import _get_sector_companies
            return json.loads(_get_sector_companies(subsector))

    def test_returns_financial_metrics(self):
        """Output harus mengandung pe_ttm dan roe, bukan hanya symbol."""
        result = self._call("banks")
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)
        first = result[0]
        self.assertIn("pe_ttm", first, "Field pe_ttm tidak ada di output")
        self.assertIn("roe",    first, "Field roe tidak ada di output")
        self.assertIn("symbol", first)
        self.assertIn("company_name", first)

    def test_exact_match_case_insensitive(self):
        """'Banks' dan 'banks' dan 'BANKS' harus sama-sama match."""
        for variant in ("banks", "Banks", "BANKS"):
            with self.subTest(variant=variant):
                result = self._call(variant)
                self.assertIsInstance(result, list)
                self.assertTrue(len(result) >= 2)

    def test_partial_match_fallback(self):
        """'bank' (partial) harus tetap menemukan sub-sektor 'banks'."""
        result = self._call("bank")
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)

    def test_unknown_subsector_returns_error_with_suggestions(self):
        """Sub-sektor tidak dikenal harus kembalikan error + daftar tersedia."""
        result = self._call("xyz-tidak-ada")
        self.assertIsInstance(result, dict)
        self.assertIn("error",    result)
        self.assertIn("tersedia", result)
        self.assertIsInstance(result["tersedia"], list)

    def test_empty_cache_returns_error(self):
        """Jika cache kosong, harus kembalikan error message, bukan exception."""
        with patch("core.agent.get_all_companies", return_value=pd.DataFrame()):
            from core.agent import _get_sector_companies
            result = json.loads(_get_sector_companies("banks"))
        self.assertIn("error", result)

    def test_max_20_companies_returned(self):
        """Output tidak boleh lebih dari 20 perusahaan."""
        # Buat DataFrame dengan 30 perusahaan di sub-sektor yang sama
        big_df = pd.DataFrame([
            {"symbol": f"XX{i:02d}", "company_name": f"Company {i}",
             "sub_sector": "banks", "pe_ttm": i * 1.0, "forward_pe": i * 0.9,
             "roe": i * 2.0, "dividend_yield": 1.0, "pb": 1.0, "market_cap": 1e12}
            for i in range(30)
        ])
        with patch("core.agent.get_all_companies", return_value=big_df):
            from core.agent import _get_sector_companies
            result = json.loads(_get_sector_companies("banks"))
        self.assertLessEqual(len(result), 20)

    def test_no_api_call_made(self):
        """Fungsi tidak boleh memanggil Sectors API — hanya get_all_companies()."""
        with patch("core.agent.get_all_companies", return_value=_make_df()) as mock_cache, \
             patch("core.agent.get_company_details") as mock_api:
            from core.agent import _get_sector_companies
            _get_sector_companies("banks")
            mock_cache.assert_called_once()
            mock_api.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# TASK 3B — NaN guard logic (Anomaly z-score cards)
# ─────────────────────────────────────────────────────────────────────────────
class TestNaNGuardLogic(unittest.TestCase):
    """
    Test logika filtering valid_flags secara unit — tanpa Streamlit.
    Ekstrak logikanya ke fungsi murni agar bisa di-test.
    """

    @staticmethod
    def _filter_valid_flags(flags: list, row_data: dict) -> list:
        """Mirror dari logika di Anomaly.py."""
        return [
            m for m in flags
            if row_data.get(f"z_{m}") is not None
            and not math.isnan(float(row_data.get(f"z_{m}", float("nan"))))
        ]

    def test_filters_out_nan_zscore(self):
        flags    = ["pe_ttm", "roe", "dividend_yield"]
        row_data = {"z_pe_ttm": 2.5, "z_roe": float("nan"), "z_dividend_yield": None}
        result   = self._filter_valid_flags(flags, row_data)
        self.assertEqual(result, ["pe_ttm"])

    def test_keeps_valid_zscores(self):
        flags    = ["pe_ttm", "pb"]
        row_data = {"z_pe_ttm": -3.1, "z_pb": 2.2}
        result   = self._filter_valid_flags(flags, row_data)
        self.assertEqual(result, ["pe_ttm", "pb"])

    def test_all_nan_returns_empty(self):
        flags    = ["roe", "dividend_yield"]
        row_data = {"z_roe": float("nan"), "z_dividend_yield": float("nan")}
        result   = self._filter_valid_flags(flags, row_data)
        self.assertEqual(result, [])

    def test_none_value_excluded(self):
        flags    = ["pe_ttm", "roe"]
        row_data = {"z_pe_ttm": 2.0, "z_roe": None}
        result   = self._filter_valid_flags(flags, row_data)
        self.assertEqual(result, ["pe_ttm"])

    def test_zero_zscore_is_valid(self):
        """z=0.0 bukan NaN — harus tetap lolos filter."""
        flags    = ["pe_ttm"]
        row_data = {"z_pe_ttm": 0.0}
        result   = self._filter_valid_flags(flags, row_data)
        self.assertEqual(result, ["pe_ttm"])


# ─────────────────────────────────────────────────────────────────────────────
# TASK 2 — Preset logic (session state keys)
# ─────────────────────────────────────────────────────────────────────────────
class TestPresetLogic(unittest.TestCase):

    PRESETS = {
        "💎 Value Investing" : {"forward_pe": 70, "pb": 60, "roe": 80},
        "💰 Dividend Focus"  : {"dividend_yield": 80, "forward_pe": 50, "pb": 40},
        "📈 Quality Growth"  : {"roe": 80, "ps": 50, "forward_pe": 60},
    }

    def _apply_preset(self, label: str) -> dict:
        """Simulasikan klik preset → kembalikan session_state yang dihasilkan."""
        session_state = {}
        weights_preset = self.PRESETS[label]
        for metric, val in weights_preset.items():
            session_state[f"w_{metric}"] = val
        session_state["sel_metrics_preset"] = list(weights_preset.keys())
        return session_state

    def test_value_investing_sets_correct_weights(self):
        state = self._apply_preset("💎 Value Investing")
        self.assertEqual(state["w_forward_pe"], 70)
        self.assertEqual(state["w_pb"],         60)
        self.assertEqual(state["w_roe"],        80)

    def test_dividend_focus_sets_correct_metrics(self):
        state = self._apply_preset("💰 Dividend Focus")
        self.assertIn("dividend_yield", state["sel_metrics_preset"])
        self.assertEqual(state["w_dividend_yield"], 80)

    def test_quality_growth_sets_roe(self):
        state = self._apply_preset("📈 Quality Growth")
        self.assertEqual(state["w_roe"], 80)
        self.assertIn("roe", state["sel_metrics_preset"])

    def test_preset_metrics_filtered_against_avail(self):
        """
        Metrik preset yang tidak ada di DataFrame harus di-drop,
        bukan raise error (guard: [m for m in default if m in avail_mets]).
        """
        avail_mets     = ["forward_pe", "pb", "roe"]   # 'ps' tidak tersedia
        state          = self._apply_preset("📈 Quality Growth")
        default_raw    = state["sel_metrics_preset"]    # ["roe", "ps", "forward_pe"]
        default_safe   = [m for m in default_raw if m in avail_mets] or avail_mets[:3]
        self.assertNotIn("ps", default_safe)
        self.assertIn("roe",  default_safe)


if __name__ == "__main__":
    unittest.main(verbosity=2)