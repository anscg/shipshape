#!/bin/sh
# Launcher: uses the project venv (Tk 9 + Pillow + qrcode).
cd "$(dirname "$0")" && exec ./.venv/bin/python label_app.py "$@"
