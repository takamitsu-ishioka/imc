#!/usr/bin/env bash
# Pull the messages posted to one Teams channel since <since>, replies included
# (read only). This is "go and look" (pull), unlike a flow triggered by new
# messages (push).
# <team> and <channel> are display names exactly as imc_teams_channel_list.sh
# prints them. <since> is ISO 8601; without a time zone it is local time (JST).
# tsv columns: posted_at, team, channel, from, addressed_to_me, reply_to, id,
# text, url. Oldest first. Needs a prior imc_teams_auth.sh login.
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <team> <channel> <since> <tsv|json>" >&2
  echo "example: $SCRIPT_NAME '全従業員' '勤怠連絡' 2026-10-15 tsv" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
  echo "Next: run $SCRIPT_DIR/imc_teams_channel_list.sh tsv to see the exact names." >&2
}

if [ "$#" -ne 4 ]; then
  usage "Wrong number of arguments"
  exit 1
fi
case "$4" in
  tsv|json) ;;
  *) usage "Format must be tsv or json: $4"; exit 1 ;;
esac
if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ]; then
  usage "Team, channel and since must not be empty"
  exit 1
fi

exec python3 "$SCRIPT_DIR/imc_teams_message_list.py" "$1" "$2" "$3" "$4"
