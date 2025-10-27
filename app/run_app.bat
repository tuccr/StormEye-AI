@echo off

echo Starting FastAPI backend...
start cmd /k "uvicorn backend.main:app --ws-max-size 3500000 --port 8000"

echo Starting PyQt frontend...
python frontend\main.py
