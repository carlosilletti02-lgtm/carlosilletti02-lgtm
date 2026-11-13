#!/bin/bash
# Doppio clic: apre la finestra di Carta OCR V6 (tutto in locale, nessuna rete).
cd "$(dirname "$0")" || exit 1
PY="$HOME/Library/Application Support/CartaOCR/runtime/bin/python3"
if [ ! -x "$PY" ]; then echo "Non trovo il Python di Carta OCR: $PY"; read -r -p "Premi invio per chiudere"; exit 1; fi
exec "$PY" -B frontend_v6.py "$@"
