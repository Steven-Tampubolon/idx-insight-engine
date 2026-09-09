# Spesifikasi Teknis: IDX Insight Engine

1. **Versi:** 2.0 (Sprint Phase 2)
2. **Terakhir diupdate:** September 2026
3. **Hackathon:** [Sectors.app Hackathon 2026](https://hackathon.sectors.app) — Track 03: Market Intelligence

---

## 1. Deskripsi Utama

IDX Insight Engine adalah aplikasi analisis pasar saham Indonesia (IDX/BEI) berbasis web (Streamlit) yang menggabungkan tiga pendekatan analisis:

1. **Custom Stock Screener** — formula scoring kustom dengan bobot metrik yang bisa disesuaikan
2. **Anomaly Dashboard** — deteksi statistik saham yang menyimpang dari peer sub-sektornya
3. **AI Query Agent** — natural language interface berbahasa Indonesia dengan agentic tool calling

Seluruh data finansial bersumber dari **Sectors REST API v2** sebagai sumber data utama.

---

## 2. Stack Teknologi

| Komponen | Teknologi | Versi |
|---|---|---|
| UI Framework | Streamlit | ≥1.35 |
| AI Agent | Groq API (`qwen/qwen3.8-27b`) | — |
| AI Explainer | Groq API (`openai/gpt-oss-20b`) | — |
| Data Source | Sectors REST API v2 | v2 |
| Local Cache | SQLite | — |
| Data Processing | Pandas, NumPy, SciPy | — |
| Visualisasi | Plotly | ≥5.18 |

---

## 3. Struktur Proyek

```
idx-insight-engine/
├── app.py                    # Entry point — cek cache, routing
├── core/
│   ├── agent.py              # Groq agentic loop + 4 tools
│   ├── anomaly.py            # Z-score detection per sub-sektor
│   ├── explainer.py          # Narasi anomali via Groq
│   └── screener.py           # Formula scoring engine
├── data/
│   ├── fetcher.py            # Sectors API v2 client + SQLite cache layer
│   └── init_cache.py         # One-time initialization script
├── pages/
│   ├── 1_📊_Screener.py      # Screener UI
│   ├── 2_🔍_Anomaly.py       # Anomaly Dashboard UI
│   └── 3_🤖_AI_Query.py      # AI Chat UI
├── dev/
│   ├── check_groq.py         # Utility: cek model Groq tersedia
│   ├── enrich_roe_yield.py   # Utility: enrich cache dengan ROE + yield
│   └── test_logic.py         # Utility: test fetcher langsung
├── docs/
│   └── specification.md      # Dokumen ini
├── .env.example
├── .streamlit/
│   └── secrets.toml.example
└── requirements.txt
```

---

## 4. Komponen Core

### 4.1 `core/agent.py` — AI Agent

Mengelola interaksi dengan Groq API menggunakan **manual tool-calling loop** (bukan automatic function calling) untuk kontrol penuh atas iterasi.

**Model:** `qwen/qwen3.8-27b`

**Tools yang tersedia:**

| Tool | Deskripsi | Sectors Credits |
|---|---|---|
| `get_company_metrics(symbol)` | Metrik finansial satu perusahaan | 0 (dari cache) |
| `get_sector_companies(subsector)` | Daftar perusahaan per sub-sektor | 0 (dari cache) |
| `get_top_companies_by_metric(metric, subsector, n)` | Ranking perusahaan | 1 (Sectors API) |
| `get_subsector_summary(metric)` | Rata-rata metrik antar sub-sektor | 0 (dari cache) |

**Alur tool-calling loop:**
```python
for _ in range(8):  # max iterasi
    response = groq.chat(messages, tools, max_tokens=800)
    if finish_reason == "stop":
        break
    # eksekusi tool calls, append hasil, lanjut
```

### 4.2 `core/anomaly.py` — Anomaly Detection

Deteksi anomali menggunakan **z-score per sub-sektor** (bukan global) agar perbandingan adil antar peer.

**Metrik yang dianalisis:** `forward_pe`, `pb`, `roe`, `dividend_yield`

**Formula:**
```
z_score = (nilai - median_subsector) / MAD_subsector
anomali  = True jika |z_score| > threshold (default: 2.0)
```

MAD (Median Absolute Deviation) digunakan sebagai pengganti standar deviasi karena lebih robust terhadap outlier ekstrem.

### 4.3 `core/screener.py` — Formula Scoring

Membangun composite score dari beberapa metrik dengan bobot kustom.

**Normalisasi yang didukung:** Min-Max (0–1) dan Z-Score

**Formula:**
```
score = Σ (normalized_metric_i × weight_i)
```

Metrik dengan "lower is better" (PE, PB) di-invert sebelum normalisasi.

### 4.4 `core/explainer.py` — AI Narasi

Menghasilkan penjelasan 2 paragraf untuk setiap anomali yang ditemukan.

**Model:** `openai/gpt-oss-20b` (tidak menghasilkan `<think>` tags)

---

## 5. Layer Data (`data/fetcher.py`)

### Hierarki pengambilan data (cache-first):

```
get_company_details(symbol):
  1. Cek company_reports WHERE symbol = ?  → return jika ada
  2. Hit Sectors API v2 /company/report/{symbol}/
     sections: overview, valuation, financials, dividend
     → simpan ke company_reports, return hasil
```

### Tabel SQLite (`data/cache.db`):

| Tabel | Isi | Diisi oleh |
|---|---|---|
| `companies` | symbol, subsector, company_name | `init_cache.py` |
| `company_reports` | data lengkap per perusahaan (JSON) | `init_cache.py` + lazy fetch |
| `anomaly_scores` | pre-computed z-scores | `init_cache.py` (opsional) |

### Field yang diekstrak dari `company_reports`:

| Field | Sumber di API v2 |
|---|---|
| `company_name` | `company_name` |
| `sub_sector` | `overview.sub_sector` |
| `market_cap` | `overview.market_cap` |
| `last_close_price` | `overview.last_close_price` |
| `forward_pe` | `valuation.forward_pe` |
| `pe_ttm` | `valuation.historical_valuation[-1].pe` |
| `pb` | `valuation.historical_valuation[-1].pb` |
| `ps` | `valuation.historical_valuation[-1].ps` |
| `roe` | `financials.historical_financial_ratio[-1].profitability.roe` |
| `dividend_yield` | `dividend.yield_ttm` |

---

## 6. Endpoints Sectors API v2 yang Digunakan

| Endpoint | Digunakan untuk | Credits |
|---|---|---|
| `GET /v2/subsectors/` | Ambil slug subsector valid | 1 |
| `GET /v2/companies/` | List perusahaan per subsector | 1 per subsector |
| `GET /v2/company/report/{symbol}/` | Detail + metrik perusahaan | 1 per section |

**Sections yang di-fetch:** `overview`, `valuation`, `financials`, `dividend` = **4 credits per perusahaan**

---

## 7. Strategi Hemat API Credits

```
init_cache (jalankan sekali):
  /v2/subsectors/          →   1 credit
  /v2/companies/ × 20     →  ~20 credits
  /v2/company/report/ × N →  ~4N credits (4 sections)

Runtime Screener/Anomaly  →   0 credits (SQLite only)
Runtime AI Query          →   0 credits (SQLite only)
                              kecuali symbol baru → 4 credits lazy fetch
```

---

## 8. Ketergantungan pada Sectors API

Aplikasi ini **tidak bisa berjalan** tanpa Sectors API karena:

1. `init_cache.py` membutuhkan `SECTORS_API_KEY` untuk mengisi database
2. `get_top_companies_by_metric` memanggil `/v2/companies/` secara langsung
3. Lazy fetch di `get_company_details` memanggil `/v2/company/report/{symbol}/` untuk symbol baru

Jika `SECTORS_API_KEY` dihapus dan `data/cache.db` dikosongkan → seluruh app lumpuh.
