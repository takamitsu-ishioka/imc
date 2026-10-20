#!/usr/bin/env bash
# Fetch the messages not fetched yet, for one route or for all of them, into
# _var/maildir and the notmuch index. One command, by hand or from a
# scheduler outside imc (imc itself schedules nothing; see design.md 6).
# <route>:
#   mail  : every account in IMC_ACCOUNTS whose HOST is not imap.gmail.com
#           (own IMAP server, POP3-only ISPs, ...) via imc_mail_sync.sh
#   gmail : accounts whose HOST is imap.gmail.com, via imc_mail_sync.sh
#   teams : the channels in teams_channels.local.tsv, via imc_teams_fetch.sh LAST
#   all   : mail, gmail, teams in that order. A failing route does not stop
#           the others; the exit code is then 1.
# Each route only fetches what is new (mbsync/getmail keep their own state,
# Teams starts from the newest stored message), so running often is cheap.
# After the routes, the tags are recomputed for every message: tag_rules.tsv
# (and tag_rules.local.tsv if it exists) through imc_tag_apply.sh, then
# imc_suspicious_tag.sh. Mail that arrives between two morning runs is thus
# tagged (suspicious, nonessential, ...) within one fetch, not the next day.
# This step holds _var/fetch.lock too, so it never writes the notmuch index
# while another fetch is indexing.
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
CHANNELS_FILE="$SCRIPT_DIR/teams_channels.local.tsv"
GMAIL_HOST="imap.gmail.com"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <mail|gmail|teams|all>" >&2
  echo "example: $SCRIPT_NAME all" >&2
  echo "example: $SCRIPT_NAME teams" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
}

stamp() { date '+%Y-%m-%dT%H:%M:%S%z'; }

if [ "$#" -ne 1 ]; then
  usage "Wrong number of arguments"
  exit 1
fi
case "$1" in
  mail|gmail|teams) routes=("$1") ;;
  all) routes=(mail gmail teams) ;;
  *) usage "Route must be mail, gmail, teams or all: $1"; exit 1 ;;
esac
if [ ! -f "$ENV_FILE" ]; then
  usage "$ENV_FILE not found"
  echo "Next: copy $SCRIPT_DIR/.env.template to $ENV_FILE and fill it in." >&2
  exit 1
fi

# Accounts of one kind (mail or gmail), split by HOST so no extra setting is needed.
accounts_of() {
  local kind="$1" account host_name is_gmail
  (
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    for account in ${IMC_ACCOUNTS:-}; do
      host_name="IMC_ACCOUNT_${account}_HOST"
      is_gmail=false
      [ "${!host_name:-}" = "$GMAIL_HOST" ] && is_gmail=true
      if { [ "$kind" = "gmail" ] && "$is_gmail"; } || { [ "$kind" = "mail" ] && ! "$is_gmail"; }; then
        echo "$account"
      fi
    done
  )
}

run_route() {
  local route="$1"
  case "$route" in
    mail|gmail)
      local selected
      mapfile -t selected < <(accounts_of "$route")
      if [ "${#selected[@]}" -eq 0 ]; then
        echo "$(stamp) $route: no such accounts in IMC_ACCOUNTS; nothing to fetch" >&2
        return 0
      fi
      echo "$(stamp) $route: ${selected[*]}" >&2
      "$SCRIPT_DIR/imc_mail_sync.sh" "${selected[@]}"
      ;;
    teams)
      if [ ! -f "$CHANNELS_FILE" ]; then
        echo "$(stamp) teams: $CHANNELS_FILE not found" >&2
        echo "Next: cp $CHANNELS_FILE.template $CHANNELS_FILE, list the channels, and run imc_teams_fetch.sh <date> once." >&2
        return 1
      fi
      echo "$(stamp) teams: channels in $CHANNELS_FILE" >&2
      "$SCRIPT_DIR/imc_teams_fetch.sh" LAST < "$CHANNELS_FILE"
      ;;
  esac
}

failed=()
index=0
for route in "${routes[@]}"; do
  index=$((index + 1))
  echo "$(stamp) $index/${#routes[@]} route $route" >&2
  run_route "$route" || failed+=("$route")
done

retag() {
  local rules_files=("$SCRIPT_DIR/tag_rules.tsv")
  [ -f "$SCRIPT_DIR/tag_rules.local.tsv" ] && rules_files+=("$SCRIPT_DIR/tag_rules.local.tsv")
  (
    exec 9>"$SCRIPT_DIR/_var/fetch.lock"
    if ! flock --wait 900 9; then
      echo "$(stamp) retag: another fetch has held _var/fetch.lock for 15 minutes; skipped" >&2
      exit 1
    fi
    "$SCRIPT_DIR/imc_mail_list.sh" '*' json | "$SCRIPT_DIR/imc_tag_apply.sh" "${rules_files[@]}" >/dev/null \
      && "$SCRIPT_DIR/imc_mail_list.sh" '*' json | "$SCRIPT_DIR/imc_suspicious_tag.sh" >/dev/null
  )
}

echo "$(stamp) retag: rules and suspicious, every message" >&2
retag || failed+=("retag")

if [ "${#failed[@]}" -gt 0 ]; then
  echo "$SCRIPT_NAME: failed routes: ${failed[*]}" >&2
  echo "Next: rerun $SCRIPT_NAME <route> for each and read its messages above." >&2
  exit 1
fi
echo "$SCRIPT_NAME: fetched ${routes[*]}" >&2
echo "Next: run $SCRIPT_DIR/imc_mail_list.sh 'tag:unread' tsv to see what came in." >&2
