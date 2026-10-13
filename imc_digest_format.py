"""Turn a message list into the body of one morning push notification.

Called only through imc_digest_notify.sh, which validates the arguments.
Arguments: <total_count> <note>
<note> is a warning to put at the top of the body, or "" for none. A run
that fetched nothing must say so, otherwise a silently broken sync looks
exactly like a quiet morning.
Stdin: the JSON output of imc_mail_list.sh, already filtered to the
messages that need action.
Stdout: the notification body.

Sender and subject are included on purpose; see design.md section 4. The
message body, attachments and URLs are never included.
"""
import json
import sys

MAX_LINES = 12
MAX_SUBJECT = 70
MAX_SENDER = 28


def one_line_note(note):
    return " ".join(str(note).split())


def shorten(text, limit):
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def sender_of(record):
    name = record.get("from_name", "").strip()
    if name:
        return shorten(name, MAX_SENDER)
    addr = record.get("from_addr", "").strip()
    return shorten(addr or "(差出人不明)", MAX_SENDER)


def main(argv):
    total, note = argv[1], argv[2]
    records = json.load(sys.stdin)

    prefix = ["\u26a0 " + one_line_note(note), ""] if note.strip() else []

    if not records:
        body = ["要対応 0件 / 全体 %s件" % total, ""]
        body.append("今日は何もありません。" if not note.strip()
                    else "一覧が正しいとは限りません。WSLで確認してください。")
        print("\n".join(prefix + body))
        return 0

    lines = ["要対応 %d件 / 全体 %s件" % (len(records), total), ""]
    for record in records[:MAX_LINES]:
        lines.append("- %s: %s" % (sender_of(record), shorten(record.get("subject", ""), MAX_SUBJECT) or "(件名なし)"))
    if len(records) > MAX_LINES:
        lines.append("- ほか %d件" % (len(records) - MAX_LINES))

    print("\n".join(prefix + lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
