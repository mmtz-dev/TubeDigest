#!/usr/bin/env bash
# TubeDigest — macOS Shutdown
# Double-click this file to stop TubeDigest.

set -euo pipefail

# cd to the directory containing this script (required for .command files)
cd "$(dirname "$0")"

echo "==============================="
echo "  Stopping TubeDigest..."
echo "==============================="
echo ""

docker compose down

echo ""
echo "==============================="
echo "  TubeDigest has been stopped."
echo "==============================="
echo ""
echo "Press any key to close this window..."
read -rsn1
