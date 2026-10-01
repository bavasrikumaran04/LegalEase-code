#!/bin/sh
# Render entrypoint: private FastAPI backend + public Streamlit UI in one service.
uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
exec streamlit run frontend/app.py --server.address 0.0.0.0 --server.port "${PORT:-8501}" --server.headless true
