#!/usr/bin/env bash
# Make this directory usable in one command, idempotently.
# Installs isync, getmail6, notmuch and neomutt, creates _var/, and
# regenerates _var/mbsyncrc (IMAP accounts), _var/getmail/getmailrc-<account>
# (POP3 accounts) and _var/notmuch-config from .env. Safe to run again after
# editing .env, for example to add a second account.
# Everything it creates lives under _var/ and can be deleted and rebuilt.
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
VAR_DIR="$SCRIPT_DIR/_var"
MAILDIR="$VAR_DIR/maildir"
GETMAIL_DIR="$VAR_DIR/getmail"
MBSYNCRC="$VAR_DIR/mbsyncrc"
NOTMUCH_CONFIG_FILE="$VAR_DIR/notmuch-config"
PACKAGES="isync getmail6 notmuch neomutt"

usage() {
  echo "$SCRIPT_NAME: $1" >&2
  echo "usage: $SCRIPT_NAME [--dry-run] [--confirm]" >&2
  echo "example: $SCRIPT_NAME --dry-run" >&2
  echo "example: $SCRIPT_NAME --confirm" >&2
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}" >&2
  echo "Next: copy $SCRIPT_DIR/.env.template to $ENV_FILE, edit it, run chmod 600 $ENV_FILE, then rerun." >&2
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

for name in IMC_USER_NAME IMC_USER_PRIMARY_EMAIL IMC_ACCOUNTS; do
  if [ -z "${!name-}" ]; then
    echo "$SCRIPT_NAME: $name is missing or empty in $ENV_FILE." >&2
    echo "Next: edit $ENV_FILE and retry." >&2
    exit 1
  fi
done

read -r -a accounts <<<"$IMC_ACCOUNTS"
imap_accounts=()
pop3_accounts=()
for account in "${accounts[@]}"; do
  if [[ ! "$account" =~ ^[a-z0-9_]+$ ]]; then
    echo "$SCRIPT_NAME: Account name '$account' must match [a-z0-9_]+." >&2
    echo "Next: fix IMC_ACCOUNTS in $ENV_FILE and retry." >&2
    exit 1
  fi
  for suffix in HOST PORT USER PASSWORD PROTOCOL; do
    name="IMC_ACCOUNT_${account}_${suffix}"
    if [ -z "${!name-}" ]; then
      echo "$SCRIPT_NAME: $name is missing or empty in $ENV_FILE." >&2
      echo "Next: edit $ENV_FILE and retry." >&2
      exit 1
    fi
  done
  protocol_name="IMC_ACCOUNT_${account}_PROTOCOL"
  case "${!protocol_name}" in
    IMAP)
      imap_accounts+=("$account")
      tlstype_name="IMC_ACCOUNT_${account}_TLSTYPE"
      if [ -z "${!tlstype_name-}" ]; then
        echo "$SCRIPT_NAME: $tlstype_name is missing or empty in $ENV_FILE." >&2
        echo "Next: edit $ENV_FILE and retry." >&2
        exit 1
      fi
      case "${!tlstype_name}" in
        IMAPS|STARTTLS) ;;
        *)
          echo "$SCRIPT_NAME: $tlstype_name must be IMAPS or STARTTLS." >&2
          echo "Next: edit $ENV_FILE and retry." >&2
          exit 1
          ;;
      esac
      ;;
    POP3)
      # POP3 is always over SSL (SimplePOP3SSLRetriever); plaintext POP3 is
      # not offered. CERTIFICATEFILE is optional, same as for IMAP accounts.
      pop3_accounts+=("$account")
      ;;
    *)
      echo "$SCRIPT_NAME: $protocol_name must be IMAP or POP3." >&2
      echo "Next: edit $ENV_FILE and retry." >&2
      exit 1
      ;;
  esac
done

missing_packages=""
for package in $PACKAGES; do
  if ! dpkg-query --show --showformat='${Status}' "$package" 2>/dev/null | grep -q 'ok installed'; then
    missing_packages="$missing_packages $package"
  fi
done
missing_packages="${missing_packages# }"

echo "Input:  $ENV_FILE, IMAP accounts=${imap_accounts[*]:-(none)}, POP3 accounts=${pop3_accounts[*]:-(none)}" >&2
echo "Output: $VAR_DIR/{maildir,notmuch,log,getmail}, $MBSYNCRC, $NOTMUCH_CONFIG_FILE" >&2
if [ -n "$missing_packages" ]; then
  echo "Output: apt-get install of${missing_packages:+ }$missing_packages (needs sudo)" >&2
else
  echo "Output: no package installation needed; $PACKAGES already installed" >&2
fi

if "$dry_run"; then
  echo "$SCRIPT_NAME: Dry run completed; nothing was created or changed." >&2
  echo "Next: rerun without --dry-run to apply." >&2
  exit 0
fi

if "$confirm"; then
  if [ ! -r /dev/tty ]; then
    echo "$SCRIPT_NAME: --confirm requires an interactive terminal." >&2
    echo "Next: rerun from a terminal, or omit --confirm." >&2
    exit 1
  fi
  read -r -p "Apply the changes listed above? [y/N] " answer </dev/tty
  if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
    echo "$SCRIPT_NAME: Aborted; nothing was created or changed." >&2
    echo "Next: rerun when you are ready." >&2
    exit 1
  fi
fi

if [ -n "$missing_packages" ]; then
  echo "$SCRIPT_NAME: Installing$missing_packages ..." >&2
  sudo apt-get update --quiet
  # shellcheck disable=SC2086
  sudo DEBIAN_FRONTEND=noninteractive apt-get install --yes --quiet $missing_packages
fi

mkdir --parents "$MAILDIR" "$VAR_DIR/notmuch" "$VAR_DIR/log" "$GETMAIL_DIR"
chmod 700 "$VAR_DIR"

# mbsync の MaildirStore も getmail の Maildir destination も、Path の
# トップディレクトリ自体(cur/new/tmpを含む完全なMaildir構造)が事前に存在
# することを要求する(どちらも中身を作るだけで、store自体は作らない)。
# アカウントごとに先に作っておく。
for account in "${accounts[@]}"; do
  mkdir --parents "$MAILDIR/$account/cur" "$MAILDIR/$account/new" "$MAILDIR/$account/tmp"
done

umask 077
{
  echo "# Generated by $SCRIPT_NAME from $ENV_FILE. Do not edit; edit .env and rerun."
  echo "# Passwords are never stored here; PassCmd reads them from .env at run time."
  echo "# Sync Pull / Remove None / Expunge None means this never writes to the"
  echo "# remote server and never deletes local mail, so the Maildir is an archive."
  echo "# IMAP accounts only; POP3 accounts are handled by getmail (see getmail/)."
  echo
  for account in "${imap_accounts[@]}"; do
    host="IMC_ACCOUNT_${account}_HOST"
    port="IMC_ACCOUNT_${account}_PORT"
    user="IMC_ACCOUNT_${account}_USER"
    tlstype="IMC_ACCOUNT_${account}_TLSTYPE"
    certfile="IMC_ACCOUNT_${account}_CERTIFICATEFILE"
    echo "IMAPAccount $account"
    echo "Host ${!host}"
    echo "Port ${!port}"
    echo "User ${!user}"
    echo "PassCmd \"+$SCRIPT_DIR/imc_secret_get.sh IMC_ACCOUNT_${account}_PASSWORD\""
    echo "SSLType ${!tlstype}"
    if [ -n "${!certfile-}" ]; then
      echo "CertificateFile ${!certfile}"
    else
      echo "SystemCertificates yes"
    fi
    echo
    echo "IMAPStore ${account}-remote"
    echo "Account $account"
    echo
    echo "MaildirStore ${account}-local"
    echo "Path $MAILDIR/$account/"
    echo "Inbox $MAILDIR/$account/INBOX"
    echo "SubFolders Verbatim"
    echo
    echo "Channel $account"
    echo "Far :${account}-remote:"
    echo "Near :${account}-local:"
    echo "Patterns *"
    echo "Create Near"
    echo "Sync Pull"
    echo "Remove None"
    echo "Expunge None"
    echo "SyncState *"
    echo
  done
} > "$MBSYNCRC"
chmod 600 "$MBSYNCRC"

# getmail では IMAP とは別物の POP3 専用アカウントを扱う。mbsync が決して
# POP3 を話せないための分岐であり、1アカウント1rcfileがgetmailの作法。
for account in "${pop3_accounts[@]}"; do
  host="IMC_ACCOUNT_${account}_HOST"
  port="IMC_ACCOUNT_${account}_PORT"
  user="IMC_ACCOUNT_${account}_USER"
  certfile="IMC_ACCOUNT_${account}_CERTIFICATEFILE"
  getmailrc="$GETMAIL_DIR/getmailrc-$account"
  {
    echo "# Generated by $SCRIPT_NAME from $ENV_FILE. Do not edit; edit .env and rerun."
    echo "# delete = false: this never deletes mail from the server, mirroring"
    echo "# mbsync's Remove None/Expunge None policy for IMAP accounts."
    echo "# read_all = false: only messages not yet in the oldmail state under"
    echo "# $GETMAIL_DIR are retrieved. The combination read_all=true (the"
    echo "# getmail default) + delete=false makes getmail re-fetch and"
    echo "# re-deliver every message on every run -- getmail itself warns"
    echo "# about this combination at run time."
    echo "[retriever]"
    echo "type = SimplePOP3SSLRetriever"
    echo "server = ${!host}"
    echo "port = ${!port}"
    echo "username = ${!user}"
    echo "password_command = (\"$SCRIPT_DIR/imc_secret_get.sh\", \"IMC_ACCOUNT_${account}_PASSWORD\")"
    if [ -n "${!certfile-}" ]; then
      echo "ca_certs = ${!certfile}"
    fi
    echo
    echo "[destination]"
    echo "type = Maildir"
    echo "path = $MAILDIR/$account/"
    echo
    echo "[options]"
    echo "verbose = 1"
    echo "delete = false"
    echo "read_all = false"
  } > "$getmailrc"
  chmod 600 "$getmailrc"
done

{
  echo "# Generated by $SCRIPT_NAME from $ENV_FILE. Do not edit; edit .env and rerun."
  echo "[database]"
  echo "path=$VAR_DIR/notmuch"
  echo "mail_root=$MAILDIR"
  echo
  echo "[user]"
  echo "name=$IMC_USER_NAME"
  echo "primary_email=$IMC_USER_PRIMARY_EMAIL"
  if [ -n "${IMC_USER_OTHER_EMAILS-}" ]; then
    echo "other_email=$(echo "$IMC_USER_OTHER_EMAILS" | tr ' ' ';')"
  fi
  echo
  echo "[new]"
  echo "tags=unread;inbox"
  echo "ignore=.uidvalidity;.mbsyncstate;.mbsyncstate.new;.mbsyncstate.journal"
  echo
  echo "[search]"
  echo "exclude_tags=deleted;spam"
  echo
  echo "[maildir]"
  echo "synchronize_flags=true"
} > "$NOTMUCH_CONFIG_FILE"
chmod 600 "$NOTMUCH_CONFIG_FILE"

if ! NOTMUCH_CONFIG="$NOTMUCH_CONFIG_FILE" notmuch new --quiet; then
  echo "$SCRIPT_NAME: notmuch new failed." >&2
  echo "Next: inspect $NOTMUCH_CONFIG_FILE and $MAILDIR, then rerun." >&2
  exit 1
fi

echo "$SCRIPT_NAME: Initialization completed." >&2
echo "Next: run $SCRIPT_DIR/imc_mail_sync.sh all to fetch mail for the first time." >&2
