#!/usr/bin/env bash
# TubeDigest — macOS Launcher
# Double-click this file to start TubeDigest in Docker Desktop.

set -euo pipefail

# cd to the directory containing this script (required for .command files)
cd "$(dirname "$0")"

echo "==============================="
echo "  TubeDigest Launcher"
echo "==============================="
echo ""

# ── [1/6] Check Docker Desktop is installed ──────────────────────
echo "[1/6] Checking Docker Desktop..."
if ! command -v docker &>/dev/null; then
    echo ""
    echo "ERROR: Docker Desktop is not installed."
    echo "Download it from https://www.docker.com/products/docker-desktop/"
    echo ""
    echo "Press any key to exit..."
    read -rsn1
    exit 1
fi
echo "      Docker found."

# ── [2/6] Start Docker Desktop if not running ────────────────────
echo "[2/6] Ensuring Docker Desktop is running..."
if ! docker info &>/dev/null; then
    echo "      Starting Docker Desktop..."
    open -a Docker
    # Wait up to 120s for Docker to be ready
    elapsed=0
    while ! docker info &>/dev/null; do
        if [ "$elapsed" -ge 120 ]; then
            echo ""
            echo "ERROR: Docker Desktop did not start within 120 seconds."
            echo "Please start Docker Desktop manually and try again."
            echo ""
            echo "Press any key to exit..."
            read -rsn1
            exit 1
        fi
        sleep 2
        elapsed=$((elapsed + 2))
        printf "\r      Waiting for Docker... %ds" "$elapsed"
    done
    echo ""
fi
echo "      Docker is running."

# ── [3/6] Create .env from .env.example if missing ───────────────
echo "[3/6] Checking configuration..."
if [ ! -f .env ] && [ -f .env.example ]; then
    cp .env.example .env
    echo "      Created .env from .env.example"
    echo "      Edit .env to add your API keys if needed."
else
    echo "      Configuration OK."
fi

# Read PORT from .env (default 5555)
PORT=5555
if [ -f .env ]; then
    env_port=$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]' || true)
    if [ -n "$env_port" ]; then
        PORT="$env_port"
    fi
fi

# ── [4/6] Start Claude proxy if claude CLI is available ──────────
echo "[4/6] Checking Claude Code CLI..."
if command -v claude &>/dev/null; then
    # Kill any existing proxy
    pkill -f 'python.*claude_proxy\.py' 2>/dev/null || true
    if [ -f claude_proxy.py ]; then
        python claude_proxy.py &
        CLAUDE_PROXY_PID=$!
        echo "      Claude proxy started (PID $CLAUDE_PROXY_PID)"
    else
        echo "      claude_proxy.py not found, skipping."
    fi
else
    echo "      Claude CLI not installed, skipping proxy."
fi

# ── [5/6] Build and start the container ──────────────────────────
echo "[5/6] Building and starting TubeDigest (this may take a minute on first run)..."
docker compose up --build -d

# Wait for container to be healthy (up to 120s)
echo "      Waiting for container to be ready..."
elapsed=0
while true; do
    health=$(docker inspect --format='{{.State.Health.Status}}' tubedigest 2>/dev/null || echo "starting")
    if [ "$health" = "healthy" ]; then
        break
    fi
    if [ "$elapsed" -ge 120 ]; then
        echo ""
        echo "WARNING: Container did not become healthy within 120 seconds."
        echo "         It may still be starting. Check: docker logs tubedigest"
        break
    fi
    sleep 2
    elapsed=$((elapsed + 2))
    printf "\r      Waiting for healthy status... %ds" "$elapsed"
done
echo ""

# ── [6/6] Open in browser ────────────────────────────────────────
echo "[6/6] Opening TubeDigest in your browser..."
open "http://localhost:$PORT"

echo ""
echo "==============================="
echo "  TubeDigest is running!"
echo "  http://localhost:$PORT"
echo ""
echo "  To stop: double-click stop.command"
echo "  Or run:  docker compose down"
echo "==============================="
echo ""
echo "Press any key to close this window..."
read -rsn1
