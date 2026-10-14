#!/usr/bin/env bash
# Re-apply one or more rules files to every message handed to it on stdin,
# so that a rule change always reaches past mail as well as new mail.
# Tags named in a rules file are owned by it and are removed when a message
# stops matching. Tags not named anywhere, such as done, are never touched.
# Pass tag_rules.tsv and, if it exists, tag_rules.local.tsv (gitignored) to
# keep identifying sender rules out of this public repository.
# Reads the JSON output of imc_mail_list.sh on stdin and writes the change
# plan to stdout as TSV.
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTMUCH_CONFIG_FILE="$SCRIPT_DIR/_var/notmuch-config"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <rules_file>... [--dry-run] [--confirm]" >&2
  echo "example: $SCRIPT_NAME tag_rules.tsv --dry-run < all.json" >&2
  echo "example: imc_mail_list.sh '*' json | $SCRIPT_NAME tag_rules.tsv tag_rules.local.tsv --confirm" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
  echo "Next: pipe the full message list in, not a filtered one, or messages outside the filter keep stale tags." >&2
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

if [ "${#args[@]}" -lt 1 ]; then
  usage "Wrong number of arguments"
  exit 1
fi
rules_files=("${args[@]}")

for rules_file in "${rules_files[@]}"; do
  if [ ! -f "$rules_file" ]; then
    usage "$rules_file not found"
    exit 1
  fi
done
if [ ! -f "$NOTMUCH_CONFIG_FILE" ]; then
  usage "$NOTMUCH_CONFIG_FILE not found"
  exit 1
fi
if [ -t 0 ]; then
  usage "No message list on stdin"
  exit 1
fi

echo "Input:  rules=${rules_files[*]}, messages=JSON on stdin" >&2
if "$dry_run"; then
  echo "Output: change plan on stdout only; the notmuch index is left alone" >&2
else
  echo "Output: change plan on stdout, and the same changes applied to the notmuch index" >&2
fi

if "$confirm" && ! "$dry_run"; then
  if [ ! -r /dev/tty ]; then
    echo "$SCRIPT_NAME: --confirm requires an interactive terminal." >&2
    echo "Next: rerun from a terminal, or omit --confirm." >&2
    exit 1
  fi
  read -r -p "Re-tag every message according to ${rules_files[*]}? [y/N] " answer </dev/tty
  if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
    echo "$SCRIPT_NAME: Aborted; the notmuch index was not changed." >&2
    echo "Next: rerun when you are ready." >&2
    exit 1
  fi
fi

mode="apply"
"$dry_run" && mode="dry-run"

exec python3 "$SCRIPT_DIR/imc_tag_apply.py" "$NOTMUCH_CONFIG_FILE" "$mode" "${rules_files[@]}"
