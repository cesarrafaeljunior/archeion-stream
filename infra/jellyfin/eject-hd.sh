#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
set -a
# shellcheck disable=SC1091
source "$script_dir/.env"
set +a

if [[ -z "${MEDIA_ROOT:-}" ]]; then
  echo "ERRO: MEDIA_ROOT nao esta definido." >&2
  exit 1
fi

source_device="$(findmnt -n -o SOURCE -T "$MEDIA_ROOT" 2>/dev/null || true)"
mounted_uuid="$(findmnt -n -o UUID -T "$MEDIA_ROOT" 2>/dev/null || true)"
if [[ -z "${MEDIA_UUID:-}" || "$mounted_uuid" != "$MEDIA_UUID" || -z "$source_device" || "$source_device" != /dev/* ]]; then
  echo "ERRO: nao foi encontrado um dispositivo montado para $MEDIA_ROOT." >&2
  exit 1
fi

parent_name="$(lsblk -n -o PKNAME "$source_device" | head -n 1)"
if [[ -z "$parent_name" ]]; then
  echo "ERRO: nao foi possivel identificar o disco de $source_device." >&2
  exit 1
fi

docker compose -f "$script_dir/docker-compose.yml" stop jellyfin
sync
udisksctl unmount -b "$source_device"
udisksctl power-off -b "/dev/$parent_name"

echo "HD desmontado e desligado com seguranca. Agora ele pode ser desconectado."
