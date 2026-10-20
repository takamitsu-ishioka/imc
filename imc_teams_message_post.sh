#!/usr/bin/env bash
# Post the text on stdin to one Teams channel as yourself: a new thread
# (<reply_to> = NEW) or a reply in an existing thread (<reply_to> = the id of
# the thread's first message, as imc_teams_message_list.sh prints it in the id
# column, or as this script printed it when it posted the thread).
# <team> and <channel> are display names exactly as imc_teams_channel_list.sh
# prints them. Line breaks in the text are kept.
# Prints the team, channel, thread and text on stderr before posting, always.
# Output: one TSV line: posted_at, id, reply_to, url.
# Needs a prior imc_teams_auth.sh login (one sign-in reads and posts).
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <team> <channel> <reply_to|NEW> [--dry-run] [--confirm] < text" >&2
  echo "example: echo 'Starting work.' | $SCRIPT_NAME 'All staff' 'Attendance' NEW --confirm" >&2
  echo "example: echo 'Taking a break.' | $SCRIPT_NAME 'All staff' 'Attendance' 1700000000000 --confirm" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
  echo "Next: run $SCRIPT_DIR/imc_teams_channel_list.sh tsv to see the exact names." >&2
}

mode="apply"
confirm="no-confirm"
args=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) mode="dry-run" ;;
    --confirm) confirm="confirm" ;;
    --*) usage "Unknown option: $arg"; exit 1 ;;
    *) args+=("$arg") ;;
  esac
done

if [ "${#args[@]}" -ne 3 ]; then
  usage "Wrong number of arguments"
  exit 1
fi
if [ -z "${args[0]}" ] || [ -z "${args[1]}" ] || [ -z "${args[2]}" ]; then
  usage "Arguments must not be empty"
  exit 1
fi
if [ -t 0 ]; then
  usage "No message text on stdin"
  exit 1
fi

exec python3 "$SCRIPT_DIR/imc_teams_message_post.py" "${args[0]}" "${args[1]}" "${args[2]}" "$mode" "$confirm"
