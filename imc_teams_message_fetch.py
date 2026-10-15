"""Pull messages posted since a given time to every channel listed on stdin.

Called only through imc_teams_message_fetch.sh, which validates the arguments.
Arguments: <since> <tsv|json>. Stdin: team<TAB>channel per line.
Team and channel ids are resolved once for the whole run, not per channel.
"""
import sys
import urllib.parse

import imc_teams_graph as g
import imc_teams_message_list as ml


def read_pairs(lines):
    pairs = []
    for n, line in enumerate(lines, 1):
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) != 2 or not cols[0] or not cols[1]:
            g.fail("stdin line %d is not team<TAB>channel: %r" % (n, line),
                   "fix the channel list (one team<TAB>channel per line).")
        pairs.append((cols[0], cols[1]))
    if not pairs:
        g.fail("The channel list on stdin is empty.", "add team<TAB>channel lines to the list.")
    return pairs


def main():
    since_arg, output_format = sys.argv[1:3]
    since = ml.parse_since(since_arg)
    pairs = read_pairs(sys.stdin)
    my_id = g.get("/me?$select=id")["id"]

    teams = {t["displayName"]: t["id"] for t in g.get_all("/me/joinedTeams?$select=id,displayName")}
    channels = {}  # team name -> {channel name: channel id}
    rows, missing = [], []
    for i, (team_name, channel_name) in enumerate(pairs, 1):
        g.stderr("%d/%d %s / %s" % (i, len(pairs), team_name, channel_name))
        if team_name not in teams:
            missing.append("team '%s'" % team_name)
            continue
        if team_name not in channels:
            path = "/teams/%s/channels?$select=id,displayName" % urllib.parse.quote(teams[team_name])
            channels[team_name] = {c["displayName"]: c["id"] for c in g.get_all(path)}
        channel_id = channels[team_name].get(channel_name)
        if channel_id is None:
            missing.append("channel '%s' in team '%s'" % (channel_name, team_name))
            continue
        rows += ml.fetch(teams[team_name], channel_id, team_name, channel_name, since, my_id)

    rows.sort(key=lambda r: r["posted_at"])
    ml.write(rows, output_format)
    g.stderr("%d messages from %d channels since %s" % (len(rows), len(pairs) - len(missing), since.isoformat()))
    if missing:
        g.stderr("Not found (skipped): %s" % ", ".join(missing))
        print("Next: check the exact names with imc_teams_channel_list.sh tsv and fix the list.", file=sys.stderr)
        return 1
    print("Next: pass the output to whatever reads it (nothing is stored or notified by this script).",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
