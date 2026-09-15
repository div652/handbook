#!/bin/bash
pip install openpyxl pdfplumber python-docx 2>/dev/null
python /tests/test_closure_date_verifier.py
python /tests/test_famli_referral.py
python /tests/test_non_applicability_verifier.py
python /tests/test_fresh_rca_regressions.py
python /tests/sop_verifier.py
