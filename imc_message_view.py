"""Full-screen viewer for unread messages (mail and Teams). Called only through
imc_message_view.sh, which validates the arguments.
Arguments: <query> (a notmuch query; the wrapper turns NEW into
"tag:unread and not tag:suspicious and not tag:nonessential").

Layout:
  left         the messages, with checkboxes
  right top    the raw header of the message being viewed
  right bottom its body: every text part decoded, then a list of the other parts
  bottom       the key bindings

The list is read once at start (r reloads). Messages are identified by
Message-ID, not by file, because changing tags renames Maildir files.
"Delete" tags the message deleted (and read): the file stays, because imc
never deletes local mail, and notmuch-config hides tag:deleted from searches.
f registers the sender of the checked messages (or the focused one) as
nonessential: it appends a from rule to tag_rules.local.tsv (gitignored,
since a sender list says which services you use) and re-applies both rules
files to every message, so past and future mail from that sender is tagged
nonessential. NEW leaves nonessential (and suspicious) mail out; to undo a
registration later, delete its line from tag_rules.local.tsv.
t opens the tag filter: every tag in the index (plus deleted and spam, which
notmuch-config hides unless asked for) with a three-way switch each: [ ] any,
[+] must have it, [-] must not have it. Space cycles the switch, Enter applies
the resulting query ("tag:a and not tag:b ..."), Escape closes the frame
without changing anything. It starts from the current query when that query
is of this simple form (NEW is), and from all [ ] otherwise.
Mouse: dragging selects text inside the one pane where the drag started (the
terminal's own selection would run across the panes), and releasing copies
it to the Windows clipboard through clip.exe. Lines folded to fit the pane
are joined back, so a long URL is copied whole. A click focuses the pane (and
the row, in the list); the wheel scrolls the pane under the pointer.
"""
import curses
import datetime
import email
import email.policy
import json
import locale
import os
import re
import subprocess
import sys
import unicodedata

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NOTMUCH_CONFIG = os.path.join(SCRIPT_DIR, "_var", "notmuch-config")
MAIL_ROOT = os.path.join(SCRIPT_DIR, "_var", "maildir")
RULES = os.path.join(SCRIPT_DIR, "tag_rules.tsv")
LOCAL_RULES = os.path.join(SCRIPT_DIR, "tag_rules.local.tsv")
NONESSENTIAL = "nonessential"
KEYS = ("v:open/close right pane  Enter:view  Tab/←→:focus  ↑↓ PgUp/PgDn Home/End:move in focus  Space:check (check,move,check = range)  "
        "a/A:all/none  t:tag filter  d:delete  f:sender nonessential  u:undo  r:reload  q:quit  "
        "mouse drag:copy in one pane  wheel:scroll")
PANES = ("list", "header", "body")   # Tab cycles in this order
# Ctrl+Home / Ctrl+End have no curses constant; ncurses names them kHOM5 / kEND5.
TOP_KEYS = (curses.KEY_HOME, "g")
END_KEYS = (curses.KEY_END, "G")
TOP_NAMES = (b"kHOM5",)
END_NAMES = (b"kEND5",)
# ncurses turns on press/release reports only; 1002 adds motion while a button
# is held, so the selection can be drawn during the drag.
DRAG_ON, DRAG_OFF = "\033[?1002h", "\033[?1002l"
WHEEL_UP = curses.BUTTON4_PRESSED
WHEEL_DOWN = curses.BUTTON5_PRESSED


def key_name(key):
    return curses.keyname(key) if isinstance(key, int) else b""


def notmuch(*args):
    env = dict(os.environ, NOTMUCH_CONFIG=NOTMUCH_CONFIG)
    return subprocess.run(["notmuch", *args], env=env, capture_output=True, text=True, check=True).stdout


def char_width(c):
    return 2 if unicodedata.east_asian_width(c) in "WF" else (0 if unicodedata.combining(c) else 1)


def fit(text, cols):
    """Cut text to at most cols terminal cells, then pad it with spaces to exactly cols."""
    out, used = [], 0
    for c in text.replace("\t", " "):
        if not c.isprintable():
            c = " "
        w = char_width(c)
        if used + w > cols:
            break
        out.append(c)
        used += w
    return "".join(out) + " " * (cols - used)


def wrap(text, cols):
    """Break text into lines of at most cols cells (long lines are folded, not cut).
    Returns (lines, folded): folded[i] is True when line i continues on line i+1."""
    lines, folded = [], []
    for raw in text.splitlines() or [""]:
        line, used = "", 0
        for c in raw.replace("\t", "    "):
            if not c.isprintable():
                continue
            w = char_width(c)
            if used + w > cols:
                lines.append(line)
                folded.append(True)
                line, used = "", 0
            line += c
            used += w
        lines.append(line)
        folded.append(False)
    return lines, folded


def char_at(line, cell):
    """Index of the character of line drawn at terminal cell offset cell
    (len(line) when the cell is past its end)."""
    used = 0
    for i, c in enumerate(line):
        used += char_width(c)
        if used > cell:
            return i
    return len(line)


def copy_to_clipboard(text):
    """Put text on the Windows clipboard. clip.exe reads UTF-16LE (no BOM: a
    BOM would be pasted as a character) and expects CRLF line ends."""
    data = text.replace("\n", "\r\n").encode("utf-16-le")
    subprocess.run(["clip.exe"], input=data, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def load(query):
    result = subprocess.run([os.path.join(SCRIPT_DIR, "imc_mail_list.sh"), query, "json"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(1)
    rows = sorted(json.loads(result.stdout or "[]"), key=lambda r: r["date_iso"])
    items = []
    for r in rows:
        subject = " ".join((r["subject"] or "").split())
        if r["account"].startswith("teams-"):
            # A Teams message has no subject of its own (imc keeps the stored Subject
            # free of message text for the ntfy digest), so show the head of the text here.
            head = teams_text_head(r["path"])
            if head:
                subject = "%s  %s" % (subject, head)
        items.append({
            "mid": r["message_id"],
            "date": r["date_iso"][5:16].replace("T", " "),
            "account": r["account"],
            "from": " ".join((r["from_name"] or r["from_addr"] or "").split()),
            "addr": (r["from_addr"] or "").strip().lower(),
            "subject": subject,
        })
    return items


def teams_text_head(path, limit=200):
    """First characters of a Teams message stored by imc_teams_fetch.sh: the text
    before the trailing link line, on one line. "" if the file cannot be read."""
    try:
        with open(os.path.join(MAIL_ROOT, path), "rb") as f:
            msg = email.message_from_binary_file(f, policy=email.policy.default)
        part = msg.get_body(preferencelist=("plain",))
        lines = (part.get_content() if part else "").rstrip("\n").split("\n")
    except (OSError, LookupError, ValueError):
        return ""
    if lines and lines[-1].startswith("https://"):
        lines.pop()
    return " ".join(" ".join(lines).split())[:limit]


def read_message(mid):
    """Return (raw header text, body text) for one message, looked up by Message-ID."""
    files = notmuch("search", "--output=files", "--exclude=false", "id:" + mid).split("\n")
    if not files or not files[0]:
        return "(not in the index any more)", ""
    with open(files[0], "rb") as f:
        raw = f.read()
    head, _, _ = raw.partition(b"\n\n")
    if b"\r\n\r\n" in raw[:len(head) + 4]:
        head = raw.partition(b"\r\n\r\n")[0]
    header_text = head.decode("utf-8", errors="replace")

    msg = email.message_from_bytes(raw, policy=email.policy.default)
    texts, others = [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        name = part.get_filename()
        if ctype.startswith("text/") and not name and part.get_content_disposition() != "attachment":
            try:
                content = part.get_content()
            except (LookupError, ValueError):
                content = part.get_payload(decode=True).decode("utf-8", errors="replace")
            if ctype == "text/html" and texts:
                others.append("%s (html alternative, %d bytes)" % (ctype, len(content)))
                continue
            texts.append(content if len(texts) == 0 else "--- %s ---\n%s" % (ctype, content))
        else:
            size = len(part.get_payload(decode=True) or b"")
            others.append("%s  %s  %d bytes" % (ctype, name or "(no name)", size))
    body = "\n\n".join(texts) or "(no text part)"
    if others:
        body += "\n\n=== other parts ===\n" + "\n".join("  " + o for o in others)
    return header_text, body


def sender_rule(addr):
    """The tag_rules from-regex for one address. imc_tag_apply matches from
    rules against "<name> <address>", so anchor on the address at the end."""
    return "(^| )%s$" % re.escape(addr)


def retag():
    """Re-apply both rules files to every message, as imc_morning_run.sh does.
    Returns "" on success, else the tail of the error output."""
    listing = subprocess.run([os.path.join(SCRIPT_DIR, "imc_mail_list.sh"), "*", "json"],
                             capture_output=True, text=True)
    if listing.returncode != 0:
        lines = listing.stderr.strip().splitlines()
        return lines[-1] if lines else "imc_mail_list.sh failed"
    rules = [RULES] + ([LOCAL_RULES] if os.path.exists(LOCAL_RULES) else [])
    applied = subprocess.run([os.path.join(SCRIPT_DIR, "imc_tag_apply.sh"), *rules],
                             input=listing.stdout, capture_output=True, text=True)
    if applied.returncode != 0:
        lines = applied.stderr.strip().splitlines()
        return lines[-1] if lines else "imc_tag_apply.sh failed"
    return ""


def local_rule_lines():
    if not os.path.exists(LOCAL_RULES):
        return []
    with open(LOCAL_RULES, encoding="utf-8") as f:
        return f.read().splitlines()


def write_local_rules(lines):
    with open(LOCAL_RULES, "w", encoding="utf-8") as f:
        f.write("".join(line + "\n" for line in lines))


FILTER_CYCLE = {" ": "+", "+": "-", "-": " "}
FILTER_TERM = re.compile(r"^(not )?tag:([A-Za-z0-9_.-]+)$")


def parse_filter(query):
    """{tag: "+" or "-"} for a query of the form "tag:a and not tag:b ...", else None."""
    states = {}
    for term in query.split(" and "):
        match = FILTER_TERM.match(term.strip())
        if not match:
            return None
        states[match.group(2)] = "-" if match.group(1) else "+"
    return states


def build_filter(tags, states):
    terms = [("tag:%s" if states.get(t) == "+" else "not tag:%s") % t
             for t in tags if states.get(t, " ") != " "]
    return " and ".join(terms) or "*"


class Viewer:
    def __init__(self, screen, query):
        self.screen, self.query = screen, query
        self.items = load(query)
        self.checked = set()   # Message-IDs
        self.cur = 0
        self.top = 0
        self.anchor = None     # index of the last check-on, while only moves follow it
        self.viewed = None     # Message-ID shown on the right
        self.header_lines, self.body_lines = [], []
        self.header_folded, self.body_folded = [], []
        self.header_top = self.body_top = 0
        self.sel = None        # {"pane", "a": (line, char), "b": (line, char)}; a is where the drag began
        self.undo = None       # ("delete", Message-IDs) or ("sender", rule lines added)
        self.status = "%d messages" % len(self.items)
        self.focus = "list"    # the pane that ↑↓ PgUp/PgDn Home/End move
        self.right_open = False  # starts closed; v toggles it, Enter (or Right) opens it

    # --- actions -------------------------------------------------------
    def toggle(self):
        if not self.items:
            return
        mid = self.items[self.cur]["mid"]
        if mid in self.checked:
            self.checked.discard(mid)
            self.anchor = None
            return
        if self.anchor is not None and self.anchor != self.cur:
            lo, hi = sorted((self.anchor, self.cur))
            self.checked.update(it["mid"] for it in self.items[lo:hi + 1])
            self.status = "checked %d-%d" % (lo + 1, hi + 1)
            self.anchor = None
        else:
            self.checked.add(mid)
            self.anchor = self.cur

    def view(self):
        if not self.items:
            return
        self.right_open = True
        index = self.cur   # the focused item; checkboxes are only for d
        mid = self.items[index]["mid"]
        header, body = read_message(mid)
        _, cols = self.screen.getmaxyx()
        width = cols - self.left_width() - 1
        self.header_lines, self.header_folded = wrap(header, width)
        self.body_lines, self.body_folded = wrap(body, width)
        self.header_top = self.body_top = 0
        self.sel = None
        self.viewed = mid
        notmuch("tag", "-unread", "--", "id:" + mid)
        self.items[index]["read"] = True
        self.status = "viewing %d" % (index + 1)

    def delete(self):
        mids = [it["mid"] for it in self.items if it["mid"] in self.checked]
        if not mids and self.items:
            mids = [self.items[self.cur]["mid"]]
        if not mids:
            return
        query = []
        for mid in mids:
            query += (["or"] if query else []) + ["id:" + mid]
        notmuch("tag", "+deleted", "-unread", "--", *query)
        self.undo = ("delete", mids)
        gone = set(mids)
        self.items = [it for it in self.items if it["mid"] not in gone]
        self.checked -= gone
        self.anchor = None
        if self.viewed in gone:
            self.viewed, self.header_lines, self.body_lines = None, [], []
        self.cur = min(self.cur, max(len(self.items) - 1, 0))
        self.status = "deleted %d (u to undo)" % len(mids)

    def undo_last(self):
        if not self.undo:
            self.status = "nothing to undo"
            return
        kind, values = self.undo
        if kind == "delete":
            query = []
            for mid in values:
                query += (["or"] if query else []) + ["id:" + mid]
            notmuch("tag", "-deleted", "+unread", "--", *query)
            self.status = "restored %d" % len(values)
        else:
            added = set(values)
            write_local_rules([line for line in local_rule_lines() if line not in added])
            error = retag()
            self.status = ("unregistered %d sender(s)" % len(values)) if not error else "retag failed: " + error
        self.undo = None
        self.reload(keep_status=True)

    def ask(self, question):
        """Show question in the status bar and wait for y (True) or anything else (False)."""
        self.status = question + " [y/N]"
        self.draw()
        return self.screen.get_wch() in ("y", "Y")

    def register_senders(self):
        """Register the senders of the checked messages (or the focused one) as nonessential."""
        targets = [it for it in self.items if it["mid"] in self.checked]
        if not targets and self.items:
            targets = [self.items[self.cur]]
        addrs = sorted({it["addr"] for it in targets if it["addr"]})
        if not addrs:
            self.status = "no sender address to register"
            return
        lines = local_rule_lines()
        known = {line.split("\t")[2] for line in lines
                 if line.count("\t") >= 2 and line.split("\t")[0] == NONESSENTIAL}
        new = [a for a in addrs if sender_rule(a) not in known]
        if not new:
            self.status = "already nonessential: %s" % ", ".join(addrs)
            return
        shown = new[0] if len(new) == 1 else "%s and %d more" % (new[0], len(new) - 1)
        if not self.ask("mark %s nonessential (all mail, past and future)?" % shown):
            self.status = "not registered"
            return
        if not lines and os.path.exists(LOCAL_RULES + ".template"):
            with open(LOCAL_RULES + ".template", encoding="utf-8") as f:
                lines = f.read().splitlines()
        today = datetime.date.today().isoformat()
        added = ["%s\tfrom\t%s\timc_message_view.sh f %s" % (NONESSENTIAL, sender_rule(a), today)
                 for a in new]
        write_local_rules(lines + added)
        self.status = "tagging..."
        self.draw()
        error = retag()
        if error:
            self.status = "rule added but retag failed: " + error
            return
        self.undo = ("sender", added)
        self.reload(keep_status=True)
        self.status = "nonessential: %s (u to undo)" % shown

    def choose_filter(self):
        """The tag filter frame (a selection frame of the layered input model):
        Space cycles [ ] -> [+] -> [-], Enter applies, Escape cancels."""
        tags = sorted(set(notmuch("search", "--output=tags", "--exclude=false", "*").split())
                      | {"deleted", "spam"})
        parsed = parse_filter(self.query)
        states = dict(parsed or {})
        tags += sorted(t for t in states if t not in tags)
        cur = 0
        note = "" if parsed is not None else "  (current query is not a plain tag filter; starting empty)"
        while True:
            self.draw()
            rows, cols = self.screen.getmaxyx()
            width = min(cols - 4, 72)
            height = min(rows - 4, len(tags) + 4)
            y0, x0 = (rows - height) // 2, (cols - width) // 2
            visible = height - 4
            top = min(max(0, cur - visible + 1), max(0, len(tags) - visible))
            lines = [" tag filter: Space [ ]>[+]>[-]  Enter apply  Esc cancel" + note, ""]
            for i in range(top, min(len(tags), top + visible)):
                lines.append("  [%s] %s" % (states.get(tags[i], " "), tags[i]))
            lines += [""] * (height - 2 - len(lines))
            lines.append(" -> " + build_filter(tags, states))
            lines.append("")
            for row, text in enumerate(lines[:height]):
                attr = curses.A_REVERSE if row == 2 + cur - top and 2 <= row < height - 2 else curses.A_NORMAL
                self.screen.addstr(y0 + row, x0, fit(text, width), attr | curses.A_BOLD)
            self.screen.refresh()
            key = self.screen.get_wch()
            if key in (curses.KEY_DOWN, "j"):
                cur = min(cur + 1, len(tags) - 1)
            elif key in (curses.KEY_UP, "k"):
                cur = max(cur - 1, 0)
            elif key == " ":
                states[tags[cur]] = FILTER_CYCLE[states.get(tags[cur], " ")]
            elif key in ("\n", "\r", curses.KEY_ENTER):
                query = build_filter(tags, states)
                if query != self.query:
                    self.query = query
                    self.checked = set()
                    self.reload(keep_status=True)
                self.status = "%d messages" % len(self.items)
                return
            elif key in ("\x1b", "q"):
                self.status = "filter unchanged"
                return

    def reload(self, keep_status=False):
        focus = self.items[self.cur]["mid"] if self.items else None
        self.items = load(self.query)
        mids = [it["mid"] for it in self.items]
        self.checked &= set(mids)
        self.cur = mids.index(focus) if focus in mids else min(self.cur, max(len(mids) - 1, 0))
        self.anchor = None
        if not keep_status:
            self.status = "reloaded: %d messages" % len(self.items)

    # --- drawing -------------------------------------------------------
    def left_width(self):
        _, cols = self.screen.getmaxyx()
        return max(30, cols * 9 // 20) if self.right_open else cols - 1

    def toggle_right(self):
        """Open or close the right panes. Closing gives the focus back to the list."""
        self.right_open = not self.right_open
        if not self.right_open:
            self.focus = "list"
        elif self.viewed:
            self.view_again()   # re-wrap for the pane width
        self.status = "right pane %s" % ("open" if self.right_open else "closed")

    def title_attr(self, pane):
        """The focused pane's title is drawn reversed, the others underlined."""
        return curses.A_REVERSE | curses.A_BOLD if pane == self.focus else curses.A_UNDERLINE

    def position(self, pane):
        lines, top = (self.header_lines, self.header_top) if pane == "header" else (self.body_lines, self.body_top)
        return "(%d/%d)" % (min(top + 1, len(lines)), len(lines)) if lines else ""

    def pane_rows(self):
        """Visible text rows of (list, header, body)."""
        rows, _ = self.screen.getmaxyx()
        body_rows = rows - 2
        head_rows = max(3, body_rows * 2 // 5)
        return body_rows, head_rows - 1, body_rows - head_rows

    def move(self, step=None, to=None):
        """Move within the focused pane: by step lines, or to "top" / "end"."""
        list_rows, head_rows, text_rows = self.pane_rows()
        if self.focus == "list":
            last = max(len(self.items) - 1, 0)
            value = self.cur
        elif self.focus == "header":
            last = max(len(self.header_lines) - head_rows, 0)
            value = self.header_top
        else:
            last = max(len(self.body_lines) - text_rows, 0)
            value = self.body_top
        if to == "top":
            value = 0
        elif to == "end":
            value = last
        else:
            value = min(max(value + step, 0), last)
        if self.focus == "list":
            self.cur = value
        elif self.focus == "header":
            self.header_top = value
        else:
            self.body_top = value

    def page(self):
        list_rows, head_rows, text_rows = self.pane_rows()
        return max(1, {"list": list_rows, "header": head_rows, "body": text_rows}[self.focus] - 1)

    def draw(self):
        rows, cols = self.screen.getmaxyx()
        if rows < 8 or cols < 60:
            self.screen.erase()
            self.screen.addstr(0, 0, fit("Window too small", cols - 1))
            self.screen.refresh()
            return
        lw = self.left_width()
        body_rows = rows - 2               # top title line and bottom key line
        rw = cols - lw - 1
        head_rows = max(3, body_rows * 2 // 5)
        self.screen.erase()

        # left pane
        title = " %s  %d/%d  checked %d " % (self.query, self.cur + 1 if self.items else 0,
                                             len(self.items), len(self.checked))
        self.screen.addstr(0, 0, fit(title, lw), self.title_attr("list"))
        list_rows = body_rows
        self.top = min(max(self.top, self.cur - list_rows + 1), self.cur)
        for row in range(list_rows):
            i = self.top + row
            if i >= len(self.items):
                break
            it = self.items[i]
            attr = curses.A_BOLD if it["mid"] in self.checked else curses.A_NORMAL
            if i == self.cur:
                attr |= curses.A_REVERSE
            self.draw_line(1 + row, 0, self.list_line(i), lw, attr, "list", i)

        if not self.right_open:
            bar = "[%s]  %s" % (self.status, KEYS)
            self.screen.addstr(rows - 1, 0, fit(bar, cols - 1), curses.A_REVERSE)
            self.screen.refresh()
            return

        # separator
        for row in range(rows - 1):
            self.screen.addstr(row, lw, "│")

        # right top: raw header
        self.screen.addstr(0, lw + 1, fit(" header %s" % self.position("header"), rw), self.title_attr("header"))
        for row in range(head_rows - 1):
            i = self.header_top + row
            text = self.header_lines[i] if i < len(self.header_lines) else ""
            self.draw_line(1 + row, lw + 1, text, rw, curses.A_NORMAL, "header", i)
        # right bottom: body
        self.screen.addstr(head_rows, lw + 1, fit(" body %s" % self.position("body"), rw), self.title_attr("body"))
        for row in range(body_rows - head_rows):
            i = self.body_top + row
            text = self.body_lines[i] if i < len(self.body_lines) else ""
            self.draw_line(head_rows + 1 + row, lw + 1, text, rw, curses.A_NORMAL, "body", i)

        # bottom: key bindings and status
        bar = "[%s]  %s" % (self.status, KEYS)
        self.screen.addstr(rows - 1, 0, fit(bar, cols - 1), curses.A_REVERSE)
        self.screen.refresh()

    # --- mouse selection -----------------------------------------------
    def list_line(self, i):
        """The text of list row i, cut to the pane width (what the list pane shows)."""
        it = self.items[i]
        box = "[x]" if it["mid"] in self.checked else "[ ]"
        mark = "*" if it["mid"] == self.viewed else (" " if it.get("read") else "N")
        line = "%s%s %s %s %s  %s" % (box, mark, it["date"], fit(it["account"], 8),
                                      fit(it["from"], 12), it["subject"])
        return fit(line, self.left_width()).rstrip()

    def pane_lines(self, pane):
        """(lines, folded) of a pane, in the same characters as drawn."""
        if pane == "header":
            return self.header_lines, self.header_folded
        if pane == "body":
            return self.body_lines, self.body_folded
        lines = [self.list_line(i) for i in range(len(self.items))]
        return lines, [False] * len(lines)

    def pane_box(self, pane):
        """Screen cells (first row, last row, first column, last column) of a pane's text."""
        rows, cols = self.screen.getmaxyx()
        lw = self.left_width()
        _, head_text_rows, _ = self.pane_rows()
        if pane == "list":
            return 1, rows - 2, 0, lw - 1
        if pane == "header":
            return 1, head_text_rows, lw + 1, cols - 1
        return head_text_rows + 2, rows - 2, lw + 1, cols - 1

    def spot_in(self, pane, y, x):
        """(line, cell) of pane under screen cell (y, x), clamped into the pane."""
        y0, y1, x0, x1 = self.pane_box(pane)
        y, x = min(max(y, y0), y1), min(max(x, x0), x1)
        top = {"list": self.top, "header": self.header_top, "body": self.body_top}[pane]
        return top + y - y0, x - x0

    def hit(self, y, x):
        """The pane whose text area holds screen cell (y, x), or None."""
        for pane in (PANES if self.right_open else ("list",)):
            y0, y1, x0, x1 = self.pane_box(pane)
            if y0 <= y <= y1 and x0 <= x <= x1:
                return pane
        return None

    def selection_span(self, pane, i, text):
        """The [start, end) character range of line i that is selected, or None."""
        if not self.sel or self.sel["pane"] != pane:
            return None
        a, b = sorted((self.sel["a"], self.sel["b"]))
        if i < a[0] or i > b[0]:
            return None
        start = a[1] if i == a[0] else 0
        end = b[1] + 1 if i == b[0] else len(text)
        return (start, min(end, len(text))) if start < end else None

    def draw_line(self, y, x, text, width, attr, pane, i):
        """Draw one pane line, the selected part of it reversed."""
        text = fit(text, width)
        span = self.selection_span(pane, i, text.rstrip())
        if not span:
            self.screen.addstr(y, x, text, attr)
            return
        start, end = span
        for part, part_attr in ((text[:start], attr), (text[start:end], attr ^ curses.A_REVERSE),
                                (text[end:], attr)):
            if part:
                self.screen.addstr(y, x, part, part_attr)
                x += sum(char_width(c) for c in part)

    def selected_text(self):
        lines, folded = self.pane_lines(self.sel["pane"])
        a, b = sorted((self.sel["a"], self.sel["b"]))
        out = []
        for i in range(a[0], min(b[0], len(lines) - 1) + 1):
            text = lines[i].rstrip() if self.sel["pane"] == "list" else lines[i]
            start = a[1] if i == a[0] else 0
            end = b[1] + 1 if i == b[0] else len(text)
            out.append(text[start:end])
            if i < b[0]:
                out.append("" if folded[i] else "\n")
        return "".join(out)

    def mouse(self):
        try:
            _, x, y, _, state = curses.getmouse()
        except curses.error:
            return
        pane = self.hit(y, x)
        if state & (WHEEL_UP | WHEEL_DOWN):
            if pane:
                focus = self.focus
                self.focus = pane
                self.move(-3 if state & WHEEL_UP else 3)
                self.focus = focus
            return
        if state & curses.BUTTON1_PRESSED:
            self.sel = None
            if pane:
                line, cell = self.spot_in(pane, y, x)
                lines, _ = self.pane_lines(pane)
                if line < len(lines):
                    start = (line, char_at(lines[line], cell))
                    self.sel = {"pane": pane, "a": start, "b": start, "drag": True}
            return
        if not self.sel or not self.sel.get("drag"):
            return
        # Dragging out of the pane does not leave it: the point is clamped into it.
        pane = self.sel["pane"]
        line, cell = self.spot_in(pane, y, x)
        lines, _ = self.pane_lines(pane)
        line = min(line, len(lines) - 1)
        self.sel["b"] = (line, char_at(lines[line], cell))
        if state & curses.BUTTON1_RELEASED:
            self.sel["drag"] = False
            if self.sel["a"] == self.sel["b"]:
                self.click(pane, line)
                return
            text = self.selected_text()
            try:
                copy_to_clipboard(text)
                self.status = "copied %d characters" % len(text)
            except (OSError, subprocess.CalledProcessError) as error:
                self.status = "clip.exe failed: %s" % error

    def click(self, pane, line):
        """A click without a drag: focus the pane, and in the list the row."""
        self.sel = None
        if pane != "list" and not self.right_open:
            return
        self.focus = pane
        if pane == "list" and line < len(self.items):
            self.cur = line
            self.anchor = None

    # --- loop ----------------------------------------------------------
    def run(self):
        curses.curs_set(0)
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        curses.mouseinterval(0)   # report press and release, not clicks
        sys.stdout.write(DRAG_ON)
        sys.stdout.flush()
        while True:
            self.draw()
            key = self.screen.get_wch()
            if key == curses.KEY_MOUSE:
                self.mouse()
                continue
            if self.sel and not self.sel.get("drag"):
                self.sel = None   # any key clears a finished selection
            if key in (curses.KEY_DOWN, "j"):
                self.move(1)
            elif key in (curses.KEY_UP, "k"):
                self.move(-1)
            elif key == curses.KEY_NPAGE:
                self.move(self.page())
            elif key == curses.KEY_PPAGE:
                self.move(-self.page())
            elif key in TOP_KEYS or key_name(key) in TOP_NAMES:
                self.move(to="top")
            elif key in END_KEYS or key_name(key) in END_NAMES:
                self.move(to="end")
            elif key == "\t" and self.right_open:
                self.focus = PANES[(PANES.index(self.focus) + 1) % len(PANES)]
            elif key == curses.KEY_BTAB and self.right_open:
                self.focus = PANES[(PANES.index(self.focus) - 1) % len(PANES)]
            elif key in (curses.KEY_LEFT, "h"):
                self.focus = "list"
            elif key in (curses.KEY_RIGHT, "l"):
                if not self.right_open:
                    self.toggle_right()
                self.focus = "body"
            elif key == " ":
                self.toggle()
            elif key == "a":
                self.checked = {it["mid"] for it in self.items}
                self.anchor = None
            elif key == "A":
                self.checked = set()
                self.anchor = None
            elif key == "v" and self.right_open:
                self.toggle_right()
            elif key in ("v", "\n", "\r", curses.KEY_ENTER):
                self.view()
            elif key == "d":
                self.delete()
            elif key == "t":
                self.choose_filter()
            elif key == "f":
                self.register_senders()
            elif key == "u":
                self.undo_last()
            elif key == "r":
                self.reload()
            elif key == curses.KEY_RESIZE:
                if self.viewed:
                    self.view_again()
            elif key in ("q", "\x1b"):
                return

    def view_again(self):
        """Re-wrap the viewed message for a new window width."""
        mid = self.viewed
        header, body = read_message(mid)
        _, cols = self.screen.getmaxyx()
        width = cols - self.left_width() - 1
        self.header_lines, self.header_folded = wrap(header, width)
        self.body_lines, self.body_folded = wrap(body, width)
        self.sel = None


def main():
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    query = sys.argv[1]
    try:
        curses.wrapper(lambda screen: Viewer(screen, query).run())
    finally:
        sys.stdout.write(DRAG_OFF)
        sys.stdout.flush()
    print("imc_message_view.sh: done. Next: run it again any time; deleted messages "
          "can be restored with notmuch tag -deleted id:<Message-ID>.", file=sys.stderr)


if __name__ == "__main__":
    main()
