# IDX Insight Engine — Architecture Decision Records

Dokumen ini menjelaskan keputusan desain utama dan alasannya.

---

## 1. Mengapa SQLite, bukan live API call setiap request?

Sectors API v2 mengenakan biaya per request (4 credits per company report).
Dengan ~900 perusahaan IDX, live API setiap page load tidak feasible.

Solusi: one-time init (`python -m data.init_cache`) → isi SQLite cache → semua
operasi runtime baca dari SQLite (0 credits). Hanya `get_company_details()` yang
lazy-fetch dari API untuk perusahaan yang belum di-cache, dengan auto-cache setelah
fetch pertama.

Trade-off: data bukan real-time. Untuk analisis fundamental (PE, ROE, PB), data
yang di-refresh mingguan sudah cukup akurat — tidak seperti data harga yang butuh detik.

---

## 2. Mengapa manual tool-calling loop, bukan `enable_automatic_function_calling`?

Groq SDK mendukung automatic function calling, tapi kami memilih manual loop karena:

1. **Kontrol iterasi**: bisa set batas maksimum (8 iterasi) untuk mencegah infinite loop
   jika model salah memilih tool.
2. **Logging transparan**: setiap tool call dicatat ke `_tool_log` via side-effect,
   sehingga UI bisa menampilkan "Agent memanggil X, Y, Z" secara real-time.
3. **Error isolation**: jika satu tool call gagal, loop bisa lanjut atau berhenti
   dengan pesan yang jelas — tidak di-swallow oleh SDK.

---

## 3. Mengapa z-score dihitung per sub-sektor, bukan global?

Z-score global akan membandingkan bank dengan perusahaan tambang — tidak relevan.
PE ratio 15x normal untuk bank, tapi sangat mahal untuk FMCG.

Dengan z-score per sub-sektor (`groupby("sub_sector")`), anomali yang terdeteksi
benar-benar bermakna: perusahaan yang menyimpang dari peer industri yang sama.

Syarat minimum: sub-sektor harus punya ≥ 3 perusahaan agar z-score valid secara
statistik. Sub-sektor dengan < 3 peers di-skip otomatis di `core/anomaly.py`.

---

## 4. Mengapa model berbeda untuk Agent dan Explainer?

| Komponen | Model | Alasan |
|---|---|---|
| Agent (`core/agent.py`) | `qwen/qwen3.8-27b` | Kuat di tool-calling dan structured reasoning |
| Explainer (`core/explainer.py`) | `openai/gpt-oss-20b` | Lebih natural untuk narasi panjang Bahasa Indonesia |

Keduanya di-host di Groq — latensi rendah, tidak perlu API key terpisah.

---

## 5. Mengapa ROE tidak tersedia untuk semua perusahaan?

Sectors API v2 memisahkan data valuasi (`sections=valuation`) dan data finansial
(`sections=financials`). Pada init awal, hanya `overview,valuation` yang di-fetch
untuk menghemat credits. Enrichment section `financials,dividend` dilakukan via
`dev/enrich_roe_yield.py` untuk menambahkan ROE dan yield ke company_reports.

Script enrichment berhenti di tengah akibat keterbatasan credits, sehingga ~94 dari
162 company_reports sudah punya data ROE, sisanya null. UI sudah didesain untuk
handle null gracefully (blank, bukan error).

---

## 6. Struktur cache (SQLite)
```
data/cache.db
├── companies — data screener per subsector (symbol, basic metrics)
├── company_reports — full report per company (overview + valuation + financials)
└── anomaly_scores — pre-computed z-score saat init (dipakai Anomaly Dashboard)
```


`get_all_companies()` melakukan LEFT JOIN antara `companies` dan `company_reports`,
dengan prioritas: data dari `company_reports` (lebih lengkap) menimpa data dari
`companies` (lebih basic), kecuali untuk field yang null di `company_reports`.