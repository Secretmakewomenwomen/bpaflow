#!/usr/bin/env bash
set -euo pipefail

PG_CONFIG_BIN="${PG_CONFIG_BIN:-/Library/PostgreSQL/18/bin/pg_config}"
PGVECTOR_VERSION="${PGVECTOR_VERSION:-0.8.1}"

if [[ ! -x "${PG_CONFIG_BIN}" ]]; then
  echo "pg_config not found: ${PG_CONFIG_BIN}" >&2
  exit 1
fi

tmpdir="$(mktemp -d /tmp/pgvector.XXXXXX)"
trap 'rm -rf "${tmpdir}"' EXIT

cd "${tmpdir}"
curl -L "https://github.com/pgvector/pgvector/archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz" -o pgvector.tar.gz
tar -xzf pgvector.tar.gz --strip-components=1
make PG_CONFIG="${PG_CONFIG_BIN}"
sudo make PG_CONFIG="${PG_CONFIG_BIN}" install

echo "pgvector ${PGVECTOR_VERSION} installed for $(\"${PG_CONFIG_BIN}\" --version)"
