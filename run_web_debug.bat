@echo off
title Arbaeen RAG Web (debug)
cd /d "%~dp0"
echo Starting with visible console (logs appear here)...
echo Then open: http://localhost:8501
echo.
python -m streamlit run web_app.py --server.port 8501 --server.address localhost
pause
