#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$script_dir/load-env.sh"
load_jellyfin_env "$script_dir/.env"

required_variables=(PUID PGID MEDIA_ROOT MEDIA_UUID MEDIA_DRIVE_ROOT)
for variable in "${required_variables[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    echo "ERRO: $variable nao esta definido." >&2
    exit 1
  fi
done

if [[ ! "$PUID" =~ ^[0-9]+$ || ! "$PGID" =~ ^[0-9]+$ ]]; then
  echo "ERRO: PUID e PGID devem ser identificadores numericos." >&2
  exit 1
fi

for media_path in "$MEDIA_ROOT" "$MEDIA_DRIVE_ROOT"; do
  if [[ "$media_path" != /* || "$media_path" == *:* ]]; then
    echo "ERRO: os caminhos de midia devem ser absolutos e nao podem conter dois-pontos." >&2
    exit 1
  fi
done

mounted_uuid="$(findmnt -n -o UUID -T "${MEDIA_ROOT:-/caminho/inexistente}" 2>/dev/null || true)"
if [[ -z "${MEDIA_ROOT:-}" || -z "${MEDIA_UUID:-}" || "$mounted_uuid" != "$MEDIA_UUID" ]]; then
  echo "ERRO: o HD de midia (UUID ${MEDIA_UUID:-nao definido}) nao esta montado em ${MEDIA_ROOT:-nao definido}." >&2
  exit 1
fi

if [[ ! -d "$MEDIA_ROOT/series" || ! -d "$MEDIA_ROOT/filmes" ]]; then
  echo "ERRO: o HD montado nao contem as pastas series e filmes do Archeion Stream." >&2
  exit 1
fi

if [[ ! -d "$MEDIA_DRIVE_ROOT" ]]; then
  echo "ERRO: a biblioteca externa nao existe em $MEDIA_DRIVE_ROOT." >&2
  exit 1
fi

docker compose --env-file "$script_dir/.env" -f "$script_dir/docker-compose.yml" up -d --force-recreate
