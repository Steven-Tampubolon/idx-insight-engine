# tests/test_enrich_screener.py
# Jalankan dari root: python -m pytest tests/test_enrich_screener.py -v
# Semua test offline — tidak ada HTTP request.
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dev.enrich_from_screener import (  # noqa: E402
    ENRICH_FIELDS,
    _merge_screener_fields,
    _normalize_symbol,
)


class TestNormalizeSymbol:
    def test_jk_suffix(self):
        assert _normalize_symbol("bbca.jk") == "BBCA"

    def test_upper(self):
        assert _normalize_symbol("bmri") == "BMRI"

    def test_none(self):
        assert _normalize_symbol(None) == ""


class TestMergeScreenerFields:
    def test_fills_empty_fields(self):
        merged, changed = _merge_screener_fields(
            {"company_name": "Bank A"}, {"roe_ttm": 22.5, "pe_ttm": 8.2}
        )
        assert changed
        assert merged["roe_ttm"] == 22.5
        assert merged["pe_ttm"] == 8.2
        assert merged["company_name"] == "Bank A"  # field lain tidak hilang

    def test_does_not_overwrite_existing(self):
        # Data report (roe 20.1) tidak boleh ditimpa screener (22.5)
        merged, changed = _merge_screener_fields({"roe_ttm": 20.1}, {"roe_ttm": 22.5})
        assert not changed
        assert merged["roe_ttm"] == 20.1

    def test_null_in_response_ignored(self):
        merged, changed = _merge_screener_fields({}, {"roe_ttm": None})
        assert not changed
        assert "roe_ttm" not in merged

    def test_unrelated_fields_ignored(self):
        merged, changed = _merge_screener_fields(
            {"company_name": "X"}, {"symbol": "X", "company_name": "X"}
        )
        assert not changed

    def test_all_enrich_fields(self):
        new = {f: 1.0 for f in ENRICH_FIELDS}
        merged, changed = _merge_screener_fields({}, new)
        assert changed
        assert all(merged[f] == 1.0 for f in ENRICH_FIELDS)


class TestEnrichEndToEnd:
    """Simulasi enrichment penuh pada mini-cache SQLite di memory."""

    def _setup(self, tmp_path):
        db = tmp_path / "c.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE companies (symbol TEXT PRIMARY KEY, subsector TEXT, data JSON)"
        )
        conn.execute("INSERT INTO companies VALUES (?,?,?)",
                     ("BBCA", "banks", json.dumps({"company_name": "BCA"})))
        conn.execute("INSERT INTO companies VALUES (?,?,?)",
                     ("BMRI", "banks",
                      json.dumps({"company_name": "Mandiri", "roe_ttm": 19.0})))
        return conn

    def _api_rows(self):
        return [
            {"symbol": "BBCA.JK", "roe_ttm": 21.0, "pe_ttm": 9.1, "yield_ttm": 3.2},
            {"symbol": "bbca",    "roe_ttm": 99.0, "pb_mrq": 2.5},  # duplikat → skip
            {"symbol": "BMRI.JK", "roe_ttm": 18.0},                 # tidak menimpa 19.0
        ]

    def test_enrich_fills_and_preserves(self, tmp_path):
        conn = self._setup(tmp_path)
        for c in self._api_rows():
            sym = _normalize_symbol(c.get("symbol"))
            row = conn.execute(
                "SELECT data FROM companies WHERE symbol=?", (sym,)
            ).fetchone()
            if not row:
                continue
            merged, changed = _merge_screener_fields(json.loads(row[0]), c)
            if changed:
                conn.execute("UPDATE companies SET data=? WHERE symbol=?",
                             (json.dumps(merged), sym))
        conn.commit()

        b = json.loads(conn.execute(
            "SELECT data FROM companies WHERE symbol='BBCA'").fetchone()[0])
        m = json.loads(conn.execute(
            "SELECT data FROM companies WHERE symbol='BMRI'").fetchone()[0])
        assert b["roe_ttm"] == 21.0 and b["pe_ttm"] == 9.1 and b["yield_ttm"] == 3.2
        assert m["roe_ttm"] == 19.0 and "pb_mrq" not in m  # existing + duplikat aman
        conn.close()