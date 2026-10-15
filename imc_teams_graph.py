"""Minimal Microsoft Graph client shared by the imc_teams_* scripts.

Not run directly. Imported by imc_teams_auth.py, imc_teams_channel_list.py and
imc_teams_message_list.py.

Authentication is the OAuth2 device code flow with a public client (no client
secret). Tenant and client ids come from .env through imc_secret_get.sh. The
tokens are generated data, not configuration: the refresh token rotates on
every use, so it cannot live in the hand-written .env. They are kept in
_var/teams/token.json (mode 600, gitignored like the rest of _var/).

Refresh policy: refresh only when the access token has expired or Graph
answers 401, and retry the request once. Refreshing more often than needed
only multiplies the chances of losing a rotated refresh token between
"received" and "saved".
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_DIR = os.path.join(SCRIPT_DIR, "_var", "teams")
TOKEN_FILE = os.path.join(TOKEN_DIR, "token.json")
GRAPH = "https://graph.microsoft.com/v1.0"
# Delegated permissions. ChannelMessage.Read.All needs tenant admin consent.
SCOPES = [
    "offline_access",
    "User.Read",
    "Team.ReadBasic.All",
    "Channel.ReadBasic.All",
    "ChannelMessage.Read.All",
]
EXPIRY_MARGIN_SECONDS = 120
MAX_RETRIES = 3


def stderr(message):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print("%s %s" % (stamp, message), file=sys.stderr)


def fail(message, next_step):
    stderr(message)
    print("Next: %s" % next_step, file=sys.stderr)
    sys.exit(1)


def env(name):
    result = subprocess.run(
        [os.path.join(SCRIPT_DIR, "imc_secret_get.sh"), name],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr, end="")
        fail("Could not read %s from .env." % name,
             "add IMC_TEAMS_TENANT_ID and IMC_TEAMS_CLIENT_ID to .env (see .env.template).")
    return result.stdout.strip()


def authority():
    return "https://login.microsoftonline.com/%s/oauth2/v2.0" % env("IMC_TEAMS_TENANT_ID")


def post_form(url, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            fail("HTTP %d from %s: %s" % (e.code, url, body[:300]), "check the network and retry.")


def save_token(token):
    """Write token.json atomically with mode 600, so that a crash can never
    leave a half-written file in place of a freshly rotated refresh token."""
    os.makedirs(TOKEN_DIR, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=TOKEN_DIR, prefix=".token.", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(token, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, TOKEN_FILE)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def store_response(resp):
    if "access_token" not in resp:
        return False
    save_token({
        "access_token": resp["access_token"],
        "refresh_token": resp.get("refresh_token", ""),
        "expires_at": int(time.time()) + int(resp.get("expires_in", 0)),
        "scope": resp.get("scope", ""),
    })
    return True


def device_code_login():
    """Run the device code flow. The human signs in on any browser; this waits."""
    client_id = env("IMC_TEAMS_CLIENT_ID")
    start = post_form(authority() + "/devicecode",
                      {"client_id": client_id, "scope": " ".join(SCOPES)})
    if "device_code" not in start:
        fail("Device code request failed: %s" % start.get("error_description", start),
             "check IMC_TEAMS_TENANT_ID / IMC_TEAMS_CLIENT_ID and that the app allows public client flows.")
    print("", file=sys.stderr)
    print(start.get("message", "Open %s and enter %s" % (start["verification_uri"], start["user_code"])),
          file=sys.stderr)
    print("", file=sys.stderr)
    interval = int(start.get("interval", 5))
    deadline = time.time() + int(start.get("expires_in", 900))
    while time.time() < deadline:
        time.sleep(interval)
        resp = post_form(authority() + "/token", {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": client_id,
            "device_code": start["device_code"],
        })
        if store_response(resp):
            return resp.get("scope", "")
        error = resp.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        fail("Sign-in failed: %s: %s" % (error, resp.get("error_description", "")),
             "if this says admin consent is required, ask a tenant admin to grant consent to the app, then retry login.")
    fail("The device code expired before sign-in completed.", "run the login again and finish within the time shown.")


def load_token():
    if not os.path.exists(TOKEN_FILE):
        fail("Not signed in to Teams (%s not found)." % TOKEN_FILE,
             "run %s login" % os.path.join(SCRIPT_DIR, "imc_teams_auth.sh"))
    with open(TOKEN_FILE) as f:
        return json.load(f)


def refresh(token):
    resp = post_form(authority() + "/token", {
        "grant_type": "refresh_token",
        "client_id": env("IMC_TEAMS_CLIENT_ID"),
        "refresh_token": token["refresh_token"],
        "scope": " ".join(SCOPES),
    })
    if not store_response(resp):
        fail("Token refresh failed: %s: %s" % (resp.get("error"), resp.get("error_description", "")),
             "run %s login" % os.path.join(SCRIPT_DIR, "imc_teams_auth.sh"))
    return load_token()


def access_token(force_refresh=False):
    token = load_token()
    if force_refresh or token["expires_at"] - EXPIRY_MARGIN_SECONDS <= time.time():
        token = refresh(token)
    return token["access_token"]


def get(path_or_url):
    """GET one Graph resource. Refreshes once on 401 and honours Retry-After on 429/503."""
    url = path_or_url if path_or_url.startswith("https://") else GRAPH + path_or_url
    refreshed = False
    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + access_token(),
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            if e.code == 401 and not refreshed:
                refreshed = True
                access_token(force_refresh=True)
                continue
            if e.code in (429, 503) and attempt < MAX_RETRIES:
                wait = int(e.headers.get("Retry-After", "5"))
                stderr("Graph throttled (HTTP %d); waiting %ds" % (e.code, wait))
                time.sleep(wait)
                continue
            if e.code == 403:
                fail("Graph refused %s (HTTP 403): %s" % (url, body[:300]),
                     "the app probably lacks admin consent for ChannelMessage.Read.All, or you are not a member of that team.")
            fail("Graph error HTTP %d for %s: %s" % (e.code, url, body[:300]), "retry later.")
    fail("Graph kept throttling %s." % url, "retry later.")


def get_all(path, stop=None):
    """Follow @odata.nextLink and return every item. stop(items_of_page) -> True ends early."""
    items, url = [], path
    while url:
        page = get(url)
        values = page.get("value", [])
        items.extend(values)
        if stop is not None and stop(values):
            break
        url = page.get("@odata.nextLink")
    return items
