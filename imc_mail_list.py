"""Read messages out of the notmuch index and print one record per message.

Called only through imc_mail_list.sh, which validates the arguments.
Arguments: <notmuch_config> <query> <tsv|json>
"""
import email.utils
import json
import os
import subprocess
import sys
import time

FIELDS = [
    "message_id",
    "date_iso",
    "account",
    "from_addr",
    "from_name",
    "subject",
    "to",
    "tags",
    "path",
]


def stderr(message):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print("%s %s" % (stamp, message), file=sys.stderr)


def flatten(node, out):
    """notmuch show nests messages as [msg, [replies]] inside thread lists."""
    if isinstance(node, list):
        for child in node:
            flatten(child, out)
    elif isinstance(node, dict):
        if "id" in node:
            out.append(node)


def one_line(text):
    return " ".join(str(text).split())


def first_filename(message):
    name = message.get("filename", "")
    if isinstance(name, list):
        name = name[0] if name else ""
    return name


def account_of(path, mail_root):
    rest = os.path.relpath(path, mail_root) if path else ""
    if rest.startswith(".."):
        return "unknown"
    head = rest.split(os.sep, 1)[0]
    return head if head and head != "." else "unknown"


def mail_root_of(config_path):
    root = ""
    with open(config_path, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("mail_root="):
                root = line.split("=", 1)[1].strip()
    return root


def main(argv):
    config_path, query, output_format = argv[1], argv[2], argv[3]
    env = dict(os.environ)
    env["NOTMUCH_CONFIG"] = config_path

    stderr("Searching the notmuch index for: %s" % query)
    completed = subprocess.run(
        [
            "notmuch", "show",
            "--format=json",
            "--body=false",
            "--entire-thread=false",
            "--",
            query,
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr.decode("utf-8", "replace"))
        stderr("notmuch show failed with exit code %d." % completed.returncode)
        stderr("Next: check the query syntax and that initialize.sh has been run.")
        return completed.returncode

    threads = json.loads(completed.stdout.decode("utf-8", "replace") or "[]")
    messages = []
    flatten(threads, messages)

    mail_root = mail_root_of(config_path)
    records = []
    total = len(messages)
    for index, message in enumerate(messages, start=1):
        if total >= 500 and index % 500 == 0:
            stderr("%d/%d messages converted" % (index, total))
        headers = message.get("headers", {})
        from_name, from_addr = email.utils.parseaddr(headers.get("From", ""))
        path = first_filename(message)
        timestamp = message.get("timestamp", 0)
        records.append({
            "message_id": message.get("id", ""),
            "date_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(timestamp)),
            "account": account_of(path, mail_root),
            "from_addr": one_line(from_addr),
            "from_name": one_line(from_name),
            "subject": one_line(headers.get("Subject", "")),
            "to": one_line(headers.get("To", "")),
            "tags": ",".join(message.get("tags", [])),
            "path": os.path.relpath(path, mail_root) if path and mail_root else path,
        })

    records.sort(key=lambda record: record["date_iso"], reverse=True)

    if output_format == "json":
        json.dump(records, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print("\t".join(FIELDS))
        for record in records:
            print("\t".join(one_line(record[field]) for field in FIELDS))

    stderr("%d messages listed." % len(records))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
