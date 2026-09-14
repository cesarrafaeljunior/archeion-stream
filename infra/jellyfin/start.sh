#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
set -a
# shellcheck disable=SC1091
source "$script_dir/.env"
set +a

mounted_uuid="$(findmnt -n -o UUID -T "${MEDIA_ROOT:-/caminho/inexistente}" 2>/dev/null || true)"
if [[ -z "${MEDIA_ROOT:-}" || -z "${MEDIA_UUID:-}" || "$mounted_uuid" != "$MEDIA_UUID" ]]; then
  echo "ERRO: o HD de midia (UUID ${MEDIA_UUID:-nao definido}) nao esta montado em ${MEDIA_ROOT:-nao definido}." >&2
  exit 1
fi

if [[ ! -d "$MEDIA_ROOT/series" || ! -d "$MEDIA_ROOT/filmes" ]]; then
  echo "ERRO: o HD montado nao contem as pastas series e filmes do Archeion Stream." >&2
  exit 1
fi

docker compose -f "$script_dir/docker-compose.yml" up -d --force-recreate
