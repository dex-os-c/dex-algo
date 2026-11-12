#!/usr/bin/env bash
# ==============================================================================
# Alpaca Quant Bot - Startup Script
# ==============================================================================
set -e

# Resolve script directory (project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================================================"
echo " Starting Alpaca Quantitative Trading Terminal"
echo " Working Directory: $SCRIPT_DIR"
echo "======================================================================"

# Check Python 3
if ! command -v python3 &>/dev/null; then
    echo "[-] Error: python3 is not installed or not in PATH."
    exit 1
fi

# Ensure .env exists from .env.example if missing
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        echo "[*] Creating .env from .env.example..."
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
        echo "[+] Created $SCRIPT_DIR/.env. Configure your keys or leave empty for mock mode."
    fi
fi

# Virtual environment handling (optional / fallback on Termux or container)
VENV_DIR="$SCRIPT_DIR/venv"
if [ -d "$VENV_DIR" ]; then
    echo "[*] Activating existing virtualenv at $VENV_DIR..."
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
elif [ -z "$PREFIX" ] && [ -z "$TERMUX_VERSION" ]; then
    # Try creating virtualenv on standard Linux desktop/servers if venv module exists
    if python3 -m venv "$VENV_DIR" 2>/dev/null; then
        echo "[+] Created virtualenv at $VENV_DIR"
        # shellcheck disable=SC1091
        source "$VENV_DIR/bin/activate"
    else
        echo "[*] Running with global/current Python environment."
    fi
else
    echo "[*] Termux / Android environment detected: using current Python environment."
fi

# Upgrade pip and install requirements if requirements.txt exists
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "[*] Checking and installing dependencies from requirements.txt..."
    python3 -m pip install -r "$SCRIPT_DIR/requirements.txt" --quiet --no-warn-script-location || {
        echo "[!] Warning: pip install encountered issues, proceeding to launch..."
    }
fi

# Export PYTHONPATH to include project root and backend
export PYTHONPATH="$SCRIPT_DIR/backend:$SCRIPT_DIR:$PYTHONPATH"

# Load default HOST and PORT from .env if present
HOST="0.0.0.0"
PORT="8000"
if [ -f "$SCRIPT_DIR/.env" ]; then
    ENV_HOST=$(grep -E '^HOST=' "$SCRIPT_DIR/.env" | cut -d '=' -f2- | tr -d ' "')
    ENV_PORT=$(grep -E '^PORT=' "$SCRIPT_DIR/.env" | cut -d '=' -f2- | tr -d ' "')
    [ -n "$ENV_HOST" ] && HOST="$ENV_HOST"
    [ -n "$ENV_PORT" ] && PORT="$ENV_PORT"
fi

echo "[+] Starting FastAPI Uvicorn Server on http://$HOST:$PORT"
echo "[+] Web Dashboard will be accessible at: http://localhost:$PORT"
echo "======================================================================"

exec uvicorn backend.server:app --host "$HOST" --port "$PORT"
