"""Post one message to a Teams channel, as a new thread or as a reply.

Called only through imc_teams_message_post.sh, which validates the arguments.
Arguments: <team> <channel> <reply_to|NEW> <apply|dry-run> <confirm|no-confirm>
Stdin: the message text (plain text; line breaks are kept)
Stdout: one TSV line: posted_at, id, reply_to, url
"""
import datetime
import html
import sys
import urllib.parse

import imc_teams_graph as g
import imc_teams_message_list as ml


def to_html(text):
    return "<br>".join(html.escape(line) for line in text.split("\n"))


def ask(question):
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write(question)
            tty.flush()
            return tty.readline().strip() in ("y", "Y")
    except OSError:
        g.fail("--confirm needs an interactive terminal.", "rerun from a terminal, or omit --confirm.")


def main():
    team_name, channel_name, reply_to, mode, confirm = sys.argv[1:6]
    text = sys.stdin.read().rstrip("\n")
    if not text.strip():
        g.fail("The message on stdin is empty.", "pipe the text to post into this script.")

    print("=== %s ===" % "imc_teams_message_post.sh", file=sys.stderr)
    print("team     : %s" % team_name, file=sys.stderr)
    print("channel  : %s" % channel_name, file=sys.stderr)
    print("reply_to : %s" % ("(new thread)" if reply_to == "NEW" else reply_to), file=sys.stderr)
    print("dry-run  : %s" % (mode == "dry-run"), file=sys.stderr)
    print("text     :", file=sys.stderr)
    for line in text.split("\n"):
        print("  | %s" % line, file=sys.stderr)
    print("=" * 40, file=sys.stderr)

    team_id, channel_id = ml.find_channel(team_name, channel_name)
    path = "/teams/%s/channels/%s/messages" % (urllib.parse.quote(team_id), urllib.parse.quote(channel_id))
    if reply_to != "NEW":
        # Fails here, before posting, if the thread does not exist.
        g.get("%s/%s?$select=id" % (path, urllib.parse.quote(reply_to)))
        path += "/%s/replies" % urllib.parse.quote(reply_to)

    if mode == "dry-run":
        g.stderr("Dry run: nothing was posted.")
        print("Next: rerun without --dry-run to post.", file=sys.stderr)
        return 0
    if confirm == "confirm" and not ask("Post this to Teams? [y/N] "):
        g.stderr("Aborted; nothing was posted.")
        print("Next: rerun when you are ready.", file=sys.stderr)
        return 1

    message = g.post(path, {"body": {"contentType": "html", "content": to_html(text)}})
    posted_at = ml.parse_time(message["createdDateTime"]).astimezone(ml.JST).isoformat()
    print("%s\t%s\t%s\t%s" % (posted_at, message["id"], "" if reply_to == "NEW" else reply_to,
                              message.get("webUrl") or ""))
    g.stderr("Posted to %s / %s." % (team_name, channel_name))
    print("Next: reply to this thread with %s as <reply_to>." % (message["id"] if reply_to == "NEW" else reply_to),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
