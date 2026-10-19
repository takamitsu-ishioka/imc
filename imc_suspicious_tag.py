"""Tag forged mail "suspicious" from what its raw header says, not from rules.

Called only through imc_suspicious_tag.sh, which validates the arguments.
Arguments: <notmuch_config> <mail_root> <apply|dry-run>
Stdin: the JSON output of imc_mail_list.sh (every message)
Stdout: the change plan as TSV (message_id, operation, tag, reason)

The tag is owned by this script: it is recomputed for every message given,
so a message that no longer matches loses it. Teams messages are skipped
(imc writes their header itself).

Signals (tried on real mail on 2026-10-19: 34 of 181 messages, all of them
spam or phishing, no false positive):
  hidden    the From display name or the Subject contains an invisible
            format character (Unicode category Cf: zero width space, bidi
            override, ...). Legitimate senders have no reason to hide
            characters; phishing uses them to dodge filters and to reverse
            text ("【 庁税国 】").
  unsigned  the message came in from outside (it has a Received header) and
            carries no DKIM-Signature at all. Every real company sender in the
            sample signs; the unsigned ones were spam, including mail that
            forged the receiving domain itself. A copy of your own sent mail
            has no Received header and is not caught.

Tried and dropped: From / Return-Path / DKIM d= domain mismatch. Phishing
senders sign with domains they registered themselves, so the domains agree;
the only hit was a false positive.
"""
import email
import email.header
import email.utils
import json
import os
import subprocess
import sys
import time
import unicodedata

TAG = "suspicious"


def stderr(message):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print("%s %s" % (stamp, message), file=sys.stderr)


def decoded(value):
    try:
        return str(email.header.make_header(email.header.decode_header(value or "")))
    except (email.errors.HeaderParseError, LookupError, UnicodeDecodeError):
        return value or ""


def has_hidden(text):
    return any(unicodedata.category(c) == "Cf" for c in text)


def reasons_of(path):
    """Return the list of signals that fire for the message file at path."""
    with open(path, "rb") as handle:
        message = email.message_from_binary_file(handle)
    name, _ = email.utils.parseaddr(decoded(message.get("From", "")))
    subject = decoded(message.get("Subject", ""))
    reasons = []
    if has_hidden(name) or has_hidden(subject):
        reasons.append("hidden")
    if message.get_all("Received") and not message.get_all("DKIM-Signature"):
        reasons.append("unsigned")
    return reasons


def quote_message_id(message_id):
    return '"%s"' % message_id.replace('"', '""')


def main(argv):
    config_path, mail_root, mode = argv[1], argv[2], argv[3]
    try:
        records = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        stderr("Stdin is not the JSON output of imc_mail_list.sh: %s" % error)
        stderr("Next: pipe \"imc_mail_list.sh '*' json\" into this script.")
        return 1

    plan = []
    total = len(records)
    unreadable = 0
    for index, record in enumerate(records, start=1):
        if total >= 500 and index % 500 == 0:
            stderr("%d/%d messages examined" % (index, total))
        message_id = record.get("message_id", "")
        if not message_id or record.get("account", "").startswith("teams-"):
            continue
        try:
            reasons = reasons_of(os.path.join(mail_root, record.get("path", "")))
        except OSError as error:
            unreadable += 1
            stderr("Skipped %s: %s" % (message_id, error))
            continue
        tagged = TAG in record.get("tags", "").split(",")
        if reasons and not tagged:
            plan.append((message_id, "+", ",".join(reasons)))
        elif not reasons and tagged:
            plan.append((message_id, "-", ""))

    print("message_id\toperation\ttag\treason")
    for message_id, operation, reason in plan:
        print("%s\t%s\t%s\t%s" % (message_id, operation, TAG, reason))

    added = sum(1 for p in plan if p[1] == "+")
    stderr("%d messages examined, %d to tag %s, %d to untag, %d unreadable."
           % (total, added, TAG, len(plan) - added, unreadable))

    if mode == "dry-run":
        stderr("Dry run: the notmuch index was not changed.")
        stderr("Next: rerun without --dry-run to apply this plan.")
        return 0
    if not plan:
        stderr("Nothing to change; the index already matches.")
        stderr("Next: imc_mail_list.sh 'tag:%s' tsv to see what is tagged." % TAG)
        return 0

    batch = "".join("%s%s -- id:%s\n" % (operation, TAG, quote_message_id(message_id))
                    for message_id, operation, _ in plan)
    env = dict(os.environ)
    env["NOTMUCH_CONFIG"] = config_path
    completed = subprocess.run(["notmuch", "tag", "--batch"], env=env,
                               input=batch.encode("utf-8"), stderr=subprocess.PIPE)
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr.decode("utf-8", "replace"))
        stderr("notmuch tag --batch failed with exit code %d." % completed.returncode)
        stderr("Next: rerun with --dry-run and inspect the plan on stdout.")
        return completed.returncode

    stderr("Applied %d tag operations." % len(plan))
    stderr("Next: imc_mail_list.sh 'tag:%s' tsv to see what is tagged." % TAG)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
