"""Full-screen viewer for unread messages (mail and Teams). Called only through
imc_message_view.sh, which validates the arguments.
Arguments: <query> (a notmuch query; the wrapper turns NEW into tag:unread).

Layout:
  left         the messages, with checkboxes
  right top    the raw header of the message being viewed
  right bottom its body: every text part decoded, then a list of the other parts
  bottom       the key bindings

The list is read once at start (r reloads). Messages are identified by
Message-ID, not by file, because changing tags renames Maildir files.
"Delete" tags the message deleted (and read): the file stays, because imc
never deletes local mail, and notmuch-config hides tag:deleted from searches.
"""
import curses
import email
import email.policy
import json
import locale
import os
import subprocess
import sys
import unicodedata

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NOTMUCH_CONFIG = os.path.join(SCRIPT_DIR, "_var", "notmuch-config")
MAIL_ROOT = os.path.join(SCRIPT_DIR, "_var", "maildir")
KEYS = ("p:right pane on/off  Tab/←→:focus  ↑↓ PgUp/PgDn Home/End:move in focus  Space:check (check,move,check = range)  "
        "a/A:all/none  v:view  d:delete  u:undo  r:reload  q:quit")
PANES = ("list", "header", "body")   # Tab cycles in this order
# Ctrl+Home / Ctrl+End have no curses constant; ncurses names them kHOM5 / kEND5.
TOP_KEYS = (curses.KEY_HOME, "g")
END_KEYS = (curses.KEY_END, "G")
TOP_NAMES = (b"kHOM5",)
END_NAMES = (b"kEND5",)


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
    """Break text into lines of at most cols cells (long lines are folded, not cut)."""
    lines = []
    for raw in text.splitlines() or [""]:
        line, used = "", 0
        for c in raw.replace("\t", "    "):
            if not c.isprintable():
                continue
            w = char_width(c)
            if used + w > cols:
                lines.append(line)
                line, used = "", 0
            line += c
            used += w
        lines.append(line)
    return lines


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
        self.header_top = self.body_top = 0
        self.undo = []         # Message-IDs of the last delete
        self.status = "%d messages" % len(self.items)
        self.focus = "list"    # the pane that ↑↓ PgUp/PgDn Home/End move
        self.right_open = True # p closes the right panes so the list takes the whole width

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
        self.header_lines, self.body_lines = wrap(header, width), wrap(body, width)
        self.header_top = self.body_top = 0
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
        self.undo = mids
        gone = set(mids)
        self.items = [it for it in self.items if it["mid"] not in gone]
        self.checked -= gone
        self.anchor = None
        if self.viewed in gone:
            self.viewed, self.header_lines, self.body_lines = None, [], []
        self.cur = min(self.cur, max(len(self.items) - 1, 0))
        self.status = "deleted %d (u to undo)" % len(mids)

    def undo_delete(self):
        if not self.undo:
            self.status = "nothing to undo"
            return
        query = []
        for mid in self.undo:
            query += (["or"] if query else []) + ["id:" + mid]
        notmuch("tag", "-deleted", "+unread", "--", *query)
        self.status = "restored %d" % len(self.undo)
        self.undo = []
        self.reload(keep_status=True)

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
            box = "[x]" if it["mid"] in self.checked else "[ ]"
            mark = "*" if it["mid"] == self.viewed else (" " if it.get("read") else "N")
            line = "%s%s %s %s %s  %s" % (box, mark, it["date"], fit(it["account"], 8),
                                          fit(it["from"], 12), it["subject"])
            attr = curses.A_BOLD if it["mid"] in self.checked else curses.A_NORMAL
            if i == self.cur:
                attr |= curses.A_REVERSE
            self.screen.addstr(1 + row, 0, fit(line, lw), attr)

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
            self.screen.addstr(1 + row, lw + 1, fit(text, rw))
        # right bottom: body
        self.screen.addstr(head_rows, lw + 1, fit(" body %s" % self.position("body"), rw), self.title_attr("body"))
        for row in range(body_rows - head_rows):
            i = self.body_top + row
            text = self.body_lines[i] if i < len(self.body_lines) else ""
            self.screen.addstr(head_rows + 1 + row, lw + 1, fit(text, rw))

        # bottom: key bindings and status
        bar = "[%s]  %s" % (self.status, KEYS)
        self.screen.addstr(rows - 1, 0, fit(bar, cols - 1), curses.A_REVERSE)
        self.screen.refresh()

    # --- loop ----------------------------------------------------------
    def run(self):
        curses.curs_set(0)
        while True:
            self.draw()
            key = self.screen.get_wch()
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
            elif key == "p":
                self.toggle_right()
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
            elif key in ("v", "\n", "\r", curses.KEY_ENTER):
                self.view()
            elif key == "d":
                self.delete()
            elif key == "u":
                self.undo_delete()
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
        self.header_lines, self.body_lines = wrap(header, width), wrap(body, width)


def main():
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    query = sys.argv[1]
    curses.wrapper(lambda screen: Viewer(screen, query).run())
    print("imc_message_view.sh: done. Next: run it again any time; deleted messages "
          "can be restored with notmuch tag -deleted id:<Message-ID>.", file=sys.stderr)


if __name__ == "__main__":
    main()
