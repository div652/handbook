#!/bin/bash
set -euo pipefail

pip install openpyxl pdfplumber python-docx 2>/dev/null
python -m unittest discover -s /tests -p 'test_*.py'
python /tests/sop_verifier.py
