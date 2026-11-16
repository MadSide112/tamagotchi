#!/usr/bin/env bash
# Migration bundle: one tar.gz with code + git history + secrets (.env) + live DB.
# Unpack on any machine, recreate venv, run. See MIGRATION.md.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p dist
OUT="dist/tamagotchi_migration_$(date +%Y%m%d_%H%M%S).tar.gz"

tar -czf "$OUT" \
  --exclude=venv \
  --exclude=bin \
  --exclude=dist \
  --exclude=__pycache__ \
  --exclude='*.pyc' \
  --exclude=.DS_Store \
  --exclude=data/tunnel_url \
  -C .. "$(basename "$PWD")"

echo "OK: $OUT ($(du -h "$OUT" | cut -f1))"
