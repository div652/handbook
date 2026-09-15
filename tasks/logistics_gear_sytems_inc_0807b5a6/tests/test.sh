#!/bin/bash
set -euo pipefail

pip install openpyxl pdfplumber pypdf reportlab python-docx 2>/dev/null
python /tests/sop_verifier.py
python /tests/test_evaluator_regressions.py
