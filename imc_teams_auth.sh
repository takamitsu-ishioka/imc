#!/usr/bin/env bash
# Sign in to Microsoft Graph for reading Teams channel messages, or show the
# current sign-in state.
# login  : device code flow. Prints a URL and a code on stderr; open the URL in
#          any browser, enter the code and sign in with your work account. This
#          command waits until you finish (or the code expires).
# status : prints "<name> <TAB> <upn> <TAB> <user id>" on stdout and the token
#          state on stderr.
# Tokens are kept in _var/teams/token.json (mode 600). Needs IMC_TEAMS_TENANT_ID
# and IMC_TEAMS_CLIENT_ID in .env.
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME <login|status>" >&2
  echo "example: $SCRIPT_NAME login" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
  echo "Next: register the app as described in .env.template, fill in .env, then run $SCRIPT_NAME login." >&2
}

if [ "$#" -ne 1 ]; then
  usage "Wrong number of arguments"
  exit 1
fi
case "$1" in
  login|status) ;;
  *) usage "Action must be login or status: $1"; exit 1 ;;
esac

exec python3 "$SCRIPT_DIR/imc_teams_auth.py" "$1"
