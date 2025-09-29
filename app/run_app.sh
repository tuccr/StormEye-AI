#!/bin/bash
set -e

# Activate venv
source venv/bin/activate

# Start FastAPI backend in background
uvicorn backend.main:app --reload --port 8000 &
BACKEND_PID=$!

# Start PyQt frontend
python frontend/main.py

# Kill backend when frontend closes
kill $BACKEND_PID

