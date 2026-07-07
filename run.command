#!/bin/bash
# Double-click to start the TI Cross-Reference tool.
cd "$(dirname "$0")"
echo "Setting up dependencies (first run only)…"
python3 -m pip install -q -r requirements.txt 2>/dev/null \
  || python3 -m pip install -q --user -r requirements.txt 2>/dev/null \
  || python3 -m pip install -q --break-system-packages -r requirements.txt
echo ""
echo "Starting the TI Cross-Reference tool…"
python3 app.py
