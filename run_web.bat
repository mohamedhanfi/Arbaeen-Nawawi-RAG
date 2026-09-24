@echo off
title Arbaeen RAG Web
cd /d "%~dp0"
start "" /min pythonw -m streamlit run web_app.py --server.headless true --server.port 8501 --server.address localhost
timeout /t 12 /nobreak >nul
start http://localhost:8501
