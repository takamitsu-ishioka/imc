"""Sign in to Microsoft Graph for Teams, or show the current sign-in state.

Called only through imc_teams_auth.sh, which validates the arguments.
Arguments: <login|status>
"""
import sys
import time

import imc_teams_graph as g


def main():
    action = sys.argv[1]
    if action == "login":
        scope = g.device_code_login()
        g.stderr("Signed in. Granted scopes: %s" % scope)
    token = g.load_token()
    me = g.get("/me?$select=displayName,userPrincipalName,id")
    remaining = int(token["expires_at"] - time.time())
    print("%s\t%s\t%s" % (me.get("displayName"), me.get("userPrincipalName"), me.get("id")))
    g.stderr("Access token valid for %ds (refreshed automatically). Scopes: %s" % (remaining, token.get("scope", "")))
    if "ChannelMessage.Read.All" not in token.get("scope", ""):
        g.stderr("ChannelMessage.Read.All is NOT granted: channel messages cannot be read.")
        print("Next: ask a tenant admin to grant admin consent to the app, then run login again.", file=sys.stderr)
        return 1
    print("Next: list your channels with imc_teams_channel_list.sh tsv", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
