#!/bin/bash
pip install openpyxl pdfplumber python-docx 2>/dev/null
python /tests/test_sop_verifier.py -q || exit 1
python /tests/sop_verifier.py
