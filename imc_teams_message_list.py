"""Pull messages (and their replies) posted to one Teams channel since a given time.

Called only through imc_teams_message_list.sh, which validates the arguments.
Arguments: <team_name> <channel_name> <since> <tsv|json>
"""
import datetime
import html
import json
import re
import sys
import urllib.parse

import imc_teams_graph as g

JST = datetime.timezone(datetime.timedelta(hours=9))
FIELDS = ["posted_at", "team", "channel", "from", "addressed_to_me", "reply_to", "id", "text", "url"]
MAX_PAGES = 50


def parse_time(value):
    dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=JST)


def plain_text(message):
    body = (message.get("body") or {}).get("content") or ""
    text = re.sub(r"<br\s*/?>|</p>|</div>", " ", body, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return " ".join(text.split())


def find_channel(team_name, channel_name):
    for team in g.get_all("/me/joinedTeams?$select=id,displayName"):
        if team["displayName"] != team_name:
            continue
        path = "/teams/%s/channels?$select=id,displayName" % urllib.parse.quote(team["id"])
        for ch in g.get_all(path):
            if ch["displayName"] == channel_name:
                return team["id"], ch["id"]
        g.fail("Channel '%s' not found in team '%s'." % (channel_name, team_name),
               "check the exact names with imc_teams_channel_list.sh tsv")
    g.fail("Team '%s' not found among the teams you are a member of." % team_name,
           "check the exact names with imc_teams_channel_list.sh tsv")


def record(message, team_name, channel_name, my_id, reply_to):
    mentioned = any(((m.get("mentioned") or {}).get("user") or {}).get("id") == my_id
                    for m in message.get("mentions") or [])
    sender = (message.get("from") or {}).get("user") or (message.get("from") or {}).get("application") or {}
    return {
        "posted_at": parse_time(message["createdDateTime"]).astimezone(JST).isoformat(),
        "team": team_name,
        "channel": channel_name,
        "from": sender.get("displayName") or "",
        "addressed_to_me": mentioned,
        "reply_to": reply_to,
        "id": message["id"],
        "text": plain_text(message),
        "url": message.get("webUrl") or "",
    }


def wanted(message, since):
    return (message.get("messageType") == "message"
            and not message.get("deletedDateTime")
            and parse_time(message["createdDateTime"]) >= since)


def main():
    team_name, channel_name, since_arg, output_format = sys.argv[1:5]
    try:
        since = parse_time(since_arg)
    except ValueError:
        g.fail("since is not ISO 8601: %s" % since_arg, "use e.g. 2026-10-15 or 2026-10-15T09:00")
    my_id = g.get("/me?$select=id")["id"]
    team_id, channel_id = find_channel(team_name, channel_name)

    pages = {"n": 0}

    def stop(values):
        # Messages come newest-activity first; once a whole page was last touched
        # before since, nothing older can contain new posts or replies.
        pages["n"] += 1
        g.stderr("page %d: %d messages" % (pages["n"], len(values)))
        last = [parse_time(m.get("lastModifiedDateTime") or m["createdDateTime"]) for m in values]
        return pages["n"] >= MAX_PAGES or not values or max(last) < since

    path = "/teams/%s/channels/%s/messages?$top=50&$expand=replies" % (
        urllib.parse.quote(team_id), urllib.parse.quote(channel_id))
    rows = []
    for root in g.get_all(path, stop=stop):
        if wanted(root, since):
            rows.append(record(root, team_name, channel_name, my_id, ""))
        for reply in root.get("replies") or []:
            if wanted(reply, since):
                rows.append(record(reply, team_name, channel_name, my_id, root["id"]))
    rows.sort(key=lambda r: r["posted_at"])

    if output_format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print("\t".join(str(r[k]).lower() if k == "addressed_to_me" else r[k].replace("\t", " ")
                            for k in FIELDS))
    g.stderr("%s / %s: %d messages since %s" % (team_name, channel_name, len(rows), since.isoformat()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
