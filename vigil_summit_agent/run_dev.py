"""
run_dev.py
----------
Sobe LP + API (porta 8080) e painel Streamlit (porta 8501) com um único comando.

Uso:
    py run_dev.py

Abra:
    LP  → http://localhost:8080
    App → http://localhost:8501
"""

import subprocess
import sys
import time
from pathlib import Path

PASTA = Path(__file__).resolve().parent
API_PORT = 8080
APP_PORT = 8501


def main() -> None:
    print("=" * 56)
    print("Vigil Summit — ambiente local")
    print(f"  LP + API : http://localhost:{API_PORT}")
    print(f"  Painel   : http://localhost:{APP_PORT}")
    print("  Ctrl+C para encerrar os dois serviços")
    print("=" * 56)

    api = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "api:app",
            "--host", "127.0.0.1", "--port", str(API_PORT),
        ],
        cwd=PASTA,
    )
    time.sleep(1.5)

    app = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.port", str(APP_PORT),
            "--server.headless", "true",
        ],
        cwd=PASTA,
    )

    try:
        app.wait()
    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        for proc in (app, api):
            if proc.poll() is None:
                proc.terminate()
        print("Serviços finalizados.")


if __name__ == "__main__":
    main()
