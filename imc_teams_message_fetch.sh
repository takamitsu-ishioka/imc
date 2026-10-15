#!/usr/bin/env bash
# Pull the messages posted since <since> to every channel listed on stdin, in
# one run (read only). The list is "team<TAB>channel" per line, display names
# exactly as imc_teams_channel_list.sh prints them; blank lines and lines
# starting with # are ignored. Keep your own list in teams_channels.local.tsv
# (gitignored: team and channel names say where you work), copied from
# teams_channels.local.tsv.template.
# <since> is ISO 8601; without a time zone it is local time (JST).
# Output: the same records as imc_teams_message_list.sh, all channels merged,
# oldest first. A channel that cannot be found is reported and skipped, and
# the exit code is then 1, after the other channels have been written.
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <since> <tsv|json> < channels.tsv" >&2
  echo "example: $SCRIPT_NAME 2026-10-15T09:00 json < $SCRIPT_DIR/teams_channels.local.tsv" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
  echo "Next: cp $SCRIPT_DIR/teams_channels.local.tsv.template $SCRIPT_DIR/teams_channels.local.tsv and edit it." >&2
}

if [ "$#" -ne 2 ]; then
  usage "Wrong number of arguments"
  exit 1
fi
case "$2" in
  tsv|json) ;;
  *) usage "Format must be tsv or json: $2"; exit 1 ;;
esac
if [ -z "$1" ]; then
  usage "since must not be empty"
  exit 1
fi
if [ -t 0 ]; then
  usage "The channel list must come on stdin"
  exit 1
fi

exec python3 "$SCRIPT_DIR/imc_teams_message_fetch.py" "$1" "$2"
