@echo off
title Arbaeen RAG Web (debug)
cd /d "%~dp0"
echo Starting with visible console (logs appear here)...
echo Then open: http://localhost:8501
echo.
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8501
pause
