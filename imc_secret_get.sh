#!/usr/bin/env bash
# Print the value of one variable from the .env file next to this script.
# Exists so that generated config files (mbsyncrc) can reference a secret
# through PassCmd without ever containing the secret themselves.
# Reads nothing from stdin and writes exactly one line to stdout.
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <variable_name>" >&2
  echo "example: $SCRIPT_NAME IMC_ACCOUNT_selfhosted_PASSWORD" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
  echo "Next: make sure $ENV_FILE exists, is mode 600, and defines the variable." >&2
}

if [ "$#" -ne 1 ]; then
  usage "Wrong number of arguments"
  exit 1
fi

name="$1"
if [[ ! "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  usage "Not a valid variable name: $name"
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  usage "$ENV_FILE not found"
  exit 1
fi

env_mode="$(stat -c '%a' "$ENV_FILE")"
if [ "$env_mode" != "600" ]; then
  echo "$SCRIPT_NAME: $ENV_FILE must have mode 600; actual mode is $env_mode." >&2
  echo "Next: run chmod 600 $ENV_FILE and retry." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [ -z "${!name-}" ]; then
  echo "$SCRIPT_NAME: $name is missing or empty in $ENV_FILE." >&2
  echo "Next: edit $ENV_FILE and retry." >&2
  exit 1
fi

printf '%s\n' "${!name}"
