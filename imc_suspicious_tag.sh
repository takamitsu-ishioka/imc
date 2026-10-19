#!/usr/bin/env bash
# Tag forged mail "suspicious" from its raw header: an invisible character in
# the From name or Subject, or mail from outside with no DKIM signature.
# See imc_suspicious_tag.py for the signals and why they were chosen.
# The suspicious tag is owned by this script and recomputed for every message
# handed to it, so pass the full list ('*'), never a filtered one.
# imc_message_view.sh NEW and imc_morning_run.sh leave suspicious mail out;
# imc_message_view.sh 'tag:suspicious' shows it.
# Reads the JSON output of imc_mail_list.sh on stdin and writes the change
# plan to stdout as TSV.
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTMUCH_CONFIG_FILE="$SCRIPT_DIR/_var/notmuch-config"
MAIL_ROOT="$SCRIPT_DIR/_var/maildir"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME [--dry-run] [--confirm] < all.json" >&2
  echo "example: imc_mail_list.sh '*' json | $SCRIPT_NAME --dry-run" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
}

dry_run=false
confirm=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=true ;;
    --confirm) confirm=true ;;
    *) usage "Unknown argument: $arg"; exit 1 ;;
  esac
done

if [ ! -f "$NOTMUCH_CONFIG_FILE" ]; then
  usage "$NOTMUCH_CONFIG_FILE not found"
  echo "Next: run $SCRIPT_DIR/initialize.sh first." >&2
  exit 1
fi
if [ -t 0 ]; then
  usage "No message list on stdin"
  exit 1
fi

echo "Input:  messages=JSON on stdin, files under $MAIL_ROOT" >&2
if "$dry_run"; then
  echo "Output: change plan on stdout only; the notmuch index is left alone" >&2
else
  echo "Output: change plan on stdout, and tag:suspicious set accordingly in the notmuch index" >&2
fi

if "$confirm" && ! "$dry_run"; then
  if [ ! -r /dev/tty ]; then
    echo "$SCRIPT_NAME: --confirm requires an interactive terminal." >&2
    echo "Next: rerun from a terminal, or omit --confirm." >&2
    exit 1
  fi
  read -r -p "Recompute tag:suspicious for every message? [y/N] " answer </dev/tty
  if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
    echo "$SCRIPT_NAME: Aborted; the notmuch index was not changed." >&2
    echo "Next: rerun when you are ready." >&2
    exit 1
  fi
fi

mode="apply"
"$dry_run" && mode="dry-run"

exec python3 "$SCRIPT_DIR/imc_suspicious_tag.py" "$NOTMUCH_CONFIG_FILE" "$MAIL_ROOT" "$mode"
