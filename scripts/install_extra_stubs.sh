#!/usr/bin/env bash
# Copy hand-written stubs for GI libraries not covered by pygobject-stubs
# Run after `uv sync` or whenever pygobject-stubs is reinstalled.
set -euo pipefail

DEST="$(dirname "$0")/../.venv/lib/python3.12/site-packages/gi-stubs/repository"
SRC="$(dirname "$0")/../stubs/gi/repository"

for f in "$SRC"/*.pyi; do
    name="$(basename "$f")"
    cp "$f" "$DEST/$name"
    echo "Installed $name"
done
