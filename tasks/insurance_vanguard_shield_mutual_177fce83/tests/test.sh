#!/bin/bash
set -euo pipefail

pip install openpyxl pdfplumber python-docx 2>/dev/null
python /tests/test_hiroshi_date_range_verifier.py
python /tests/test_carlos_daily_cap_verifier.py
python /tests/test_slack_artifact_path_verifier.py
python /tests/test_hassan_rahimi_format_verifier.py
python /tests/sop_verifier.py
