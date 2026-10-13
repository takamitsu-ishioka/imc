#!/usr/bin/env bash
# Run the whole morning pipeline: sync every account, re-apply the rules to
# every message, and send one push notification.
# Called by the Windows Task Scheduler through wsl.exe, so it takes no
# interactive input and writes a dated log under _var/log/.
# A failed sync does not stop the notification: a notification that says
# something went wrong is far better than no notification at all.
set -uo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/_var/log"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <query>" >&2
  echo "example: $SCRIPT_NAME 'tag:actionable and not tag:done'" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
  echo "Next: register this script in the Windows Task Scheduler; see design.md section 6." >&2
}

if [ "$#" -ne 1 ]; then
  usage "Wrong number of arguments"
  exit 1
fi
query="$1"

mkdir --parents "$LOG_DIR"
log_file="$LOG_DIR/$(date '+%Y-%m-%d').log"
exec 2> >(tee --append "$log_file" >&2)

stamp() { date '+%Y-%m-%dT%H:%M:%S%z'; }

echo "$(stamp) $SCRIPT_NAME: starting, query=$query" >&2

sync_note=""
if ! "$SCRIPT_DIR/imc_mail_sync.sh" all; then
  sync_note="同期に失敗しました。下の一覧は古い可能性があります。"
  echo "$(stamp) $SCRIPT_NAME: sync failed; continuing so that a notification is still sent" >&2
fi

if ! "$SCRIPT_DIR/imc_mail_list.sh" '*' json \
  | "$SCRIPT_DIR/imc_tag_apply.sh" "$SCRIPT_DIR/tag_rules.tsv" >/dev/null; then
  sync_note="${sync_note}${sync_note:+ }仕分けに失敗しました。"
  echo "$(stamp) $SCRIPT_NAME: tagging failed; continuing" >&2
fi

if [ -n "$sync_note" ]; then
  echo "$(stamp) $SCRIPT_NAME: degraded run: $sync_note" >&2
fi

if ! "$SCRIPT_DIR/imc_digest_notify.sh" "$query" "$sync_note"; then
  echo "$(stamp) $SCRIPT_NAME: notification failed. Nothing will arrive on the phone today." >&2
  echo "Next: read $log_file and fix the cause; a missing morning notification is the only alarm this system has." >&2
  exit 1
fi

echo "$(stamp) $SCRIPT_NAME: finished" >&2
echo "Next: nothing. The notification is on the phone." >&2
