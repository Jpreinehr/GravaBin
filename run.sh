#!/usr/bin/env bash
# Inicia o GravaBin usando o virtualenv local.
set -e
cd "$(dirname "$0")"

if [ -d ".venv" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

exec python3 gravabin.py "$@"
