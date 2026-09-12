# pages/3_🤖_AI_Query.py
import streamlit as st
import importlib
import core.agent as _agent_mod
importlib.reload(_agent_mod)
run_query = _agent_mod.run_query

st.set_page_config(page_title="AI Query — IDX Insight Engine",
                   page_icon="🤖", layout="wide")

st.title("🤖 AI Query")

st.caption("Tanya apa saja tentang saham IDX · Groq Qwen 3.8B + Sectors API v2")

# ── Session state ─────────────────────────────────────────────────────────────
if "messages"      not in st.session_state: st.session_state.messages      = []
if "pending_query" not in st.session_state: st.session_state.pending_query = None

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("💬 Sesi Chat")
    if st.button("🗑️ Hapus riwayat", use_container_width=True):
        st.session_state.messages      = []
        st.session_state.pending_query = None
        st.rerun()

    st.divider()
    st.markdown("**Tools tersedia:**")
    st.markdown(
        "- `get_company_metrics` — data satu saham\n"
        "- `get_sector_companies` — daftar per sub-sektor\n"
        "- `get_top_companies_by_metric` — ranking berdasarkan metrik\n"
        "- `get_subsector_summary` — perbandingan antar sub-sektor"
    )
    st.caption("Semua baca dari SQLite cache")

# ── Ambil pending query (dari tombol suggested) ───────────────────────────────
pending = st.session_state.pending_query
if pending:
    st.session_state.pending_query = None   # langsung reset

# ── Suggested queries (hanya tampil saat chat kosong & tidak ada pending) ──────
SUGGESTED = [
    "Bandingkan PE ratio BBCA, BMRI, dan BBRI",
    "Sub-sektor mana yang rata-rata PB-nya paling murah?",
    "Tampilkan 5 saham dengan market cap terbesar di IDX",
    "Saham sektor banks mana yang forward PE-nya paling rendah?",
]

if not st.session_state.messages and not pending:
    st.markdown("### 💡 Coba pertanyaan ini:")
    col1, col2 = st.columns(2)
    for i, q in enumerate(SUGGESTED):
        if (col1 if i % 2 == 0 else col2).button(q, key=f"s_{i}",
                                                   use_container_width=True):
            st.session_state.pending_query = q
            st.rerun()
    st.divider()

# ── Tampilkan riwayat chat ────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and msg.get("tool_log"):
            with st.expander(f"🔧 {len(msg['tool_log'])} tool call(s) — klik untuk lihat"):
                for call in msg["tool_log"]:
                    st.code(call, language="")

# ── Proses input (typed atau dari pending) ────────────────────────────────────
typed_input = st.chat_input("Tanya tentang saham IDX...")
query       = pending or typed_input

if query:
    # Simpan & tampilkan pesan user
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    # Panggil Groq Agent & tampilkan respons
    with st.chat_message("assistant"):
        with st.spinner("Groq Agent sedang menganalisis... ⏳"):
            answer, tool_log = run_query(query)

        st.markdown(answer)

        if tool_log:
            with st.expander(
                f"🔧 {len(tool_log)} tool call(s) — klik untuk lihat",
                expanded=True,     # expanded=True agar terlihat di video demo
            ):
                for call in tool_log:
                    st.code(call, language="")
        else:
            st.caption("ℹ️ Query dijawab dari pengetahuan model — tidak ada tool yang dipanggil.")

    # Simpan ke riwayat
    st.session_state.messages.append({
        "role"     : "assistant",
        "content"  : answer,
        "tool_log" : tool_log,
    })