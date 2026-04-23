#!/bin/bash

# READ ME
# If you're having issues regarding opengl when running the application using run_app.sh, use this runner script instead.
# This script will run the application without using hardware acceleration for the PyQt frontend renderer (OpenGL). 
# Using this script to run the app may lead to some performance problems when using the leaflet map UI or other interactive components.
# Ensure that xvfb is installed on your ubuntu machine before running this scripts

set -u

_CLEANED_UP=0

echo "Starting backend..."

UVICORN_ARGS=(backend.main:app --ws-max-size 3500000 --port 8000)


# Start in a dedicated process group so cleanup can terminate the whole backend tree.
setsid uvicorn "${UVICORN_ARGS[@]}" &
BACKEND_PID=$!
echo "Backend started with PID $BACKEND_PID"

cleanup() {
  if [[ "$_CLEANED_UP" -eq 1 ]]; then
    return
  fi
  _CLEANED_UP=1

  echo ""
  echo "Shutting down application..."

  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "Stopping backend process group (PGID: $BACKEND_PID)..."
    kill -- -"$BACKEND_PID" 2>/dev/null || true
    sleep 1
    if kill -0 "$BACKEND_PID" 2>/dev/null; then
      echo "Force killing backend process group..."
      kill -9 -- -"$BACKEND_PID" 2>/dev/null || true
    fi
  fi

  echo "Cleanup complete."
}
trap cleanup EXIT INT TERM

echo "Starting frontend..."

# Prefer software rendering for remote/headless Linux environments.
export QT_OPENGL="${QT_OPENGL:-software}"
export QT_QUICK_BACKEND="${QT_QUICK_BACKEND:-software}"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export QT_XCB_GL_INTEGRATION="${QT_XCB_GL_INTEGRATION:-none}"

if [[ -n "${DISPLAY:-}" ]]; then
  python frontend/main.py || true
else
  if command -v xvfb-run >/dev/null 2>&1; then
    xvfb-run -a python frontend/main.py || true
  else
    echo "No DISPLAY found and xvfb-run is not installed."
    echo "There may be issues with OpenGL or your desktop engine compatibility. Install xvfb (e.g. 'sudo apt-get install xvfb') or run in a desktop session."
  fi
fi



