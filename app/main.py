import subprocess
import sys
import signal
import time
import os

backend_process = None


def start_backend():
    global backend_process

    print("Starting backend...")

    backend_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--ws-max-size",
            "3500000",
            "--port",
            "8000",
        ]
    )

    print(f"Backend started with PID {backend_process.pid}")


def cleanup():
    global backend_process

    print("\nShutting down application...")

    if backend_process and backend_process.poll() is None:
        print(f"Stopping backend (PID: {backend_process.pid})...")
        backend_process.terminate()

        try:
            backend_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("Force killing backend...")
            backend_process.kill()

    print("Cleanup complete.")


def signal_handler(sig, frame):
    cleanup()
    sys.exit(0)


def start_frontend():
    print("Starting frontend...")
    subprocess.call([sys.executable, "frontend/main.py"])


def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        start_backend()
        time.sleep(2)  # give backend time to start
        start_frontend()
    finally:
        cleanup()


if __name__ == "__main__":
    main()
