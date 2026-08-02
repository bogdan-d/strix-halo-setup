#!/usr/bin/env bash
# Self-contained acceptance gate. The ONLY test command you need. Exit 0 = done.
cd "$(dirname "$0")"
if [ ! -f pacman.html ]; then echo "FAIL  pacman.html does not exist yet"; exit 1; fi
python3 gate.py pacman.html
