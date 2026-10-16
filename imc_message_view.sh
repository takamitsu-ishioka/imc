#!/usr/bin/env bash
# Full-screen viewer for messages from every route (mail and Teams), in one
# terminal: the list with checkboxes on the left, the raw header (top right)
# and the body (bottom right) of the message being viewed, the keys at the
# bottom. One pane has the focus (Tab cycles list/header/body, Left = list,
# Right = body); Up/Down, PgUp/PgDn and Home/End move within that pane.
# p opens/closes the right panes (closed, the list takes the whole width;
# v or Right opens them again).
# Space checks a message; check, move, check checks the whole range;
# v views the focused message, d deletes the
# checked messages (or the focused one), u undoes the last delete.
# "Delete" tags the message deleted in notmuch; the file stays in _var/maildir
# (imc never deletes local mail), and tag:deleted is hidden from searches.
# Viewing a message marks it read.
# <query> is a notmuch query, or NEW for every unread message (tag:unread).
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <NEW|query>" >&2
  echo "example: $SCRIPT_NAME NEW" >&2
  echo "example: $SCRIPT_NAME 'tag:unread and not folder:/teams-.*/'" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
}

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  usage "Wrong number of arguments"
  exit 1
fi
if [ ! -f "$SCRIPT_DIR/_var/notmuch-config" ]; then
  usage "$SCRIPT_DIR/_var/notmuch-config not found"
  echo "Next: run $SCRIPT_DIR/initialize.sh first." >&2
  exit 1
fi
if [ ! -t 0 ] || [ ! -t 1 ]; then
  echo "$SCRIPT_NAME: This is a full-screen program; run it in a terminal." >&2
  exit 2
fi
query="$1"
[ "$query" = "NEW" ] && query="tag:unread"

exec python3 "$SCRIPT_DIR/imc_message_view.py" "$query"
