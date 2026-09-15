#!/bin/bash
pip install openpyxl pdfplumber python-docx 2>/dev/null
python /tests/sop_verifier.py
python /tests/test_verifier_regressions.py
