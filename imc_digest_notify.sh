#!/usr/bin/env bash
# Send one morning push notification listing the messages that need action.
# A notification is sent even when the count is zero, so that a morning with
# no notification at all is a reliable sign that this pipeline is broken.
# <query> is the notmuch query that defines "needs action". <note> is a
# warning to put at the top of the body, or '' when the run was healthy.
# Reads its ntfy settings from the .env file next to this script, which uses
# a different topic from ~/bin/ntfy/.env on purpose.
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <query> <note> [--dry-run] [--confirm]" >&2
  echo "example: $SCRIPT_NAME 'tag:actionable and not tag:done' ''" >&2
  echo "example: $SCRIPT_NAME 'tag:actionable and not tag:done' '同期に失敗しました。' --dry-run" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
  echo "Next: copy $SCRIPT_DIR/.env.template to $ENV_FILE, set IMC_NTFY_TOPIC, and run chmod 600 $ENV_FILE." >&2
}

dry_run=false
confirm=false
args=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=true ;;
    --confirm) confirm=true ;;
    --*) usage "Unknown option: $arg"; exit 1 ;;
    *) args+=("$arg") ;;
  esac
done

if [ "${#args[@]}" -ne 2 ]; then
  usage "Wrong number of arguments"
  exit 1
fi
query="${args[0]}"
note="${args[1]}"

if [ ! -f "$ENV_FILE" ]; then
  usage "$ENV_FILE not found"
  exit 1
fi

env_mode="$(stat -c '%a' "$ENV_FILE")"
if [ "$env_mode" != "600" ]; then
  echo "$SCRIPT_NAME: $ENV_FILE must have mode 600; actual mode is $env_mode." >&2
  echo "Next: run chmod 600 $ENV_FILE and retry." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

for name in IMC_NTFY_SERVER IMC_NTFY_TOPIC IMC_NTFY_TITLE IMC_NTFY_PRIORITY; do
  if [ -z "${!name-}" ]; then
    echo "$SCRIPT_NAME: $name is missing or empty in $ENV_FILE." >&2
    echo "Next: edit $ENV_FILE and retry." >&2
    exit 1
  fi
done

if [[ ! "$IMC_NTFY_SERVER" =~ ^https://[^[:space:]/]+/?$ ]]; then
  echo "$SCRIPT_NAME: IMC_NTFY_SERVER must be an HTTPS origin without a path." >&2
  echo "Next: set it to a value such as https://ntfy.sh." >&2
  exit 1
fi

# The topic goes into the URL path, so allow only URL-safe characters.
# How unguessable it is, is left to the owner (2026-10-15: the hex-randomness
# check was removed at the owner's request).
if [[ ! "$IMC_NTFY_TOPIC" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "$SCRIPT_NAME: IMC_NTFY_TOPIC may contain only letters, digits, underscores and hyphens." >&2
  echo "Next: edit $ENV_FILE and retry." >&2
  exit 1
fi

case "$IMC_NTFY_PRIORITY" in
  min|low|default|high|max) ;;
  *)
    echo "$SCRIPT_NAME: IMC_NTFY_PRIORITY must be min, low, default, high, or max." >&2
    echo "Next: edit $ENV_FILE and retry." >&2
    exit 1
    ;;
esac

actionable_json="$("$SCRIPT_DIR/imc_mail_list.sh" "$query" json)"
total="$("$SCRIPT_DIR/imc_mail_list.sh" '*' tsv 2>/dev/null | tail -n +2 | wc -l)"
message="$(printf '%s' "$actionable_json" | python3 "$SCRIPT_DIR/imc_digest_format.py" "$total" "$note")"

echo "Input:  query=$query, note=${note:-(none)}, matched=$(printf '%s' "$actionable_json" | grep -c '"message_id"' || true), total=$total" >&2
echo "Output: one notification to topic ${IMC_NTFY_TOPIC%%-*}-... on $IMC_NTFY_SERVER" >&2
echo "---- notification body ----" >&2
printf '%s\n' "$message" >&2
echo "---------------------------" >&2

if "$dry_run"; then
  echo "$SCRIPT_NAME: Dry run completed; no notification was sent." >&2
  echo "Next: rerun without --dry-run to send it." >&2
  exit 0
fi

if "$confirm"; then
  if [ ! -r /dev/tty ]; then
    echo "$SCRIPT_NAME: --confirm requires an interactive terminal." >&2
    echo "Next: rerun from a terminal, or omit --confirm." >&2
    exit 1
  fi
  read -r -p "Send this notification? [y/N] " answer </dev/tty
  if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
    echo "$SCRIPT_NAME: Aborted; no notification was sent." >&2
    echo "Next: rerun when you are ready." >&2
    exit 1
  fi
fi

if curl \
  --request POST \
  --fail-with-body \
  --silent \
  --show-error \
  --retry 3 \
  --retry-delay 2 \
  --retry-all-errors \
  --connect-timeout 10 \
  --max-time 30 \
  --header "X-Title: $IMC_NTFY_TITLE" \
  --header "X-Priority: $IMC_NTFY_PRIORITY" \
  --data-binary "$message" \
  "${IMC_NTFY_SERVER%/}/$IMC_NTFY_TOPIC" \
  >/dev/null; then
  echo "$SCRIPT_NAME: Notification accepted by ntfy." >&2
  echo "Next: confirm that it arrived on the subscribed smartphone." >&2
else
  status=$?
  echo "$SCRIPT_NAME: Notification failed with curl exit code $status." >&2
  echo "Next: check the network and $ENV_FILE. A missing morning notification means this failed silently; check the log." >&2
  exit "$status"
fi
