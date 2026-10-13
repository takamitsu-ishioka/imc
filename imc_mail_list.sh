#!/usr/bin/env bash
# List messages from the notmuch index as one record per message.
# <query> is a notmuch query such as 'tag:actionable', 'date:1d..', or '*'
# for every message. <format> is tsv or json.
# Writes records to stdout and progress to stderr.
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTMUCH_CONFIG_FILE="$SCRIPT_DIR/_var/notmuch-config"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <query> <tsv|json>" >&2
  echo "example: $SCRIPT_NAME '*' tsv" >&2
  echo "example: $SCRIPT_NAME 'tag:actionable and not tag:done' json" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
  echo "Next: run $SCRIPT_DIR/initialize.sh if $NOTMUCH_CONFIG_FILE does not exist yet." >&2
}

if [ "$#" -ne 2 ]; then
  usage "Wrong number of arguments"
  exit 1
fi

query="$1"
output_format="$2"

case "$output_format" in
  tsv|json) ;;
  *) usage "Format must be tsv or json: $output_format"; exit 1 ;;
esac

if [ -z "$query" ]; then
  usage "Query is empty"
  exit 1
fi

if [ ! -f "$NOTMUCH_CONFIG_FILE" ]; then
  usage "$NOTMUCH_CONFIG_FILE not found"
  exit 1
fi

exec python3 "$SCRIPT_DIR/imc_mail_list.py" "$NOTMUCH_CONFIG_FILE" "$query" "$output_format"
