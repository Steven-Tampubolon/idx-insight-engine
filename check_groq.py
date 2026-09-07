import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

print("🔍 Memeriksa model yang tersedia di Groq API Key Anda...\n")
try:
    models = client.models.list()
    for m in models.data:
        print(f"✅ Model ID: {m.id}")
except Exception as e:
    print(f"❌ Gagal mengambil daftar model: {e}")