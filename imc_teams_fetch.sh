#!/usr/bin/env bash
# Fetch the Teams messages not fetched yet into _var/maildir and index them
# with notmuch, in one command (by hand or from cron). Stage 5 of design.md:
# Teams (Graph API) -> Maildir -> notmuch, next to the mail accounts.
# The channel list comes on stdin, team<TAB>channel per line, the same as
# imc_teams_message_fetch.sh (usually teams_channels.local.tsv).
# <since> is ISO 8601 (JST when no zone), or LAST: for each channel, start a
# little before the newest message already stored, so nothing in between is
# missed. LAST fails for a channel with nothing stored yet; run once with an
# explicit date first. Storing is idempotent: one file per message, named by
# channel and message id, so overlapping runs never make duplicates.
# Each message: From = sender, Subject = "Teams <team> / <channel>" (no
# message text, because the morning ntfy digest shows subjects through a
# public server), body = text and link, In-Reply-To = the thread root.
# Holds _var/fetch.lock like imc_mail_sync.sh. Needs imc_teams_auth.sh login.
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAR_DIR="$SCRIPT_DIR/_var"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <since|LAST> [--dry-run] < channels.tsv" >&2
  echo "example: $SCRIPT_NAME 2026-10-01 < $SCRIPT_DIR/teams_channels.local.tsv" >&2
  echo "example: $SCRIPT_NAME LAST < $SCRIPT_DIR/teams_channels.local.tsv" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
  echo "Next: cp $SCRIPT_DIR/teams_channels.local.tsv.template $SCRIPT_DIR/teams_channels.local.tsv and edit it." >&2
}

dry_run=false
args=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=true ;;
    --*) usage "Unknown option: $arg"; exit 1 ;;
    *) args+=("$arg") ;;
  esac
done
if [ "${#args[@]}" -ne 1 ] || [ -z "${args[0]}" ]; then
  usage "Wrong number of arguments"
  exit 1
fi
if [ -t 0 ]; then
  usage "The channel list must come on stdin"
  exit 1
fi
if [ ! -f "$VAR_DIR/notmuch-config" ]; then
  usage "$VAR_DIR/notmuch-config not found"
  echo "Next: run $SCRIPT_DIR/initialize.sh first." >&2
  exit 1
fi

LOCK_FILE="$VAR_DIR/fetch.lock"
exec 9>"$LOCK_FILE"
if ! flock --wait 900 9; then
  echo "$SCRIPT_NAME: another fetch has held $LOCK_FILE for 15 minutes; giving up." >&2
  echo "Next: check for a stuck mbsync, getmail or notmuch process, then retry." >&2
  exit 1
fi

rc=0
python3 "$SCRIPT_DIR/imc_teams_fetch.py" "${args[0]}" "$dry_run" || rc=$?
if [ "$rc" -ne 0 ] && [ "$rc" -ne 1 ]; then
  exit "$rc"
fi
if "$dry_run"; then
  exit "$rc"
fi
echo "$(date '+%Y-%m-%dT%H:%M:%S%z') Indexing new messages with notmuch" >&2
if ! NOTMUCH_CONFIG="$VAR_DIR/notmuch-config" notmuch new; then
  echo "$SCRIPT_NAME: notmuch new failed." >&2
  echo "Next: run 'NOTMUCH_CONFIG=$VAR_DIR/notmuch-config notmuch new' by hand to see the error." >&2
  exit 1
fi
exit "$rc"
