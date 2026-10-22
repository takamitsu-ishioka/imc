#!/usr/bin/env bash
# Full-screen viewer for messages from every route (mail and Teams), in one
# terminal: the list with checkboxes on the left, the header (top right, MIME
# encoded words decoded, From and Subject highlighted)
# and the body (bottom right) of the message being viewed, the keys at the
# bottom. One pane has the focus (Tab cycles list/header/body, Left = list,
# Right = body); Up/Down, PgUp/PgDn and Home/End move within that pane.
# The right panes start closed, so the list takes the whole width. v opens
# them on the focused message and closes them again; Enter always shows the
# focused message (opening them if needed), and Right opens them too.
# Space checks a message; check, move, check checks the whole range;
# d deletes the
# checked messages (or the focused one), f marks their senders nonessential,
# u undoes the last delete or f.
# "Delete" tags the message deleted in notmuch; the file stays in _var/maildir
# (imc never deletes local mail), and tag:deleted is hidden from searches.
# f appends a from rule to tag_rules.local.tsv (gitignored) and re-applies the
# rules to every message, so all mail from that sender, past and future, gets
# tag:nonessential. Remove the line from that file to take it back later.
# ! flags the checked messages (or the focused one) as needing action (notmuch
# tag flagged, shown as "!" in the list; never written back to the server), or
# unflags them when all are flagged already. u undoes it.
# t opens the tag filter: each tag can be [ ] any, [+] required or [-]
# excluded (Space cycles, Enter applies, Escape cancels); the list is then
# reloaded with the resulting query.
# Mouse: a drag selects text inside the pane where it started (the terminal's
# own selection runs across the panes) and copies it to the Windows clipboard
# with clip.exe, folded lines joined back; a click focuses a pane or row, and
# the wheel scrolls the pane under the pointer.
# Viewing a message marks it read.
# <query> is a notmuch query, NEW for every unread message that is neither
# suspicious (see imc_suspicious_tag.sh) nor nonessential, or LAST for the
# query of the previous run (as left by t; kept in _var/view_last_query).
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <NEW|LAST|query>" >&2
  echo "example: $SCRIPT_NAME NEW" >&2
  echo "example: $SCRIPT_NAME LAST" >&2
  echo "example: $SCRIPT_NAME 'tag:unread and not folder:/teams-.*/'" >&2
  echo "example: $SCRIPT_NAME 'tag:suspicious or tag:nonessential'" >&2
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
[ "$query" = "NEW" ] && query="tag:unread and not tag:suspicious and not tag:nonessential"
if [ "$query" = "LAST" ]; then
  last_file="$SCRIPT_DIR/_var/view_last_query"
  if [ ! -s "$last_file" ]; then
    usage "No previous query ($last_file not found)"
    echo "Next: run $SCRIPT_NAME NEW once; the query you leave it with is kept for LAST." >&2
    exit 1
  fi
  query="$(head -n 1 "$last_file")"
fi

exec python3 "$SCRIPT_DIR/imc_message_view.py" "$query"
