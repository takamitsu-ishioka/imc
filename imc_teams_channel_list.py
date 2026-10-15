"""List the Teams teams and channels you are a member of.

Called only through imc_teams_channel_list.sh, which validates the arguments.
Arguments: <tsv|json>
"""
import json
import sys
import urllib.parse

import imc_teams_graph as g


def main():
    output_format = sys.argv[1]
    rows = []
    teams = g.get_all("/me/joinedTeams?$select=id,displayName")
    for i, team in enumerate(teams, 1):
        g.stderr("%d/%d %s" % (i, len(teams), team["displayName"]))
        path = "/teams/%s/channels?$select=id,displayName,membershipType" % urllib.parse.quote(team["id"])
        for ch in g.get_all(path):
            rows.append({
                "team": team["displayName"],
                "channel": ch["displayName"],
                "membership": ch.get("membershipType", ""),
                "team_id": team["id"],
                "channel_id": ch["id"],
            })
    if output_format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print("\t".join(r[k] for k in ("team", "channel", "membership", "team_id", "channel_id")))
    g.stderr("%d teams, %d channels" % (len(teams), len(rows)))
    print("Next: read a channel with imc_teams_message_list.sh '<team>' '<channel>' <since> tsv", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
