#!/bin/bash
set -euo pipefail

pip install openpyxl pdfplumber python-docx 2>/dev/null
python /tests/test_verifier_regressions.py
python /tests/sop_verifier.py
