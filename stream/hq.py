"""Leyline HQ: the one place to run Leyline (stream/admin.py loads it; docs/ADMIN-CONSOLE.md).

The owner opens /wrath/admin and reads, in ten seconds: is everything up, what needs him, what shipped, what Claude
says, and he can leave Claude a note. Everything else is one tap away: the people (search, a person's page, kick,
mute, ban, site-wide sanctions), the realms (hide, relay block), the content tabs, the game tools ported from the GM
console, and the system tabs. Server-rendered, the Leyline look, plain words, works on a phone.

    GET  /wrath/admin                 Home: status strip, Needs you, Releases, Recent changes, From Claude, Note to Claude
    GET  /wrath/admin/inbox           Needs you: every open report and queue, newest first, one-click actions
    GET  /wrath/admin/players         find a person (name, Name#1234, game account, character)
    GET  /wrath/admin/person?acct=X   one person: profile, sanctions, reports, submissions, realms, devices, game actions
    GET  /wrath/admin/game            in the game: announce, kick, mute, rescue to Dalaran, ban, GM tickets (read-only)
    GET  /wrath/admin/notes           every note from Claude, and (owner) every note to Claude
    GET  /wrath/admin/realms          the official realm, community realms (admin.realms_page), relay blocks
    GET  /wrath/admin/api/<what>      the JSON API: me, inbox, search, person, realm, audit, stats, notes
    POST /wrath/admin/api/act         the same actions as the pages (admin.run_action), JSON in and out

The API uses the website cookie plus the CSRF token from api/me (header X-Leyline-CSRF or the field "csrf").
TODO(launcher admin mode): Bearer tokens with an admin scope (stream/social.py's device tokens plus a staff check);
until then the API answers cookie sessions only.

What the owner's PC sends (tools/hq/hq_sync.py, the Autopilot step hq-sync, also run after every deploy run and with
the 3-hourly server check by tools/control/control.py), into WU_HQ_DIR ($WU_PORTAL_DATA/hq):
    changes.json        {"format": 1, "made_at", "steps": [{id, step, title, note, ok, at}], "last_check": {at, ok, id}}
                        (the last ~30 Autopilot steps; ids, names and outcomes only, never a log line)
    claude-notes.json   {"format": 1, "updated_at", "notes": [{id, date, title, items[]}], "ack": [owner note ids]}
                        (Claude writes control/hq-notes.json on the PC; the step checks it and uploads it)
    picked-up-at        the time the PC last downloaded the owner's notes
What HQ writes there:
    owner-notes.jsonl   the owner's notes to Claude, append-only: {id, at, by, text} and {id, status, at, by} lines
Standard library only.
"""
from __future__ import annotations

import html
import json
import os
import re
import secrets
import time
import unicodedata
import urllib.parse
import urllib.request

e = html.escape
A = None   # stream/admin.py (attributes looked up live)


def setup(admin) -> None:
    global A
    A = admin
    register()


def P(name):
    return A.P(name)


# ----------------------------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------------------------

def hq_dir() -> str:
    return os.environ.get("WU_HQ_DIR") or os.path.join(A._portal_data(), "hq")


def _hpath(name: str) -> str:
    return os.path.join(hq_dir(), name)


ISO_RE = re.compile(r"^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d)(?::(\d\d))?Z?$")


def epoch(v) -> float:
    """Seconds for an epoch number or an ISO time ('2026-10-30T12:00:00Z', '2026-10-30 12:00:00'); 0 when unknown."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) if v > 0 else 0.0
    m = ISO_RE.match(str(v or "").strip())
    if not m:
        return 0.0
    try:
        import calendar
        return float(calendar.timegm((int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)),
                                      int(m.group(5)), int(m.group(6) or 0), 0, 0, 0)))
    except (ValueError, OverflowError):
        return 0.0


def ago(v) -> str:
    """'just now', '5 min ago', '3 h ago', '2 days ago', or the date."""
    t = epoch(v)
    if not t:
        return ""
    d = A._now() - t
    if d < 0:
        return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t))
    if d < 90:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400 * 2:
        return f"{int(d // 3600)} h ago"
    if d < 86400 * 30:
        return f"{int(d // 86400)} days ago"
    return time.strftime("%Y-%m-%d", time.gmtime(t))


def clean_text(v, n: int, lines: bool = False) -> str:
    """Printable text, control characters out; newlines kept when lines=True (at most 40)."""
    s = str(v or "").replace("\r\n", "\n").replace("\r", "\n")
    s = "".join(ch if ch == "\n" and lines else (" " if unicodedata.category(ch)[0] == "C" else ch) for ch in s)
    if lines:
        out = [" ".join(x.split()) for x in s.split("\n")]
        while out and not out[-1]:
            out.pop()
        return "\n".join(out[:40]).strip()[:n]
    return " ".join(s.split())[:n]


def _jsonl_tail(path: str, limit_bytes: int = 2_000_000) -> list[dict]:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - limit_bytes))
            raw = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def _append_jsonl(path: str, rec: dict) -> None:
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n"
    with A._lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)


def _fetch_json(url: str, limit: int = 3_000_000, timeout: float = 6):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json, application/json",
                                               "User-Agent": "leyline-hq"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(limit).decode("utf-8"))


# ----------------------------------------------------------------------------------------------
# The status strip
# ----------------------------------------------------------------------------------------------

def realm_name() -> str:
    return str(P("REALM_NAME") or "Wrath Unleashed")


def realm_status() -> dict:
    try:
        st = json.loads(P("status_json")().decode("utf-8"))
        return st if isinstance(st, dict) else {}
    except Exception:   # noqa: BLE001
        return {}


def site_version() -> str:
    """When the site's files last changed: the newest of the portal's own files (the signin step installs them)."""
    t = 0.0
    for p in (P("__file__"), os.path.join(A.HERE, "admin.py"), os.path.join(A.HERE, "hq.py")):
        try:
            t = max(t, os.path.getmtime(p)) if p else t
        except OSError:
            pass
    return A._iso(t) if t else ""


def disk_memory() -> list[tuple[str, str, str, str]]:
    out = []
    try:
        st = os.statvfs(A._portal_data())
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        if total:
            pct = int(round(100 * (total - free) / total))
            out.append(("Disk", "bad" if pct >= 92 else "warn" if pct >= 85 else "good", f"{pct}% used",
                        f"{free / 1e9:.1f} GB free"))
    except (OSError, AttributeError):
        pass
    try:
        mem = {}
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                k, _, v = line.partition(":")
                if k in ("MemTotal", "MemAvailable"):
                    mem[k] = int(v.split()[0])
        if mem.get("MemTotal") and "MemAvailable" in mem:
            pct = int(round(100 * (mem["MemTotal"] - mem["MemAvailable"]) / mem["MemTotal"]))
            out.append(("Memory", "bad" if pct >= 95 else "warn" if pct >= 88 else "good", f"{pct}% used",
                        f"{mem['MemAvailable'] / 1e6:.1f} GB free"))
    except (OSError, ValueError):
        pass
    return out


def status_items() -> list[tuple[str, str, str, str]]:
    """(label, good|warn|bad|"", value, detail) for the strip at the top of Home."""
    out = [("Website", "good", "Up", ("files from " + ago(site_version())) if site_version() else "")]
    st = realm_status()
    if st.get("online"):
        p = st.get("players")
        out.append((realm_name(), "good", "Online", (f"{p} playing" if isinstance(p, int) else "players unknown")
                    + (f", {st['queue']} waiting" if st.get("queue") else "")))
    else:
        out.append((realm_name(), "bad", "Down", "the realm is not answering"))
    try:
        realms, ok = P("community_realms")()
    except Exception:   # noqa: BLE001
        realms, ok = [], False
    out.append(("Relay", "good" if ok else "bad", "Up" if ok else "Down",
                f"{len(realms)} community realm{'s' if len(realms) != 1 else ''} listed" if ok else "the listing is not answering"))
    g = A.gamedata_status()
    out.append(("Browser play", "good" if g.get("gamedata_streaming") else "", "On" if g.get("gamedata_streaming") else "Off",
                "the slim sampler streams" if g.get("gamedata_streaming") else "players use their own game folder"))
    chk = changes().get("last_check") or {}
    if chk.get("at"):
        out.append(("Server check", "good" if chk.get("ok") else "bad", "Passed" if chk.get("ok") else "Failed", ago(chk["at"])))
    else:
        out.append(("Server check", "", "Not sent yet", "the PC sends it with hq-sync"))
    out.extend(disk_memory())
    return out


# ----------------------------------------------------------------------------------------------
# Needs you: every open item, one list
# ----------------------------------------------------------------------------------------------

# (action, target, label, fields, confirm, danger); fields: {name: value} hidden, or {name: ("text", placeholder)}
def _item(kind, ident, label, title, text, at, where, acts, sub="", group=1) -> dict:
    return {"kind": kind, "id": ident, "label": label, "title": title, "text": text, "at": epoch(at), "where": where,
            "acts": acts, "sub": sub, "group": group}


def inbox_items() -> tuple[list[dict], list[str]]:
    """(items, problems): open reports first (newest first), then the queues. problems: sources that did not answer."""
    items, problems = [], []
    ok, bugs, err = A.bug_list("open")
    if not ok:
        problems.append("bug reports (" + err + ")")
    for b in bugs:
        sid = str(b["id"])
        items.append(_item("bug", "bug:" + sid, "Bug report", f"#{sid} from {b['char']}", b["text"], b["created"],
                           "/wrath/admin/reports", [("bug.set", sid, "Seen", {"status": "seen"}, None, False),
                                                    ("bug.set", sid, "Resolve", {"status": "resolved"}, None, False),
                                                    ("bug.set", sid, "Won't fix", {"status": "wontfix"}, None, False)]
                           if b["status"] == "new" else
                           [("bug.set", sid, "Resolve", {"status": "resolved"}, None, False),
                            ("bug.set", sid, "Won't fix", {"status": "wontfix"}, None, False)],
                           sub=f"level {b['level']} · zone {b['zone']} · {b['status']}"))
    store = A.social_store()
    if store is not None:
        try:
            for r in store.reports("open", 200):
                rid = r.get("id")
                if not isinstance(rid, int):
                    continue
                ctx = [m for m in (r.get("context") or []) if isinstance(m, dict) and m.get("from") == r.get("target")]
                body = str(ctx[-1].get("text") or "")[:600] if ctx else "(no message from them in the thread)"
                tgt = str(r.get("target") or "")
                items.append(_item("msg", f"msg:{rid}", "Message report",
                                   f"{str(r.get('target_name') or '?')[:40]} reported by {str(r.get('reporter_name') or '?')[:40]}",
                                   body, r.get("at"), "/wrath/admin/reports",
                                   [("msg.resolve", str(rid), "Done", {"outcome": ("text", "what you did")}, None, False),
                                    ("msg.dismiss", str(rid), "Dismiss", {}, None, False)],
                                   sub=f"{str(r.get('reason') or '')[:40]}" + (f" · {str(r.get('note'))[:160]}" if r.get("note") else ""),
                                   group=0) | {"person": tgt if A.GAME_ACCT_RE.fullmatch(tgt.upper()) else ""})
        except Exception:   # noqa: BLE001
            problems.append("message reports")
    fs = A.forum_store()
    if fs is not None:
        try:
            for r in fs.reports("open", 200):
                rid = str(r["id"])
                acts = ([("forum.post.hide", str(r["post"]), "Hide the post", {}, None, False)] if not r["post_hidden"] else []) + [
                    ("forum.report.done", rid, "Done", {"outcome": ("text", "what you did")}, None, False),
                    ("forum.report.dismiss", rid, "Dismiss", {}, None, False)]
                items.append(_item("forum", f"forum:{rid}", "Forum report",
                                   f"{(r['author_name'] or '?')[:40]} reported by {(r['reporter_name'] or '?')[:40]}",
                                   str(r["post_body"])[:600], r["at"], "/wrath/admin/forum", acts,
                                   sub=f"{r['reason']} · in {str(r['thread_title'] or '?')[:60]}", group=0)
                             | {"person": str(r.get("author") or "")})
        except Exception:   # noqa: BLE001
            problems.append("forum reports")
    for p in A.projects_all():
        pid = p.get("id", "")
        n = len(p.get("reports") or []) if isinstance(p.get("reports"), list) else 0
        if not n or p.get("hidden") or not A.PID_RE.fullmatch(str(pid)):
            continue
        items.append(_item("link", "link:" + pid, "Link report", str(p.get("title") or pid)[:80],
                           str(p.get("description") or "")[:300], p.get("submitted_at"), "/wrath/admin/catalog",
                           [("link.hide", pid, "Hide", {}, pid, True), ("link.dismiss", pid, "Dismiss reports", {}, None, False)],
                           sub=f"{n} report{'s' if n != 1 else ''} · added by {str(p.get('submitted_by') or '?')[:40]}", group=0))
    net = P("network")
    if net is not None:
        try:
            for x in net.reports("open")[:200]:
                rid = str(x.get("realm") or "")
                if not A.REALM_ID_RE.fullmatch(rid):
                    continue
                items.append(_item("realm", "realm:" + rid + ":" + str(x.get("at", "")), "Realm report",
                                   str(x.get("name") or rid)[:60], str(x.get("note") or "")[:300], x.get("at"), "/wrath/admin/realms",
                                   [("realm.reports", rid, "Resolve", {"how": "resolved"}, None, False),
                                    ("realm.reports", rid, "Dismiss", {"how": "dismissed"}, None, False),
                                    ("realm.hide", rid, "Hide the realm", {}, rid, True)],
                                   sub=str(net.REPORT_REASON.get(x.get("reason"), "?")), group=0))
        except Exception:   # noqa: BLE001
            problems.append("realm reports")
    ok, ws, err = A.ws_list("pending")
    if not ok:
        problems.append("the Workshop queue (" + err + ")")
    for r in ws:
        sid = str(r["id"])
        items.append(_item("ws", "ws:" + sid, "Workshop: waiting", f"#{sid} {r['title']}", r["descr"], 0, "/wrath/admin/workshop",
                           [("ws.approve", sid, "Approve", {}, None, False), ("ws.reject", sid, "Reject", {}, sid, True)],
                           sub=f"{r['kind']} by {r['author']}" + (" · filtered word" if r["flagged"] else "")))
    dec = A.hub_decisions()
    seen = set()
    for s in reversed(A.hub_submissions()):
        sid = s["id"]
        if sid in dec or sid in seen:
            continue
        seen.add(sid)
        items.append(_item("hub", "hub:" + sid, "Index: submitted", str(s.get("repo") or sid)[:120], str(s.get("note") or "")[:300],
                           s.get("at"), "/wrath/admin/hub",
                           [("hub.approve", sid, "Approve", {}, None, False),
                            ("hub.reject", sid, "Reject", {"reason": ("text", "why (required)")}, None, True)],
                           sub=f"{str(s.get('build') or '')} · {str(s.get('category') or '')}"))
    if A.themes_review():
        for t in A.theme_items():
            if t["state"] != "pending":
                continue
            items.append(_item("theme", f"theme:{t['kind']}:{t['id']}", "Theme pack: waiting", t["name"], "", 0, "/wrath/admin/themes",
                               [(f"{t['kind']}.approve", t["id"], "Approve", {}, None, False),
                                (f"{t['kind']}.reject", t["id"], "Reject", {}, t["id"], True)], sub="by " + t["by"]))
    items.sort(key=lambda x: (x["group"], -x["at"]))
    return items, problems


INBOX_WORDS = {"bug": ("bug report", "bug reports"), "msg": ("message report", "message reports"),
               "forum": ("forum report", "forum reports"), "link": ("link report", "link reports"),
               "realm": ("realm report", "realm reports"), "ws": ("Workshop item waiting", "Workshop items waiting"),
               "hub": ("index submission", "index submissions"), "theme": ("theme pack waiting", "theme packs waiting")}


def inbox_counts(items: list[dict]) -> str:
    c = {}
    for x in items:
        c[x["kind"]] = c.get(x["kind"], 0) + 1
    return " · ".join(f"{n} {INBOX_WORDS[k][n != 1]}" for k, n in c.items())


def _fields(fields: dict) -> str:
    out = []
    for k, v in fields.items():
        if isinstance(v, tuple):
            out.append(f'<input type="text" name="{e(k)}" maxlength="300" placeholder="{e(v[1])}" aria-label="{e(v[1])}"'
                       f'{" required" if "required" in v[1] else ""}>')
        else:
            out.append(f'<input type="hidden" name="{e(k)}" value="{e(str(v))}">')
    return "".join(out)


def item_html(user: dict, x: dict, back: str) -> str:
    plain, fold = [], []
    for (action, target, label, fields, confirm, danger) in x["acts"]:
        f = A.act(user, action, target, label, back, _fields(fields), confirm=confirm, danger=danger)
        (fold if confirm or danger else plain).append(f)
    acts = "".join(plain) + (f'<details><summary>More</summary>{"".join(fold)}</details>' if any(fold) else "")
    person = (f' · <a href="/wrath/admin/person?acct={e(urllib.parse.quote(x["person"]))}">their page</a>'
              if x.get("person") else "")
    when = ago(x["at"]) if x["at"] else ""
    return (f'<article class="hq-item"><p class="what">{e(x["label"])}{" · " + e(when) if when else ""}</p>'
            f'<p class="title"><b>{e(x["title"])}</b></p>'
            + (f'<p class="sub">{e(x["sub"])}{person}</p>' if x["sub"] or person else "")
            + (f'<div class="body">{e(x["text"])}</div>' if x["text"] else "")
            + (f'<div class="acts">{acts}</div>' if acts.strip() else
               f'<p class="fine">Ask an admin: your role can look but not act on this.</p>')
            + f'<p class="fine"><a href="{e(x["where"])}">Open it there</a></p></article>')


def inbox_page(user: dict) -> str:
    items, problems = inbox_items()
    back = "/wrath/admin/inbox"
    warn = (f'<p class="ad-msg err">Could not read: {e("; ".join(problems))}. The rest is below.</p>' if problems else "")
    if not items:
        return (f'<section class="ly-panel"><h2>Needs you</h2>{warn}<p class="hq-calm">Nothing is waiting. '
                f'Reports and queues show up here as they come in.</p></section>')
    return (f'<section class="ly-panel"><h2>Needs you</h2><p class="fine">{e(inbox_counts(items))}. Reports first, newest '
            f'first, then the queues.</p>{warn}' + "".join(item_html(user, x, back) for x in items[:200]) + '</section>')


# ----------------------------------------------------------------------------------------------
# Releases
# ----------------------------------------------------------------------------------------------

GH_REPO = "https://github.com/orionopenwow/Leyline/"


def gh_runs() -> tuple[bool, list[dict], str]:
    url = os.environ.get("WU_LEYLINE_RUNS_API", "https://api.github.com/repos/orionopenwow/Leyline/actions/runs?per_page=15")

    def get():
        try:
            doc = _fetch_json(url)
        except Exception as ex:   # noqa: BLE001
            return False, [], str(ex)[:120]
        out, seen = [], set()
        for r in (doc.get("workflow_runs") if isinstance(doc, dict) else None) or []:
            if not isinstance(r, dict):
                continue
            name = clean_text(r.get("name"), 60)
            if not name or name in seen:
                continue
            seen.add(name)
            page = r.get("html_url") if isinstance(r.get("html_url"), str) and r["html_url"].startswith(GH_REPO) else ""
            out.append({"name": name, "status": clean_text(r.get("status"), 20), "conclusion": clean_text(r.get("conclusion"), 20),
                        "branch": clean_text(r.get("head_branch"), 40), "at": clean_text(r.get("created_at"), 20), "url": page})
        return True, out[:5], ""
    return A.cached("gh-runs", A.RELEASES_TTL, get)


def addonpack() -> tuple[bool, dict, str]:
    url = os.environ.get("WU_ADDONPACK_URL", GH_REPO + "releases/download/leyline-addons/addonpack.json")

    def get():
        try:
            doc = _fetch_json(url, 400_000)
        except Exception as ex:   # noqa: BLE001
            return False, {}, str(ex)[:120]
        if not isinstance(doc, dict):
            return False, {}, "not a listing"
        return True, {"version": clean_text(doc.get("version"), 40), "build": clean_text(doc.get("build"), 20),
                      "addons": len(doc.get("addons")) if isinstance(doc.get("addons"), list) else None}, ""
    return A.cached("addonpack", A.RELEASES_TTL, get)


def hostpack() -> dict:
    ln = P("leyline_net")
    try:
        d = ln.hostpack() if ln is not None else None
    except Exception:   # noqa: BLE001
        d = None
    if not d:
        d = A._read_json(os.path.join(A.HERE, "hostpack.json"), {})
    return d if isinstance(d, dict) else {}


def release_rows() -> list[tuple[str, str, str]]:
    """(what, value, detail) for the Releases card."""
    rows = []
    ok, rels, err = A.releases()
    ch = A.channel_doc()
    live = [r for r in rels if not r["draft"] and r["version"]]
    if live:
        r = live[0]
        rows.append(("Launcher", r["version"] + (" (pre-release)" if r["prerelease"] else ""),
                     "published " + ago(r["published"]) if r["published"] else ""))
    else:
        rows.append(("Launcher", "unknown", "GitHub did not answer: " + err if not ok else "no releases yet"))
    chan = ("updates on hold" if ch["hold"] else
            f"stable {ch['stable']['version']}" if ch["stable"] else "stable: the newest release")
    if ch["beta"]:
        chan += f", beta {ch['beta']['version']}"
    rows.append(("Channel", chan, "set on Releases (owner)"))
    rok, runs, rerr = gh_runs()
    if runs:
        for x in runs[:3]:
            state = x["conclusion"] or x["status"]
            word = {"success": "passed", "failure": "failed", "cancelled": "cancelled", "in_progress": "running",
                    "queued": "waiting"}.get(state, state)
            rows.append(("Build: " + x["name"], word, ago(x["at"]) + (f" · {x['branch']}" if x["branch"] else "")))
    else:
        rows.append(("Builds", "unknown", "GitHub did not answer" if not rok else "no runs yet"))
    aok, ap, aerr = addonpack()
    rows.append(("Addon pack", ap.get("version") or "unknown", (f"{ap['addons']} addons" if ap.get("addons") else "")
                 if aok else "not reachable"))
    hp = hostpack()
    rows.append(("Host pack", str(hp.get("version") or "unknown")[:40], ""))
    rows.append(("Website", "files from " + (ago(site_version()) or "?"), "the signin step ships them"))
    return rows


# ----------------------------------------------------------------------------------------------
# What the PC sends: recent changes and Claude's notes
# ----------------------------------------------------------------------------------------------

STEP_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,48}$")


def changes() -> dict:
    """changes.json from the owner's PC, checked field by field."""
    doc = A._read_json(_hpath("changes.json"), {}, 400_000)
    steps = []
    for s in (doc.get("steps") if isinstance(doc.get("steps"), list) else [])[:40]:
        if not isinstance(s, dict) or not STEP_ID_RE.fullmatch(str(s.get("id", ""))):
            continue
        ok = s.get("ok")
        steps.append({"id": str(s["id"]), "step": clean_text(s.get("step"), 24), "title": clean_text(s.get("title"), 100),
                      "note": clean_text(s.get("note"), 200), "ok": ok if ok in (True, False) else None,
                      "at": clean_text(s.get("at"), 25)})
    chk = doc.get("last_check") if isinstance(doc.get("last_check"), dict) else {}
    chk = {"at": clean_text(chk.get("at"), 25), "ok": chk.get("ok") is True, "id": clean_text(chk.get("id"), 48)} if chk.get("at") else {}
    return {"made_at": clean_text(doc.get("made_at"), 25), "steps": steps, "last_check": chk}


def claude_notes() -> dict:
    doc = A._read_json(_hpath("claude-notes.json"), {}, 400_000)
    notes = []
    for n in (doc.get("notes") if isinstance(doc.get("notes"), list) else [])[:50]:
        if not isinstance(n, dict) or not STEP_ID_RE.fullmatch(str(n.get("id", ""))):
            continue
        items = [clean_text(x, 300) for x in (n.get("items") if isinstance(n.get("items"), list) else [])][:8]
        notes.append({"id": str(n["id"]), "date": clean_text(n.get("date"), 25), "title": clean_text(n.get("title"), 120),
                      "items": [x for x in items if x]})
    ack = {str(x) for x in (doc.get("ack") if isinstance(doc.get("ack"), list) else []) if isinstance(x, str)}
    return {"updated_at": clean_text(doc.get("updated_at"), 25), "notes": notes, "ack": ack}


NOTE_ID_RE = re.compile(r"^o\d{14}[0-9a-f]{4}$")


def owner_notes() -> list[dict]:
    """The owner's notes to Claude, newest first, each with its status: waiting, on Claude's PC, seen, closed."""
    notes, status = {}, {}
    for r in _jsonl_tail(_hpath("owner-notes.jsonl")):
        nid = str(r.get("id", ""))
        if not NOTE_ID_RE.fullmatch(nid):
            continue
        if "text" in r:
            notes[nid] = {"id": nid, "at": str(r.get("at", ""))[:25], "by": str(r.get("by", ""))[:64],
                          "text": clean_text(r.get("text"), 2000, lines=True)}
        elif r.get("status") in ("closed", "open"):
            status[nid] = r["status"]
    ack = claude_notes()["ack"]
    try:
        with open(_hpath("picked-up-at"), encoding="utf-8") as f:
            picked = epoch(f.read(40).strip())
    except OSError:
        picked = 0.0
    out = []
    for nid, n in notes.items():
        st = ("closed" if status.get(nid) == "closed" else "seen" if nid in ack
              else "on Claude's PC" if picked and picked >= epoch(n["at"]) else "waiting")
        out.append(dict(n, status=st))
    return sorted(out, key=lambda n: n["at"], reverse=True)


def a_note_add(user, target, form):
    text = clean_text(form.get("text"), 2000, lines=True)
    if len(text) < 2:
        raise A.Refused("Write the note first.")
    if sum(1 for n in owner_notes() if n["status"] != "closed") >= 100:
        raise A.Refused("100 notes are waiting already: close a few first.")
    nid = "o" + time.strftime("%Y%m%d%H%M%S", time.gmtime()) + secrets.token_hex(2)
    rec = {"id": nid, "at": A._iso(), "by": user["account"], "text": text}
    _append_jsonl(_hpath("owner-notes.jsonl"), rec)
    return {}, {"id": nid, "chars": len(text)}


def a_note_status(status):
    def fn(user, target, form):
        if not any(n["id"] == target for n in owner_notes()):
            raise A.Refused("No such note.")
        _append_jsonl(_hpath("owner-notes.jsonl"), {"id": target, "status": status, "at": A._iso(), "by": user["account"]})
        return {}, {"status": status}
    return fn


# ----------------------------------------------------------------------------------------------
# The game, over SOAP: every command built here from checked parts (the gmconsole.py rules), one line, from the
# allow-list below. Nothing a staff member types reaches the console unchecked.
# ----------------------------------------------------------------------------------------------

CHAR_RE = re.compile(r"^[^\W\d_]{2,12}$")          # gmconsole.py RE_CHAR: letters only, 2-12
ACCT_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,32}$")    # gmconsole.py RE_ACCT
BOT_PREFIX = os.environ.get("WU_BOT_PREFIX", "RNDBOT")
REASON_BAD = re.compile(r"[^\w .,!?'():/-]", re.UNICODE)
GAME_ALLOW = ("kick ", "mute ", "unmute ", "tele name ", "ban account ", "unban account ", "announce ", "notify ",
              "ticket list", "account onlinelist")


def char_name(v) -> str:
    v = str(v or "").strip()
    if not CHAR_RE.fullmatch(v):
        raise A.Refused("Not a character name (2-12 letters).")
    return v[0].upper() + v[1:].lower()


def acct_name(v) -> str:
    v = str(v or "").strip()
    if not ACCT_RE.fullmatch(v):
        raise A.Refused("Not a game account (letters, digits, _ . -).")
    if v.upper().startswith(BOT_PREFIX):
        raise A.Refused("That is a bot account.")
    return v.upper()


def game_reason(v, n: int = 160, need: bool = True) -> str:
    s = " ".join(REASON_BAD.sub("", clean_text(v, 400).replace("_", " ")).split())[:n]
    if need and len(s) < 3:
        raise A.Refused("Say why (3 letters or more).")
    return s


def say_text(v, n: int = 200) -> str:
    """An announcement: one line, no chat codes (|), no game-brand names."""
    s = clean_text(v, 400).replace("|", "/")
    s = " ".join(REASON_BAD.sub("", s.replace("_", " ")).split())[:n]
    if len(s) < 2:
        raise A.Refused("Write the message.")
    A._no_brand(s)
    return s


def build(kind: str, form: dict, target: str = "") -> str:
    """The console command for one game action. Raises Refused on anything that doesn't fit."""
    if kind == "kick":
        cmd = f"kick {char_name(target)}"
    elif kind == "mute":
        try:
            m = int(str(form.get("minutes") or "").strip())
        except ValueError:
            raise A.Refused("Minutes: a number from 1 to 10080 (a week).") from None
        if not 1 <= m <= 10080:
            raise A.Refused("Minutes: a number from 1 to 10080 (a week).")
        cmd = f"mute {char_name(target)} {m} {game_reason(form.get('reason'))}"
    elif kind == "unmute":
        cmd = f"unmute {char_name(target)}"
    elif kind == "rescue":
        cmd = f"tele name {char_name(target)} Dalaran"
    elif kind == "ban":
        try:
            hours = int(str(form.get("hours") or "").strip())
        except ValueError:
            raise A.Refused("Hours: 1 to 8760, or 0 for a permanent ban.") from None
        if not 0 <= hours <= 8760:
            raise A.Refused("Hours: 1 to 8760, or 0 for a permanent ban.")
        cmd = f"ban account {acct_name(target)} {str(hours) + 'h' if hours else '-1'} {game_reason(form.get('reason'))}"
    elif kind == "unban":
        cmd = f"unban account {acct_name(target)}"
    elif kind == "announce":
        cmd = f"announce {say_text(form.get('text'))}"
    elif kind == "notify":
        cmd = f"notify {say_text(form.get('text'))}"
    else:
        raise A.Refused("Unknown game action.")
    if "\n" in cmd or "\r" in cmd or not cmd.lower().startswith(GAME_ALLOW):
        raise A.Refused("That command is not allowed.")
    return cmd


def game_soap(cmd: str) -> tuple[bool, str]:
    """(ok, the console's answer, cleaned) for a command build() made (or a read-only one from GAME_ALLOW)."""
    if not cmd.lower().startswith(GAME_ALLOW) or "\n" in cmd:
        return False, "not allowed"
    fn, err_cls = P("ac_soap"), P("SoapError")
    if fn is None:
        return False, "no SOAP here"
    try:
        out = fn(cmd) or ""
    except Exception as ex:   # noqa: BLE001
        if err_cls is not None and isinstance(ex, err_cls):
            if ex.kind == "fault":
                return False, "the realm said: " + clean_text(ex.detail, 200)
            return False, f"the realm did not answer ({ex.kind})"
        return False, "the realm did not answer"
    return True, clean_text(out, 2000, lines=True)


FAIL_WORDS = re.compile(r"(?i)not found|no such|can't|cannot|unknown|incorrect|invalid|does not exist|not exist")


def a_game(kind):
    def fn(user, target, form):
        cmd = build(kind, form, target)
        ok, out = game_soap(cmd)
        if not ok:
            raise A.Refused(out)
        if FAIL_WORDS.search(out.split("\n")[0] if out else ""):
            raise A.Refused("The realm said: " + out[:200])
        after = {"command": cmd.split(" ", 2)[0] if kind != "rescue" else "tele name", "answer": out[:160]}
        if kind in ("mute", "ban"):
            after.update({k: form.get(k) for k in ("minutes", "hours") if form.get(k)})
        return {}, after
    return fn


def tickets() -> tuple[bool, list[str]]:
    def get():
        ok, out = game_soap("ticket list")
        return ok, [x for x in out.split("\n") if x.strip()][:80] if ok else [out]
    return A.cached("tickets", 30, get)


def online_list() -> tuple[bool, list[str]]:
    def get():
        ok, out = game_soap("account onlinelist")
        lines = [x for x in out.split("\n") if x.strip() and BOT_PREFIX not in x.upper()]
        return ok, lines[:120] if ok else [out]
    return A.cached("online", 30, get)


# ----------------------------------------------------------------------------------------------
# People: search, a person's page, sanctions, devices
# ----------------------------------------------------------------------------------------------

def _social():
    soc = P("social")
    return getattr(soc, "store", None) if soc is not None else None


def search(q: str) -> list[dict]:
    q = A._clean_line(q, 40)
    if not q:
        return []
    st = _social()
    accts: list[str] = []
    if st is not None:
        name, _, tag = q.partition("#")
        like = name.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        try:
            rows = st.q("SELECT acct FROM social_accounts WHERE acct = ? OR name_lc = ? OR name_lc LIKE ? ESCAPE '\\' "
                        "ORDER BY name_lc LIMIT 40", (q.upper(), name.lower(), like))
            accts = [r[0] for r in rows if not tag or (st.profile(r[0]) or {}).get("tag") == tag]
            for r in st.q("SELECT DISTINCT acct FROM social_chars WHERE name_lc = ? LIMIT 20", (q.lower(),)):
                if r[0] not in accts:
                    accts.append(r[0])
        except Exception:   # noqa: BLE001
            pass
    if A.GAME_ACCT_RE.fullmatch(q.upper()) and q.upper() not in accts and not q.upper().startswith(BOT_PREFIX):
        accts.append(q.upper())
    out = []
    for a in accts[:40]:
        p = (st.profile(a) if st is not None else None) or {}
        out.append({"acct": a, "name": p.get("name", ""), "tag": p.get("tag", ""), "main": p.get("main", ""),
                    "sanctions": [v["type"] for v in A.sanctions_for(a)]})
    return out


def person(acct: str, site: str = "") -> dict:
    """Everything HQ knows about one game account (and, when given, its website account id)."""
    acct = acct.upper()
    st = _social()
    doc = {"acct": acct, "site": site, "name": "", "tag": "", "main": "", "chars": [], "online": None, "bio": "",
           "sanctions": A.sanctions_for(acct, site, active=False), "message_reports": [], "forum_reports": [],
           "workshop": [], "links": [], "realms": [], "devices": [], "audit": []}
    if st is not None:
        try:
            p = st.profile(acct) or {}
            doc.update(name=p.get("name", ""), tag=p.get("tag", ""), main=p.get("main", ""))
            doc["chars"] = [r[0] for r in st.q("SELECT name FROM social_chars WHERE acct = ? ORDER BY name LIMIT 60", (acct,))]
            ing = getattr(st, "ingame", {}).get(acct)
            doc["online"] = {"char": ing.get("char", ""), "since": ing.get("since")} if isinstance(ing, dict) else None
            doc["devices"] = st.tokens(acct)
            doc["message_reports"] = [{"id": r.get("id"), "at": r.get("at"), "status": r.get("status"), "reason": r.get("reason"),
                                       "by": r.get("reporter_name")} for r in st.reports("", 1000) if r.get("target") == acct][:30]
        except Exception:   # noqa: BLE001
            pass
    prof = A._profiles_mod()
    if prof is not None:
        try:
            doc["bio"] = (prof.store.get(acct) or {}).get("bio", "")
        except Exception:   # noqa: BLE001
            pass
    fs = A.forum_store()
    if fs is not None:
        try:
            doc["forum_reports"] = [{"id": r["id"], "at": r["at"], "status": r["status"], "reason": r["reason"],
                                     "thread": r["thread_title"]} for r in fs.reports("", 1000) if r.get("author") == acct][:30]
        except Exception:   # noqa: BLE001
            pass
    chars = {c.lower() for c in doc["chars"]}
    if chars:
        ok, rows, _ = A.ws_list("all")
        doc["workshop"] = [{"id": r["id"], "title": r["title"], "state": r["state"]} for r in rows if r["author"].lower() in chars][:30]
    if site:
        doc["links"] = [{"id": p.get("id"), "title": p.get("title"), "hidden": bool(p.get("hidden"))}
                        for p in A.projects_all() if p.get("submitter") == site][:30]
    hf = P("hostflow")
    if hf is not None:
        try:
            doc["realms"] = [{"id": r.get("realm_id") or r.get("pending_id"), "name": r.get("name", ""), "claimed": bool(r.get("claimed"))}
                             for r in hf.realms_of(acct)][:20]
        except Exception:   # noqa: BLE001
            pass
    doc["audit"] = [r for r in A.audit_tail(400) if acct in str(r.get("target", "")) or (site and site in str(r.get("target", "")))][:20]
    return doc


def a_sanction_set(user, target, form):
    acct = form.get("acct") or (target if not target.startswith("site:") else "")
    site = form.get("site") or (target[5:] if target.startswith("site:") else "")
    try:
        hours = int(str(form.get("hours") or "0").strip() or 0)
    except ValueError:
        raise A.Refused("Hours: a number (0 = until it is lifted).") from None
    return A.set_sanction(user, form.get("type", ""), acct, site, hours, A._clean_line(form.get("reason"), 200))


def a_sanction_lift(user, target, form):
    if not re.fullmatch(r"s\d{14}[0-9a-f]{6}", target):
        raise A.Refused("Not a sanction id.")
    return A.lift_sanction(user, target)


def a_device_revoke(user, target, form):
    st = _social()
    if st is None:
        raise A.Refused("Launcher sign-ins (stream/social.py) are not on this portal.")
    acct = target.upper()
    if not A.GAME_ACCT_RE.fullmatch(acct):
        raise A.Refused("Not a game account.")
    tid = str(form.get("id") or "")
    if tid == "all":
        n = 0
        for t in st.tokens(acct):
            n += 1 if st.revoke(acct, short_id=t["id"]) else 0
        return {}, {"revoked": n}
    if not re.fullmatch(r"[0-9a-f]{12}", tid) or not st.revoke(acct, short_id=tid):
        raise A.Refused("No such sign-in.")
    return {}, {"revoked": tid}


def a_realm_block(on):
    def fn(user, target, form):
        A._realm_target(target)
        reason = A._clean_line(form.get("reason"), 200)
        if on and not reason:
            raise A.Refused("Say why (staff only; the feed carries no reasons).")
        return A.set_relay_block(user, target, on, reason)
    return fn


def register() -> None:
    A.ACTIONS.update({
        "game.kick": (a_game("kick"), "mod", None),
        "game.mute": (a_game("mute"), "mod", None),
        "game.unmute": (a_game("unmute"), "mod", None),
        "game.rescue": (a_game("rescue"), "mod", None),
        "game.ban": (a_game("ban"), "admin", True),
        "game.unban": (a_game("unban"), "admin", True),
        "game.announce": (a_game("announce"), "admin", None),
        "game.notify": (a_game("notify"), "admin", None),
        "sanction.set": (a_sanction_set, "admin", True),
        "sanction.lift": (a_sanction_lift, "admin", None),
        "device.revoke": (a_device_revoke, "admin", None),
        "realm.block": (a_realm_block(True), "admin", True),
        "realm.unblock": (a_realm_block(False), "admin", None),
        "hq.note.add": (a_note_add, "owner", None),
        "hq.note.close": (a_note_status("closed"), "owner", None),
        "hq.note.reopen": (a_note_status("open"), "owner", None),
    })


# ----------------------------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------------------------

CSS = """
.ad-head{margin-bottom:4px}.ad-sub{margin-top:-2px}.ad-sub a{font-size:13px;padding:4px 10px}
.hq-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:10px;margin:14px 0 6px}
.hq-chip{background:rgba(18,22,54,.72);border:1px solid var(--ly-line);border-radius:8px;padding:10px 12px;min-width:0}
.hq-chip .k{display:block;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--ly-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hq-chip .v{display:flex;align-items:center;gap:8px;font-size:18px;font-weight:600;margin:2px 0}
.hq-chip .d{display:block;font-size:12px;color:var(--ly-dim)}
.hq-dot{flex:none;width:10px;height:10px;border-radius:50%;background:#7c84ad}
.hq-dot.good{background:#5ef0a0;box-shadow:0 0 8px rgba(94,240,160,.6)}.hq-dot.bad{background:#ff7a90;box-shadow:0 0 8px rgba(255,122,144,.6)}
.hq-dot.warn{background:#ffd27a}
.hq-grid{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(0,1fr);gap:0 18px;align-items:start}
@media (max-width:900px){.hq-grid{grid-template-columns:minmax(0,1fr)}}
.hq-item{border-top:1px solid rgba(120,150,255,.16);padding:12px 0}.hq-item:first-of-type{border-top:0;padding-top:4px}
.hq-item p{margin:0}.hq-item .what{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--ly-cyan)}
.hq-item .title{margin:2px 0}.hq-item .sub{font-size:13px;color:var(--ly-dim)}.hq-item .acts{margin-top:6px}
.hq-item .body{max-height:7.5em;overflow:hidden}
.hq-calm{font-size:17px;color:var(--ly-ink);margin:6px 0}
.hq-big{font:600 15px/1.3 system-ui,sans-serif;color:var(--ly-dim);margin:-4px 0 10px}
.hq-rows{display:grid;grid-template-columns:auto minmax(0,1fr);gap:7px 14px;margin:0}
.hq-rows dt{color:var(--ly-dim);font-size:14px}.hq-rows dd{margin:0;font-size:15px}.hq-rows dd .fine{margin-left:6px}
.hq-list{list-style:none;padding:0;margin:0}.hq-list li{padding:8px 0;border-top:1px solid rgba(120,150,255,.12)}
.hq-list li:first-child{border-top:0}
.hq-note h3{margin:0 0 4px;font-size:16px}.hq-note ul{margin:4px 0 0 18px;padding:0}.hq-note li{margin:2px 0}
.hq-say textarea{width:100%;box-sizing:border-box;min-height:84px}
.hq-say form.blk{max-width:none}
.hq-people{list-style:none;padding:0;margin:8px 0}.hq-people li{padding:9px 0;border-top:1px solid rgba(120,150,255,.12)}
.hq-tools{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.hq-tools .tool{background:rgba(10,12,34,.55);border:1px solid var(--ly-line);border-radius:6px;padding:12px}
.hq-tools .tool h3{margin:0 0 6px;font-size:15px}
.hq-tools form{display:flex;flex-wrap:wrap}
.hq-mono{font:13px/1.45 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word;background:rgba(5,8,25,.6);padding:8px;border-radius:4px;max-height:360px;overflow:auto}
.ad .ad-top{row-gap:6px}
.ad .ly-panel>h2{font-size:clamp(18px,2.2vw,24px);margin-top:0}
.hq-more{display:inline-block;margin-top:10px;padding:7px 14px;border:1px solid var(--ly-line);border-radius:999px;text-decoration:none}
.hq-more:hover,.hq-more:focus-visible{border-color:var(--ly-cyan);box-shadow:var(--ly-glow)}
@media (max-width:640px){.ly-wrap.ad{padding-left:12px;padding-right:12px}.ly-panel{padding:16px 14px}
.hq-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.hq-chip .v{font-size:16px}
.ad-top a{padding:6px 10px;font-size:13px}.ly h1.ad{font-size:30px}.ad form{margin:3px 4px 3px 0}}
"""


def strip_html() -> str:
    return '<div class="hq-strip" role="list">' + "".join(
        f'<div class="hq-chip" role="listitem"><span class="k">{e(k)}</span><span class="v"><span class="hq-dot {e(s)}" '
        f'aria-hidden="true"></span>{e(v)}</span><span class="d">{e(d)}</span></div>' for k, s, v, d in status_items()) + '</div>'


def releases_html() -> str:
    rows = "".join(f'<dt>{e(k)}</dt><dd>{e(v)}{"<span class=fine>" + e(d) + "</span>" if d else ""}</dd>' for k, v, d in release_rows())
    return (f'<section class="ly-panel"><h2>Releases</h2><dl class="hq-rows">{rows}</dl>'
            f'<p class="fine"><a href="/wrath/admin/releases">Channel, hold and News</a></p></section>')


def changes_html(n: int = 8) -> str:
    ch = changes()
    if not ch["steps"]:
        return ('<section class="ly-panel"><h2>Recent changes</h2><p class="fine">Nothing sent yet. The owner\'s PC sends '
                'the last deploys after each Autopilot run (the step hq-sync).</p></section>')
    li = "".join(
        f'<li>{A._tags(("done", "good") if s["ok"] is True else ("failed", "bad") if s["ok"] is False else ("waiting", "hot"))}'
        f'<b>{e(s["title"] or s["step"])}</b>{" · " + e(s["note"]) if s["note"] else ""}'
        f'<span class="sub fine"> {e(ago(s["at"]) if s["at"] else "")} · {e(s["id"])}</span></li>' for s in ch["steps"][:n])
    return (f'<section class="ly-panel"><h2>Recent changes</h2><ul class="hq-list">{li}</ul>'
            f'<p class="fine">Sent by the owner\'s PC {e(ago(ch["made_at"]))}. Step names and outcomes only; the logs stay on the PC.</p></section>')


def note_html(n: dict) -> str:
    return (f'<article class="hq-note"><h3>{e(n["title"])}</h3><p class="fine">{e(n["date"])}</p>'
            + ("<ul>" + "".join(f"<li>{e(x)}</li>" for x in n["items"]) + "</ul>" if n["items"] else "") + '</article>')


def from_claude_html(n: int = 1) -> str:
    cn = claude_notes()
    if not cn["notes"]:
        body = '<p class="fine">No notes yet. Claude\'s updates show here after the PC\'s next hq-sync.</p>'
    else:
        body = "".join(note_html(x) for x in cn["notes"][:n])
        if len(cn["notes"]) > n:
            body += f'<p class="fine"><a href="/wrath/admin/notes">All {len(cn["notes"])} notes</a></p>'
    return f'<section class="ly-panel"><h2>From Claude</h2>{body}</section>'


def to_claude_html(user: dict, back: str, n: int = 3) -> str:
    if user["role"] != "owner":
        return ""
    form = A.act(user, "hq.note.add", "new", "Leave the note", back,
                 '<textarea name="text" maxlength="2000" placeholder="What should Claude know or do next?" '
                 'aria-label="Note to Claude" required></textarea>', block=True)
    notes = owner_notes()
    li = "".join(
        f'<li>{A._tags((x["status"], "good" if x["status"] in ("seen", "closed") else "hot"))}'
        f'<span class="fine">{e(ago(x["at"]))}</span><div class="body">{e(x["text"])}</div>'
        + (A.act(user, "hq.note.close", x["id"], "Close", back) if x["status"] != "closed" else "") + '</li>'
        for x in notes[:n])
    more = f'<p class="fine"><a href="/wrath/admin/notes">All {len(notes)} notes</a></p>' if len(notes) > n else ""
    return (f'<section class="ly-panel hq-say"><h2>Note to Claude</h2><p class="fine">Claude reads these next time it '
            f'checks in; for a live chat use the Claude app.</p>{form}'
            + (f'<ul class="hq-list">{li}</ul>{more}' if li else "") + '</section>')


def home(user: dict) -> str:
    items, problems = inbox_items()
    back = "/wrath/admin"
    if items:
        need = (f'<p class="hq-big">{e(inbox_counts(items))}</p>' + "".join(item_html(user, x, back) for x in items[:5])
                + (f'<p><a class="hq-more" href="/wrath/admin/inbox">See all {len(items)} &rarr;</a></p>' if len(items) > 5 else ""))
    else:
        need = '<p class="hq-calm">Nothing is waiting for you.</p>'
    if problems:
        need += f'<p class="fine">Could not read: {e("; ".join(problems))}.</p>'
    return (strip_html()
            + '<div class="hq-grid"><div>'
            + f'<section class="ly-panel"><h2>Needs you</h2>{need}</section>'
            + '</div><div>' + from_claude_html() + to_claude_html(user, back) + releases_html() + changes_html(6) + '</div></div>')


def notes_page(user: dict) -> str:
    cn = claude_notes()
    body = "".join(note_html(x) for x in cn["notes"]) or '<p class="fine">No notes from Claude yet.</p>'
    out = f'<section class="ly-panel"><h2>From Claude</h2>{body}</section>'
    if user["role"] == "owner":
        back = "/wrath/admin/notes"
        li = "".join(
            f'<li>{A._tags((x["status"], "good" if x["status"] in ("seen", "closed") else "hot"))}<span class="fine">'
            f'{e(x["at"])}</span><div class="body">{e(x["text"])}</div>'
            + (A.act(user, "hq.note.close", x["id"], "Close", back) if x["status"] != "closed" else
               A.act(user, "hq.note.reopen", x["id"], "Reopen", back)) + '</li>' for x in owner_notes()[:200])
        out += to_claude_html(user, back, 0).replace('</section>', (f'<ul class="hq-list">{li}</ul>' if li else "") + '</section>')
        out += ('<section class="ly-panel"><h2>How notes travel</h2><p class="fine">Waiting: saved here. On Claude\'s PC: the '
                'owner\'s PC picked it up (the Autopilot step hq-sync writes control/notes-from-owner.json). Seen: Claude '
                'read it and said so. Closed: you closed it.</p></section>')
    return out


def players_page(user: dict, query: dict) -> str:
    q = A._clean_line((query.get("q") or [""])[0], 40)
    form = (f'<form method="get" action="/wrath/admin/players"><input type="search" name="q" value="{e(q)}" maxlength="40" '
            'placeholder="Name, Name#1234, game account or character" aria-label="Find a person" size="34"> '
            '<button type="submit">Find</button></form>')
    if not q:
        san = [dict(v, id=k) for k, v in A.sanctions().items() if A.sanction_active(v)]
        rows = "".join(
            f'<li>{A._tags((v["type"], "bad"))}<a href="/wrath/admin/person?acct={e(v.get("acct") or "")}">'
            f'{e(v.get("acct") or v.get("site") or "?")}</a> <span class="fine">{e(v.get("reason", ""))} · '
            f'{"until " + e(A._iso(v["until"])) if v.get("until") else "until lifted"}</span></li>'
            for v in sorted(san, key=lambda v: v.get("at", ""), reverse=True)[:50] if v.get("acct"))
        return (f'<section class="ly-panel"><h2>Players</h2>{form}<p class="fine">Find someone, then open their page: '
                f'reports, what they made, kick, mute, ban and site-wide sanctions.</p></section>'
                f'<section class="ly-panel"><h2>Sanctions in force</h2>'
                + (f'<ul class="hq-people">{rows}</ul>' if rows else '<p class="fine">None.</p>') + '</section>')
    people = search(q)
    li = "".join(
        f'<li><a href="/wrath/admin/person?acct={e(p["acct"])}"><b>{e(p["name"] or p["acct"])}</b>'
        f'{"#" + e(p["tag"]) if p["tag"] else ""}</a> <span class="fine">{e(p["acct"])}'
        f'{" · main " + e(p["main"]) if p["main"] else ""}</span>'
        f'{A._tags(*[(s, "bad") for s in p["sanctions"]])}</li>' for p in people)
    return (f'<section class="ly-panel"><h2>Players</h2>{form}'
            + (f'<ul class="hq-people">{li}</ul>' if li else '<p class="fine">Nobody by that name.</p>') + '</section>')


def multi_act(user: dict, back: str, fields: str, buttons: list[tuple[str, str]]) -> str:
    """One form, several actions (the pressed button names it): e.g. one character box with Kick, Mute, Unmute.
    Only the buttons this role may use; nothing when none."""
    btns = "".join(f'<button type="submit" name="action" value="{e(a)}">{e(lab)}</button>' for a, lab in buttons
                   if A.can(user, A.ACTIONS.get(a, (None, "owner"))[1]))
    if not btns:
        return ""
    return (f'<form method="post" action="/wrath/admin/act"><input type="hidden" name="csrf" '
            f'value="{A.csrf_token(user["session"], user["account"])}"><input type="hidden" name="back" value="{e(back)}">'
            f'{fields}{btns}</form>')


CHAR_FIELDS = ('<input type="text" name="target" value="{v}" maxlength="12" placeholder="character" aria-label="Character" size="12" required>'
               '<input type="text" name="minutes" value="60" size="4" inputmode="numeric" aria-label="Mute minutes" title="Mute: minutes">'
               '<input type="text" name="reason" maxlength="160" placeholder="reason (for a mute)" aria-label="Reason">')
CHAR_BUTTONS = [("game.kick", "Kick"), ("game.rescue", "Send to Dalaran"), ("game.mute", "Mute"), ("game.unmute", "Unmute")]


def _tool(title: str, body: str) -> str:
    return f'<div class="tool"><h3>{e(title)}</h3>{body}</div>' if body else ""


def person_page(user: dict, query: dict) -> tuple[int, str]:
    acct = str((query.get("acct") or [""])[0]).strip().upper()
    site = str((query.get("site") or [""])[0]).strip()
    if not A.GAME_ACCT_RE.fullmatch(acct) or (site and not A.ACCOUNT_ID_RE.fullmatch(site)):
        return 404, '<section class="ly-panel"><h2>Not found</h2><p>That is not a game account.</p></section>'
    d = person(acct, site)
    back = "/wrath/admin/person?acct=" + acct
    title = (d["name"] or acct) + (("#" + d["tag"]) if d["tag"] else "")
    online = (f'In the game now as {e(d["online"]["char"])}' if d["online"] else "Not in the game")
    chars = ", ".join(d["chars"]) or "none known"
    first = d["chars"][0] if d["chars"] else ""
    game = multi_act(user, back, CHAR_FIELDS.format(v=e(first)), CHAR_BUTTONS)
    ban = (A.act(user, "game.ban", acct, "Ban the game account", back,
                 '<input type="text" name="hours" value="24" size="5" inputmode="numeric" aria-label="Hours (0 = permanent)">'
                 '<input type="text" name="reason" maxlength="160" placeholder="reason" aria-label="Reason" required>',
                 confirm=acct, danger=True)
           + A.act(user, "game.unban", acct, "Unban", back, confirm=acct))
    san_form = A.act(user, "sanction.set", acct, "Apply", back,
                     '<select name="type" aria-label="Sanction"><option value="mute">Mute (no posts or messages)</option>'
                     '<option value="nosubmit">No new submissions</option><option value="suspend">Suspend (everything)</option></select>'
                     '<input type="text" name="hours" value="72" size="5" inputmode="numeric" aria-label="Hours (0 = until lifted)">'
                     f'<input type="text" name="site" value="{e(site)}" maxlength="64" placeholder="website id (optional)" aria-label="Website account id">'
                     '<input type="text" name="reason" maxlength="200" placeholder="reason (the player reads it)" aria-label="Reason" required>',
                     confirm=acct, danger=True)
    san_rows = "".join(
        f'<li>{A._tags((v["type"], "bad" if A.sanction_active(v) else ""), ("lifted", "") if v.get("lifted") else ("", ""))}'
        f'<span class="fine">{e(v.get("reason", ""))} · by {e(v.get("by", ""))} {e(ago(v.get("at")))} · '
        f'{"until " + e(A._iso(v["until"])) if v.get("until") else "until lifted"}</span>'
        + (A.act(user, "sanction.lift", v["id"], "Lift", back) if A.sanction_active(v) else "") + '</li>'
        for v in d["sanctions"])
    dev = "".join(
        f'<li>{e(t.get("label", ""))} <span class="fine">used {e(ago(t.get("used")))}</span>'
        + A.act(user, "device.revoke", acct, "Sign it out", back, f'<input type="hidden" name="id" value="{e(t["id"])}">') + '</li>'
        for t in d["devices"])
    if len(d["devices"]) > 1:
        dev += '<li>' + A.act(user, "device.revoke", acct, "Sign out every launcher", back, '<input type="hidden" name="id" value="all">') + '</li>'

    def lst(rows):
        return f'<ul class="hq-list">{"".join(rows)}</ul>' if rows else '<p class="fine">None.</p>'
    reports = lst([f'<li>Message report: {e(str(r["reason"]))} by {e(str(r["by"] or "?"))} {A._tags((str(r["status"]), ""))}'
                   f'<span class="fine">{e(ago(r["at"]))}</span></li>' for r in d["message_reports"]]
                  + [f'<li>Forum report: {e(str(r["reason"]))} in {e(str(r["thread"] or "?"))} {A._tags((str(r["status"]), ""))}'
                     f'<span class="fine">{e(ago(r["at"]))}</span></li>' for r in d["forum_reports"]])
    made = lst([f'<li>Workshop #{r["id"]} {e(r["title"])} {A._tags((r["state"], ""))}</li>' for r in d["workshop"]]
               + [f'<li>Link {e(str(r["title"]))} {A._tags(("hidden", "bad") if r["hidden"] else ("listed", "good"))}</li>' for r in d["links"]])
    realms = lst([f'<li>{e(r["name"])} <code>{e(str(r["id"]))}</code> {A._tags(("claimed", "good") if r["claimed"] else ("not set up yet", ""))}</li>'
                  for r in d["realms"]])
    hist = lst([f'<li><code>{e(str(r.get("action")))}</code> by {e(str(r.get("name")))} <span class="fine">{e(str(r.get("at")))}'
                f'{" · refused" if not r.get("ok") else ""}</span></li>' for r in d["audit"]])
    return 200, (
        f'<section class="ly-panel"><h2>{e(title)}</h2><p class="hq-big">{online}</p>'
        f'<dl class="hq-rows"><dt>Game account</dt><dd><code>{e(acct)}</code></dd>'
        f'<dt>Characters</dt><dd>{e(chars)}</dd>'
        + (f'<dt>Website id</dt><dd><code>{e(site)}</code></dd>' if site else "")
        + (f'<dt>Bio</dt><dd>{e(d["bio"])}</dd>' if d["bio"] else "")
        + f'</dl><p class="fine"><a href="/wrath/admin/profiles?q={e(acct)}">Profile resets</a> · '
          f'<a href="/wrath/admin/players">Find someone else</a></p></section>'
        + f'<section class="ly-panel"><h2>Act</h2><div class="hq-tools">'
        + _tool("In the game (a character)", game) + _tool("The game account", ban)
        + _tool("On Leyline (site-wide)", san_form)
        + '</div><p class="fine">A site-wide sanction stops posts, messages, submissions or everything on the website and '
          'the launcher, with the reason shown to the player. A game ban stops logins to ' + e(realm_name()) + '.</p></section>'
        + f'<section class="ly-panel"><h2>Sanctions</h2>{lst([san_rows]) if san_rows else "<p class=fine>None.</p>"}</section>'
        + f'<section class="ly-panel"><h2>Reports about them</h2>{reports}</section>'
        + f'<section class="ly-panel"><h2>What they made</h2>{made}<h3>Realms they host</h3>{realms}</section>'
        + f'<section class="ly-panel"><h2>Launcher sign-ins</h2>{lst([dev]) if dev else "<p class=fine>None.</p>"}</section>'
        + f'<section class="ly-panel"><h2>Staff history</h2>{hist}</section>')


def game_page(user: dict) -> str:
    back = "/wrath/admin/game"
    acct_box = '<input type="text" name="target" maxlength="32" placeholder="game account" aria-label="Game account" size="14" required>'

    def aact(action, label, extra="", danger=False):
        # typed confirm: the account again (the server checks it)
        return A.act(user, action, "", label, back, acct_box + extra
                     + '<input type="text" name="confirm" maxlength="32" placeholder="type it again" aria-label="Type the account again" size="12" required>',
                     danger=danger).replace('<input type="hidden" name="target" value="">', "")
    tools = (_tool("Say to everyone", A.act(user, "game.announce", "all", "Announce", back,
                                               '<input type="text" name="text" maxlength="200" placeholder="message (one line)" '
                                               'aria-label="Announcement" size="30" required>')
                   + A.act(user, "game.notify", "all", "On-screen notice", back,
                           '<input type="text" name="text" maxlength="200" placeholder="message (one line)" aria-label="Notice" size="30" required>'))
             + _tool("A character", multi_act(user, back, CHAR_FIELDS.format(v=""), CHAR_BUTTONS))
             + _tool("A game account", aact("game.ban", "Ban", '<input type="text" name="hours" value="24" size="5" inputmode="numeric" '
                                            'aria-label="Hours (0 = permanent)"><input type="text" name="reason" maxlength="160" '
                                            'placeholder="reason" aria-label="Reason" required>', danger=True)
                     + aact("game.unban", "Unban")))
    tok, tlines = tickets()
    onl_ok, olines = online_list()
    return (f'<section class="ly-panel"><h2>In the game</h2><p class="fine">{e(realm_name())}, through the realm\'s console. '
            f'Send to Dalaran rescues a stuck character. Bans need the account typed twice. Everything is in the audit log.</p>'
            f'<div class="hq-tools">{tools}</div></section>'
            f'<section class="ly-panel"><h2>GM tickets</h2><p class="fine">Read-only (answer them in the game).</p>'
            f'<div class="hq-mono">{e(chr(10).join(tlines)) or "No open tickets."}</div></section>'
            f'<section class="ly-panel"><h2>Online now</h2><p class="fine">Accounts signed in (bots left out).</p>'
            f'<div class="hq-mono">{e(chr(10).join(olines)) or "Nobody."}</div></section>'
            f'<section class="ly-panel"><h2>Bug reports</h2><p><a href="/wrath/admin/reports">The .bug reports</a> are in Needs you '
            f'and under Content, All reports. The old GM console (127.0.0.1:8099 over the SSH tunnel) still works for '
            f'restarts and logs; HQ is the main place now.</p></section>')


def realms_wrap(user: dict) -> str:
    st = realm_status()
    on = st.get("online")
    off = (f'<section class="ly-panel"><h2>Official realm</h2><dl class="hq-rows"><dt>{e(realm_name())}</dt><dd>'
           f'{A._tags(("online", "good") if on else ("down", "bad"))}'
           + (f'{st.get("players")} playing, {st.get("bots")} bots' if on and st.get("players") is not None else "")
           + '</dd></dl><p class="fine"><a href="/wrath/admin/game">Game tools</a></p></section>')
    back = "/wrath/admin/realms"
    blocks = A.relay_blocks()
    li = "".join(f'<li><code>{e(k)}</code> <span class="fine">{e(v.get("reason", ""))} · {e(ago(v.get("at")))}</span>'
                 + A.act(user, "realm.unblock", k, "Unblock", back) + '</li>' for k, v in sorted(blocks.items()))
    signed = "signed" if os.environ.get("WU_RELAY_FEED_KEY") else "not signed (set WU_RELAY_FEED_KEY)"
    rb = (f'<section class="ly-panel"><h2>Blocked at the relay</h2><p class="fine">A blocked realm is cut off, its logins '
          f'refused and it leaves the relay\'s own list, within a few minutes (the relay polls '
          f'/wrath/leyline/relay-block.json, {signed}). The relay adds at most a few new blocks per update, and its own '
          f'block file still wins.</p>' + (f'<ul class="hq-list">{li}</ul>' if li else '<p class="fine">None.</p>') + '</section>')
    return off + A.realms_page(user) + rb


def page(user: dict, tab: str, query: dict):
    """(status, title, body) for the HQ pages, or None for the classic ones (stream/admin.py)."""
    if tab == "":
        return 200, "Home", home(user)
    if tab == "inbox":
        return 200, "Needs you", inbox_page(user)
    if tab == "players":
        return 200, "Players", players_page(user, query)
    if tab == "person":
        st, body = person_page(user, query)
        return st, "Person", body
    if tab == "game":
        return 200, "Game", game_page(user)
    if tab == "notes":
        return 200, "Notes", notes_page(user)
    if tab == "realms":
        return 200, "Realms", realms_wrap(user)
    if tab == "content":
        return 200, "Catalog", A.catalog_page(user)
    if tab == "system":
        return 200, "Health", A.health_page(user)
    return None


# ----------------------------------------------------------------------------------------------
# The JSON API (cookie + CSRF; the same actions as the pages)
# ----------------------------------------------------------------------------------------------

def _json(h, status: int, doc) -> None:
    h.send(status, (json.dumps(doc, ensure_ascii=False, default=str) + "\n").encode("utf-8"), "application/json; charset=utf-8",
           headers=A.NOINDEX)


def api_get(h, user: dict, what: str, query: dict) -> None:
    q1 = lambda k: str((query.get(k) or [""])[0])[:80]   # noqa: E731
    if what == "me":
        return _json(h, 200, {"ok": True, "account": user["account"], "name": user["name"], "role": user["role"],
                              "csrf": A.csrf_token(user["session"], user["account"]),
                              "can": sorted(k for k, v in A.ACTIONS.items() if A.can(user, v[1]))})
    if what == "inbox":
        items, problems = inbox_items()
        return _json(h, 200, {"ok": True, "problems": problems, "items": [
            {k: x[k] for k in ("kind", "id", "label", "title", "text", "sub", "at", "where")}
            | {"person": x.get("person", ""), "actions": [
                {"action": a, "target": t, "label": lab, "fields": {k: (None if isinstance(v, tuple) else v) for k, v in f.items()},
                 "confirm": c} for (a, t, lab, f, c, _d) in x["acts"] if A.can(user, A.ACTIONS.get(a, (None, "owner"))[1])]}
            for x in items[:200]]})
    if what == "search":
        return _json(h, 200, {"ok": True, "people": search(q1("q"))})
    if what == "person":
        acct = q1("acct").upper()
        if not A.GAME_ACCT_RE.fullmatch(acct):
            return _json(h, 400, {"ok": False, "error": "That is not a game account."})
        site = q1("site")
        return _json(h, 200, {"ok": True, "person": person(acct, site if A.ACCOUNT_ID_RE.fullmatch(site) else "")})
    if what == "realm":
        rid = q1("id")
        if not A.REALM_ID_RE.fullmatch(rid):
            return _json(h, 400, {"ok": False, "error": "That is not a realm id."})
        ok, recs, _ = A.raw_listing()
        net = P("network")
        return _json(h, 200, {"ok": True, "realm": next((r for r in recs if r["id"] == rid), None),
                              "overrides": A.realm_overrides().get(rid) or {}, "relay_blocked": rid in A.relay_blocks(),
                              "reports": net.reports("", rid)[:50] if net is not None else []})
    if what == "audit":
        try:
            n = max(1, min(int(q1("n") or 100), 500))
        except ValueError:
            n = 100
        return _json(h, 200, {"ok": True, "audit": A.audit_tail(n, q1("action"))})
    if what == "stats":
        items, problems = inbox_items()
        return _json(h, 200, {"ok": True, "status": [{"label": k, "state": s, "value": v, "detail": d} for k, s, v, d in status_items()],
                              "needs_you": len(items), "needs_you_by_kind": {k: sum(1 for x in items if x["kind"] == k) for k in INBOX_WORDS},
                              "releases": [{"what": k, "value": v, "detail": d} for k, v, d in release_rows()],
                              "changes": changes()})
    if what == "notes":
        cn = claude_notes()
        doc = {"ok": True, "from_claude": cn["notes"]}
        if user["role"] == "owner":
            doc["to_claude"] = owner_notes()
        return _json(h, 200, doc)
    return _json(h, 404, {"ok": False, "error": "Unknown API call."})
