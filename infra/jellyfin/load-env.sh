#!/usr/bin/env bash

# Carrega apenas as chaves conhecidas do arquivo .env, sem executar seu conteudo.
load_jellyfin_env() {
  local env_file="$1"
  local line key value

  if [[ ! -f "$env_file" || -L "$env_file" ]]; then
    echo "ERRO: crie um arquivo .env regular a partir de .env.example." >&2
    return 1
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*$ || "$line" =~ ^[[:space:]]*# ]] && continue

    if [[ ! "$line" =~ ^([A-Z][A-Z0-9_]*)=(.*)$ ]]; then
      echo "ERRO: linha invalida em $env_file." >&2
      return 1
    fi

    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    case "$key" in
      PUID|PGID|MEDIA_ROOT|MEDIA_UUID|MEDIA_DRIVE_ROOT|JELLYFIN_BIND_ADDRESS|JELLYFIN_DISCOVERY_BIND_ADDRESS) ;;
      *)
        echo "ERRO: variavel nao permitida em $env_file: $key" >&2
        return 1
        ;;
    esac

    if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then
      value="${BASH_REMATCH[1]}"
    fi
    printf -v "$key" '%s' "$value"
    export "$key"
  done < "$env_file"
}
