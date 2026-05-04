#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${MIGRATION_DATABASE_URL:-}" ]]; then
  export DATABASE_URL="${MIGRATION_DATABASE_URL}"
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL 未设置。请提供 DATABASE_URL 或 MIGRATION_DATABASE_URL。" >&2
  exit 1
fi

export FLASK_APP="${FLASK_APP:-src.index}"
export REQUIRE_PRODUCTION_ENV=false

echo "== Alembic heads =="
uv run flask db heads

echo "== Preparing legacy migration state =="
uv run python scripts/prepare-legacy-migration-state.py

echo "== Current revision (before) =="
uv run flask db current || true

echo "== Running upgrade =="
uv run flask db upgrade

echo "== Current revision (after) =="
uv run flask db current
