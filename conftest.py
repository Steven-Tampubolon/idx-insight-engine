# conftest.py
import sys
import os

# Tambahkan root project ke sys.path agar 'core', 'data', dll. bisa di-import
sys.path.insert(0, os.path.dirname(__file__))