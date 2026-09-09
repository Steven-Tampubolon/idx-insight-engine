# dev/test_logic.py
"""
Script debug untuk test get_company_details() secara langsung.
Jalankan dari root: python dev/test_logic.py BMRI
"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from data.fetcher import get_company_details

if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BMRI"
    print(f"Testing get_company_details('{symbol}')...")
    result = get_company_details(symbol)
    print(json.dumps(result, indent=2, ensure_ascii=False))