#!/usr/bin/env bash
# List the Teams teams and channels you are a member of (read only).
# tsv columns: team, channel, membership type, team id, channel id.
# Needs a prior imc_teams_auth.sh login.
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <tsv|json>" >&2
  echo "example: $SCRIPT_NAME tsv" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
  echo "Next: run $SCRIPT_DIR/imc_teams_auth.sh login first if you have not signed in." >&2
}

if [ "$#" -ne 1 ]; then
  usage "Wrong number of arguments"
  exit 1
fi
case "$1" in
  tsv|json) ;;
  *) usage "Format must be tsv or json: $1"; exit 1 ;;
esac

exec python3 "$SCRIPT_DIR/imc_teams_channel_list.py" "$1"
