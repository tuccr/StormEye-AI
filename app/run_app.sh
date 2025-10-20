#!/bin/bash
set -e

# --- Activate virtual environment ---
source venv/bin/activate

# --- Start FastAPI backend in background ---
echo "Starting backend..."
uvicorn backend.main:app --ws-max-size 3500000 --port 8000 &
BACKEND_PID=$!

# --- Setup cleanup trap ---
cleanup() {
  echo ""
  echo "Shutting down application..."

  # Kill the backend and all its children
  if ps -p $BACKEND_PID > /dev/null 2>&1; then
    echo "Stopping backend (PID: $BACKEND_PID)..."
    pkill -P $BACKEND_PID || true      # kill backend children
    kill $BACKEND_PID 2>/dev/null || true
    sleep 1
    if ps -p $BACKEND_PID > /dev/null 2>&1; then
      echo "Force killing backend..."
      kill -9 $BACKEND_PID 2>/dev/null || true
    fi
  fi

  # Kill any stray uvicorn processes just in case
  pkill -f "uvicorn backend.main:app" 2>/dev/null || true

  echo "Cleanup complete."
}
trap cleanup EXIT INT TERM

# --- Start PyQt frontend ---
echo "Starting frontend..."
python frontend/main.py || true

# --- Wait for cleanup when frontend closes ---
cleanup



