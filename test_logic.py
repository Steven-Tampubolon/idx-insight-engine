import json
from poc_agent import get_company_metrics

# Tes langsung fungsinya tanpa melibatkan chat Gemini
if __name__ == "__main__":
    print("Menguji ekstraksi data BMRI...")
    result = get_company_metrics("BMRI")
    print(json.dumps(json.loads(result), indent=2))