# Spesifikasi Proyek: IDX Insight Engine

## 1. Deskripsi Utama
IDX Insight Engine adalah aplikasi berbasis web (Streamlit) untuk menganalisis saham-saham di Bursa Efek Indonesia (IDX). Aplikasi ini menggunakan data finansial yang di-cache secara lokal (SQLite) dan memiliki integrasi dengan AI (Google Gemini) untuk memberikan analisis, penyaringan, dan deteksi anomali.

## 2. Struktur Proyek
- `app.py`: Titik masuk utama (entry point) untuk Streamlit. Memeriksa keberadaan cache `data/cache.db`.
- `requirements.txt`: Daftar dependensi (streamlit, pandas, numpy, scipy, google-generativeai, plotly).
- `.env`: Konfigurasi variabel lingkungan (menyimpan `GEMINI_API_KEY`).
- `data/`: Folder manajemen data lokal. Terdapat mekanisme pengambilan data dan caching (`init_cache`).
- `core/`: Logika bisnis dan pemrosesan data.
- `pages/`: Halaman-halaman UI Streamlit.

## 3. Komponen Utama (Core)
- **`core/agent.py`**: Mengelola interaksi dengan Google Gemini (gemini-1.5-flash). Dilengkapi fitur *function calling* (tools) untuk mengambil data dari cache lokal:
  - `get_company_metrics(symbol)`: Ambil metrik finansial satu perusahaan.
  - `get_sector_companies(subsector)`: Ambil perusahaan dalam sub-sektor tertentu.
  - `get_top_by_metric(metric, n)`: Peringkat perusahaan berdasarkan metrik spesifik.
- **`core/anomaly.py`**: Mendeteksi anomali finansial menggunakan perhitungan *Z-score* dalam kelompok sub-sektor (bukan global). Metrik yang dianalisis: `forward_pe`, `pb`, `roe`, `dividend_yield`. Menghasilkan `anomaly_score` dan daftar metrik yang melewati ambang batas (threshold).
- **`core/screener.py`**: Logika pemfilteran data saham (Screener).
- **`core/explainer.py`**: Modul tambahan (kemungkinan untuk memberi penjelasan AI pada hasil analisis/anomali).

## 4. Antarmuka Pengguna (Pages)
- **`pages/1_📊_Screener.py`**: Halaman untuk menyaring dan memfilter saham berdasarkan metrik finansial.
- **`pages/2_🔍_Anomaly.py`**: Halaman untuk melihat saham-saham yang terdeteksi sebagai anomali (undervalued, overvalued, dll) berdasarkan *Z-score* di dalam sub-sektornya.
- **`pages/3_🤖_AI_Query.py`**: Halaman chat AI yang memungkinkan pengguna bertanya seputar saham IDX dalam bahasa natural, dan agen akan merespons dengan bantuan tools data lokal.

## 5. Alur Kerja Data
1. Pengguna harus menjalankan skrip `init_cache` untuk mengambil data saham dan menyimpannya di `data/cache.db`.
2. Semua fitur analisis (Screener, Anomaly) membaca data dari cache SQLite lokal ini untuk kecepatan dan menghemat kuota API.
3. Fitur AI Query tidak melakukan crawling data secara langsung, melainkan mengeksekusi tools yang membaca data dari cache lokal yang sama.
