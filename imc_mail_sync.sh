#!/usr/bin/env bash
# Fetch mail from one account, or from all of them, into _var/maildir and
# index the result with notmuch. Pull only: this never writes to the remote
# server and never deletes local mail.
# IMAP accounts go through mbsync; POP3 accounts (mbsync cannot speak POP3
# at all) go through getmail instead, reading _var/getmail/getmailrc-<account>.
# <account> is a name from IMC_ACCOUNTS in .env, or the word all.
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
VAR_DIR="$SCRIPT_DIR/_var"
GETMAIL_DIR="$VAR_DIR/getmail"
MBSYNCRC="$VAR_DIR/mbsyncrc"
NOTMUCH_CONFIG_FILE="$VAR_DIR/notmuch-config"

stamp() { date '+%Y-%m-%dT%H:%M:%S%z'; }

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <account|all> [--dry-run]" >&2
  echo "example: $SCRIPT_NAME all" >&2
  echo "example: $SCRIPT_NAME selfhosted --dry-run" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
  echo "Next: run $SCRIPT_DIR/initialize.sh first if $MBSYNCRC does not exist." >&2
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

if [ "${#args[@]}" -ne 1 ]; then
  usage "Wrong number of arguments"
  exit 1
fi
target="${args[0]}"

for path in "$ENV_FILE" "$MBSYNCRC" "$NOTMUCH_CONFIG_FILE"; do
  if [ ! -f "$path" ]; then
    usage "$path not found"
    exit 1
  fi
done

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

read -r -a accounts <<<"${IMC_ACCOUNTS:-}"
if [ "${#accounts[@]}" -eq 0 ]; then
  echo "$SCRIPT_NAME: IMC_ACCOUNTS is empty in $ENV_FILE." >&2
  echo "Next: edit $ENV_FILE and retry." >&2
  exit 1
fi

if [ "$target" = "all" ]; then
  targets=("${accounts[@]}")
else
  found=false
  for account in "${accounts[@]}"; do
    [ "$account" = "$target" ] && found=true
  done
  if ! "$found"; then
    echo "$SCRIPT_NAME: Unknown account '$target'; IMC_ACCOUNTS has: ${accounts[*]}" >&2
    echo "Next: use one of those names, or the word all." >&2
    exit 1
  fi
  targets=("$target")
fi

echo "Input:  accounts ${targets[*]} (IMAP via $MBSYNCRC, POP3 via $GETMAIL_DIR)" >&2
echo "Output: new mail under $VAR_DIR/maildir, new entries in the notmuch index" >&2

if "$dry_run"; then
  echo "$SCRIPT_NAME: Dry run completed; nothing was fetched or indexed." >&2
  echo "Next: rerun without --dry-run to fetch." >&2
  exit 0
fi

total="${#targets[@]}"
index=0
failed=()
for account in "${targets[@]}"; do
  index=$((index + 1))
  protocol_name="IMC_ACCOUNT_${account}_PROTOCOL"
  protocol="${!protocol_name:-}"
  case "$protocol" in
    IMAP)
      echo "$(stamp) $index/$total Syncing $account (IMAP)" >&2
      if ! mbsync --config "$MBSYNCRC" "$account"; then
        echo "$(stamp) $index/$total Sync FAILED for $account" >&2
        failed+=("$account")
      fi
      ;;
    POP3)
      echo "$(stamp) $index/$total Syncing $account (POP3)" >&2
      if ! getmail --getmaildir "$GETMAIL_DIR" --rcfile "$GETMAIL_DIR/getmailrc-$account"; then
        echo "$(stamp) $index/$total Sync FAILED for $account" >&2
        failed+=("$account")
      fi
      ;;
    *)
      echo "$SCRIPT_NAME: $protocol_name is '$protocol', not IMAP or POP3." >&2
      echo "Next: run initialize.sh again; it validates this before generating configs." >&2
      failed+=("$account")
      ;;
  esac
done

echo "$(stamp) Indexing new mail with notmuch" >&2
if ! NOTMUCH_CONFIG="$NOTMUCH_CONFIG_FILE" notmuch new; then
  echo "$SCRIPT_NAME: notmuch new failed." >&2
  echo "Next: run 'NOTMUCH_CONFIG=$NOTMUCH_CONFIG_FILE notmuch new' by hand to see the error." >&2
  exit 1
fi

if [ "${#failed[@]}" -gt 0 ]; then
  echo "$SCRIPT_NAME: ${#failed[@]} of $total accounts failed to sync: ${failed[*]}" >&2
  echo "Next: check the credentials in $ENV_FILE and network access to those hosts." >&2
  exit 1
fi

echo "$SCRIPT_NAME: Synced $total accounts and indexed them." >&2
echo "Next: run $SCRIPT_DIR/imc_mail_list.sh '*' tsv to see every message." >&2
