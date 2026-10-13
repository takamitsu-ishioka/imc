"""Re-apply the sender and subject rules to every message given on stdin.

Called only through imc_tag_apply.sh, which validates the arguments.
Arguments: <notmuch_config> <rules_file> <apply|dry-run>
Stdin: the JSON output of imc_mail_list.sh
Stdout: the change plan as TSV (message_id, operation, tag)

Tags named in the rules file are owned by the rules file: a message that no
longer matches loses the tag. Tags that are not named there are never
touched, so hand made tags such as done survive.
"""
import json
import os
import re
import subprocess
import sys
import time

VALID_FIELDS = ("from", "subject", "to")


def stderr(message):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print("%s %s" % (stamp, message), file=sys.stderr)


def load_rules(path):
    rules = []
    owned = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                raise ValueError(
                    "%s line %d: expected at least 3 tab separated columns, got %d"
                    % (path, number, len(parts))
                )
            tag, field, pattern = parts[0].strip(), parts[1].strip(), parts[2]
            if field not in VALID_FIELDS:
                raise ValueError(
                    "%s line %d: field must be one of %s, got '%s'"
                    % (path, number, ", ".join(VALID_FIELDS), field)
                )
            if not re.match(r"^[A-Za-z0-9_.-]+$", tag):
                raise ValueError(
                    "%s line %d: tag '%s' must match [A-Za-z0-9_.-]+" % (path, number, tag)
                )
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error as error:
                raise ValueError("%s line %d: bad regex: %s" % (path, number, error))
            rules.append((tag, field, compiled))
            if tag not in owned:
                owned.append(tag)
    return rules, owned


def subject_of(record):
    return record.get("subject", "")


def from_of(record):
    name = record.get("from_name", "")
    addr = record.get("from_addr", "")
    return ("%s %s" % (name, addr)).strip()


def quote_message_id(message_id):
    return '"%s"' % message_id.replace('"', '""')


def main(argv):
    config_path, rules_path, mode = argv[1], argv[2], argv[3]

    try:
        rules, owned = load_rules(rules_path)
    except (OSError, ValueError) as error:
        stderr(str(error))
        stderr("Next: fix %s and rerun." % rules_path)
        return 1
    if not rules:
        stderr("%s contains no rules." % rules_path)
        stderr("Next: add at least one rule line, or stop calling this script.")
        return 1
    stderr("Loaded %d rules owning %d tags: %s" % (len(rules), len(owned), ", ".join(owned)))

    try:
        records = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        stderr("Stdin is not the JSON output of imc_mail_list.sh: %s" % error)
        stderr("Next: pipe \"imc_mail_list.sh '*' json\" into this script.")
        return 1

    owned_set = set(owned)
    operations = []
    total = len(records)
    for index, record in enumerate(records, start=1):
        if total >= 500 and index % 500 == 0:
            stderr("%d/%d messages matched" % (index, total))
        values = {
            "from": from_of(record),
            "subject": subject_of(record),
            "to": record.get("to", ""),
        }
        wanted = set()
        for tag, field, compiled in rules:
            if compiled.search(values[field]):
                wanted.add(tag)
        current = {t for t in record.get("tags", "").split(",") if t} & owned_set
        message_id = record.get("message_id", "")
        if not message_id:
            continue
        for tag in sorted(wanted - current):
            operations.append((message_id, "+", tag))
        for tag in sorted(current - wanted):
            operations.append((message_id, "-", tag))

    print("message_id\toperation\ttag")
    for message_id, operation, tag in operations:
        print("%s\t%s\t%s" % (message_id, operation, tag))

    added = sum(1 for op in operations if op[1] == "+")
    removed = len(operations) - added
    stderr("%d messages examined, %d tags to add, %d tags to remove."
           % (total, added, removed))

    if mode == "dry-run":
        stderr("Dry run: the notmuch index was not changed.")
        stderr("Next: rerun without --dry-run to apply this plan.")
        return 0

    if not operations:
        stderr("Nothing to change; the index already matches the rules.")
        stderr("Next: edit %s if you expected a change." % rules_path)
        return 0

    batch = "".join(
        "%s%s -- id:%s\n" % (operation, tag, quote_message_id(message_id))
        for message_id, operation, tag in operations
    )
    # Inherit the environment rather than building a minimal one: notmuch
    # exits 1 with an empty stderr when HOME is unset, which is impossible to
    # diagnose from the outside.
    env = dict(os.environ)
    env["NOTMUCH_CONFIG"] = config_path
    completed = subprocess.run(
        ["notmuch", "tag", "--batch"],
        env=env,
        input=batch.encode("utf-8"),
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr.decode("utf-8", "replace"))
        stderr("notmuch tag --batch failed with exit code %d." % completed.returncode)
        stderr("Next: rerun with --dry-run and inspect the plan on stdout.")
        return completed.returncode

    stderr("Applied %d tag operations." % len(operations))
    stderr("Next: run imc_mail_list.sh 'tag:actionable' tsv to see the result.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
