"""Store Teams channel messages into _var/maildir as one RFC 5322 file each.

Called only through imc_teams_fetch.sh, which validates the arguments, holds
the fetch lock and runs notmuch new afterwards.
Arguments: <since|LAST> <dry_run: true|false>. Stdin: team<TAB>channel per line.

Layout: _var/maildir/teams-<h>/{tmp,new,cur}, one Maildir per channel, where
<h> is a short hash of the channel id (stable when a channel is renamed). A
message file is named <message id>.<h>.teams; Teams message ids are creation
times in milliseconds, so LAST can take the newest one from the file names.
"""
import datetime
import email.message
import email.policy
import email.utils
import hashlib
import os
import socket
import sys

import imc_teams_graph as g
import imc_teams_message_fetch as mf
import imc_teams_message_list as ml

MAILDIR_ROOT = os.path.join(g.SCRIPT_DIR, "_var", "maildir")
# Start this far before the newest stored message, so that messages posted
# while the previous run was in flight are picked up too.
LAST_MARGIN = datetime.timedelta(minutes=10)
DOMAIN = "teams.imc.invalid"


def channel_hash(channel_id):
    return hashlib.sha1(channel_id.encode()).hexdigest()[:12]


def message_id(msg_id, h):
    return "<%s.%s@%s>" % (msg_id, h, DOMAIN)


def folder(h):
    return os.path.join(MAILDIR_ROOT, "teams-" + h)


def stored_ids(path):
    """Message ids already in this Maildir (new/ and cur/; cur names get flags appended)."""
    ids = set()
    for sub in ("new", "cur"):
        d = os.path.join(path, sub)
        if os.path.isdir(d):
            for name in os.listdir(d):
                ids.add(name.split(".", 1)[0])
    return ids


def last_since(ids):
    numeric = [int(i) for i in ids if i.isdigit()]
    if not numeric:
        return None
    newest = datetime.datetime.fromtimestamp(max(numeric) / 1000, tz=ml.JST)
    return newest - LAST_MARGIN


def build(row, h):
    msg = email.message.EmailMessage(policy=email.policy.SMTP)
    sender = row["from"] or "unknown"
    local = "".join(c if c.isalnum() or c in "._-" else "_" for c in sender) or "unknown"
    msg["From"] = email.utils.formataddr((sender, "%s@%s" % (local, DOMAIN)))
    msg["To"] = "%s / %s <channel@%s>" % (row["team"], row["channel"], DOMAIN)
    msg["Subject"] = "Teams %s / %s" % (row["team"], row["channel"])
    msg["Date"] = email.utils.format_datetime(datetime.datetime.fromisoformat(row["posted_at"]))
    msg["Message-ID"] = message_id(row["id"], h)
    if row["reply_to"]:
        msg["In-Reply-To"] = message_id(row["reply_to"], h)
        msg["References"] = message_id(row["reply_to"], h)
    msg["X-Imc-Source"] = "teams"
    msg["X-Imc-Team"] = row["team"]
    msg["X-Imc-Channel"] = row["channel"]
    msg["X-Imc-Addressed-To-Me"] = "true" if row["addressed_to_me"] else "false"
    msg.set_content("%s\n\n%s\n" % (row["text"], row["url"]))
    return msg.as_bytes()


def deliver(path, name, data):
    """Maildir delivery: write into tmp/, then rename into new/ (atomic)."""
    for sub in ("tmp", "new", "cur"):
        os.makedirs(os.path.join(path, sub), mode=0o700, exist_ok=True)
    tmp = os.path.join(path, "tmp", "%s.%d.%s" % (name, os.getpid(), socket.gethostname()))
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, os.path.join(path, "new", name))


def main():
    since_arg, dry_run = sys.argv[1], sys.argv[2] == "true"
    fixed_since = None if since_arg == "LAST" else ml.parse_since(since_arg)
    pairs = mf.read_pairs(sys.stdin)
    my_id = g.get("/me?$select=id")["id"]
    found, missing = mf.resolve(pairs)

    total_new = 0
    no_history = []
    for i, (team_name, channel_name, team_id, channel_id) in enumerate(found, 1):
        h = channel_hash(channel_id)
        path = folder(h)
        have = stored_ids(path)
        since = fixed_since or last_since(have)
        label = "%d/%d %s / %s" % (i, len(found), team_name, channel_name)
        if since is None:
            g.stderr("%s: nothing stored yet, so LAST has no starting point; skipped" % label)
            no_history.append("%s / %s" % (team_name, channel_name))
            continue
        g.stderr("%s since %s (teams-%s)" % (label, since.isoformat(), h))
        rows = ml.fetch(team_id, channel_id, team_name, channel_name, since, my_id)
        new_rows = [r for r in rows if r["id"] not in have]
        if not dry_run:
            for r in new_rows:
                deliver(path, "%s.%s.teams" % (r["id"], h), build(r, h))
        total_new += len(new_rows)
        g.stderr("%s: %d fetched, %d new%s" % (label, len(rows), len(new_rows),
                                              " (dry run, not stored)" if dry_run else ""))

    g.stderr("%d new messages from %d channels" % (total_new, len(found) - len(no_history)))
    failed = False
    if missing:
        g.stderr("Not found (skipped): %s" % ", ".join(missing))
        print("Next: check the exact names with imc_teams_channel_list.sh tsv and fix the list.", file=sys.stderr)
        failed = True
    if no_history:
        print("Next: run once with a date for %s, e.g. imc_teams_fetch.sh 2026-10-01 < list"
              % ", ".join(no_history), file=sys.stderr)
        failed = True
    if not failed:
        print("Next: read them with imc_mail_list.sh 'folder:/teams-.*/' tsv, or in neomutt.", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
