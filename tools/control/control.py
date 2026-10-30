#!/usr/bin/env python3
"""Leyline Control: the owner's one window for launching what Claude has ready.

    py -3 tools\\control\\control.py          (or double-click "Leyline Control.bat")

Serves a page on http://127.0.0.1:8097 (this PC only) and opens it. The page shows:
  * Live: the realm, Play page and game files answering (checked from this PC every 30 s).
  * Claude: what Claude is working on, what is waiting for you, what finished (control/claude-status.json,
    which Claude keeps up to date in this folder).
  * Ready to launch: the steps in UPDATES-PENDING.txt not yet in UPDATES-DONE.txt; "Launch all" runs them in
    order (the same steps UPDATE.bat runs) and streams each step's output live; it stops at a failure.
  * History: finished steps with their logs (logs/<id>-<step>.log).
  * Autopilot (switch in the header, remembered in control/autopilot.json): while this window is open, new
    steps Claude adds to UPDATES-PENDING.txt run on their own within a minute, and a read-only server check
    runs every 3 hours (logs/check-auto-*.log), so Claude can read the results without asking you. A failed
    step is not retried until Claude changes UPDATES-PENDING.txt. The owner's standing rules still apply.
Only this PC can open it: it listens on 127.0.0.1, and every action needs the session token in the page.
Standard library only.
"""
import hashlib
import html
import http.server
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # the workspace folder (Desktop\\Leyline)
PEND = ROOT / "UPDATES-PENDING.txt"
DONE = ROOT / "UPDATES-DONE.txt"
LOGS = ROOT / "logs"
STATUS = ROOT / "control" / "claude-status.json"
PORT = int(os.environ.get("WU_CONTROL_PORT", "8097"))
AUTO = ROOT / "control" / "autopilot.json"
LAST = ROOT / "control" / "last-run.json"
QUIET = "--quiet" in sys.argv                         # started at Windows sign-in: no browser tab
TOKEN_FILE = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WrathUnleashed" / "control-token"
# The shared look (stream/www-files/art: wu-theme.css, the starfield, corners, dragons, divider, Cinzel), the same
# files the play pages and the GM console use. Served at /art/<name>, from this list only.
ART_DIR = Path(os.environ.get("WU_ART_DIR") or ROOT / "stream" / "www-files" / "art")
ART_TYPES = {
    "wu-theme.css": "text/css; charset=utf-8",
    "wu-load-orion.webp": "image/webp", "wu-load-bg.webp": "image/webp", "wu-card.webp": "image/webp",
    "wu-corner-tl.webp": "image/webp", "wu-corner-tr.webp": "image/webp",
    "wu-corner-bl.webp": "image/webp", "wu-corner-br.webp": "image/webp",
    "wu-divider.webp": "image/webp", "wu-dragon-l.webp": "image/webp", "wu-dragon-r.webp": "image/webp",
    "Cinzel-SemiBold.woff2": "font/woff2", "Cinzel-OFL.txt": "text/plain; charset=utf-8",
}


def art_bytes(name: str):
    """One file from the allow-list, or None. The name is only ever a key of ART_TYPES, never a path."""
    if name not in ART_TYPES:
        return None
    try:
        return (ART_DIR / name).read_bytes()
    except OSError:
        return None


def theme_version() -> str:
    b = art_bytes("wu-theme.css")
    return hashlib.sha256(b).hexdigest()[:10] if b else "none"


def _token() -> str:
    """One key per PC, kept outside the repo, so a reload, a bookmark or a second start keeps working."""
    try:
        t = TOKEN_FILE.read_text().strip()
        if len(t) >= 20:
            return t
    except OSError:
        pass
    t = secrets.token_urlsafe(18)
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(t)
    except OSError:
        pass
    return t


TOKEN = _token()

STEPS = {
    "client":  ("stream/Update browser client.bat", "New browser game build", False),
    "signin":  ("stream/Update sign-in and warm-up.bat", "Play page and sign-in", False),
    "page":    ("stream/Update game page.bat", "Game page only (keeps the live game build)", False),
    "ghclean-check": ("tools/github-cleanup/GitHub cleanup - dry run.bat", "What the GitHub cleanup would delete (read-only)", False),
    "ghclean": ("tools/github-cleanup/GitHub cleanup - do it.bat", "GitHub cleanup: old releases and packages (owner's choices, 2026-10-30)", False),
    "scripts": ("realm/Server pass - finder 10 and bug reports.bat", "Realm scripts (live reload)", False),
    "realm":   ("realm/Server pass - finder 10 and bug reports.bat", "Realm settings (5-min restart)", False),
    "foreverui": ("stream/Add Forever UI to the stream.bat", "Forever UI look (menus and character select)", False),
    "slice":   ("stream/Make mini slice.bat", "Streamed game files (30-60 min)", False),
    "ship":    ("Ship to GitHub.bat", "Save everything to GitHub", True),
    "check":   ("realm/Server check.bat", "Server check (read-only)", False),
    "gm":      ("gmconsole/Install GM Console.bat", "GM console update (game keeps running)", False),
    "lean":    ("realm/Lean server.bat", "Lean server: fewer bots, idle areas unload (5-min restart)", False),
    "relay": ("hosting/relay/Deploy relay.bat", "Beacons relay (relay.openvanilla.app)", False),
    "hangout": ("hosting/hangout/Deploy Dalaran hangout.bat", "Dalaran Hangout on Leyline (the realm as a Beacon)", False),
    "hangout-off": ("hosting/hangout/Take Dalaran hangout off Leyline.bat", "Take the Dalaran Hangout off Leyline", False),
    "leyline": ("tools/leyline-repo/Update Leyline repo.bat", "Leyline repo: copy and push (github.com/orionopenwow/Leyline)", False),
    "mods":  ("mods/Put mods on Wrath.bat", "Mods catalog: realm (live reload), streamed addons and /wrath/mods", False),
    "hostkit": ("hosting/kit/Publish host kit.bat", "Host kit download (checked zip on the public Leyline release)", False),
    "sampler-check": ("realm/Sample hangout - check.bat", "Leyline Sample Hangout: what would change (read-only)", False),
    "sampler": ("realm/Sample hangout - on.bat", "Leyline Sample Hangout on: lighter realm, browser fence (5-min restart)", False),
    "sampler-off": ("realm/Sample hangout - off.bat", "Leyline Sample Hangout off: back to the full realm (5-min restart)", False),
    "slice-sampler": ("stream/Make sampler slice.bat", "Sample Hangout streamed game files (30-60 min)", False),
    # The Leyline brand switch (realm/brand.sh; owner 2026-10-30: "wait for the site to change on my command"). Only
    # when the owner says so. No restart, nobody kicked; brand-off is the rollback.
    "brand-check": ("realm/Leyline brand - check.bat", "Leyline brand: what would change (read-only)", False),
    "brand-leyline": ("realm/Leyline brand - on.bat", "Leyline brand ON: site, game and realm list say Leyline / Dalaran Hangout", False),
    "brand-off": ("realm/Leyline brand - off.bat", "Leyline brand off: every name back as it was", False),
    # The hub's preview thumbnails (tools/hub-index, docs/HUB-INDEX.md): top 30 and new entries, then ship + signin.
    "thumbs": ("tools/hub-index/Refresh hub thumbnails.bat", "Hub thumbnails: preview images for the top 30 and new catalog entries (then ship)", False),
    "builds-why": ("tools/github-builds/Why did the build fail.bat", "Why the last GitHub build failed (read-only)", False),
    "remove-files": ("tools/cleanup/Remove listed files.bat", "Remove the files a change took out (tools/cleanup/REMOVE.txt)", False),
    "fresh-check": ("tools/fresh-history/Fresh history - dry run.bat", "Fresh Leyline history: what it would do (read-only)", False),
    "fresh-history": ("tools/fresh-history/Fresh history - do it.bat", "Fresh Leyline history: one commit, old history to a Desktop backup", False),
    # ovrename / ovland (the OpenVanilla repo's rename to Leyline-Launcher, 2026-10-29) are done for good: the tool is in
    # labs/done/ov-rename/ (labs/README.md says how to run it again).
    # The game data killswitch (docs/GAME-DATA-ON-OUR-SERVER.md): only when the owner asks for it.
    "gamedata-off": ("stream/Game data killswitch ON.bat", "Game data OFF: our server serves no game data (players use their own game folder)", False),
    "gamedata-on": ("stream/Game data killswitch OFF.bat", "Game data back ON: stream the slim sampler again", False),
}
CHECKS = [
    ("Play page", "https://play.openvanilla.app/wrath"),
    ("Game files", "https://wrath.openvanilla.app/data/__tier/index.json"),
    ("Client", "https://wrath.openvanilla.app/boot-manifest.json"),
]

state = {"running": None, "lines": [], "health": {}, "health_at": 0, "auto_failed": None}
lock = threading.Lock()
listeners: list[queue.Queue] = []


def read_lines(p: Path) -> list[str]:
    try:
        return [l.strip() for l in p.read_text(encoding="utf-8-sig", errors="replace").splitlines()]
    except FileNotFoundError:
        return []


def pending() -> list[dict]:
    done = set(read_lines(DONE))
    out = []
    for line in read_lines(PEND):
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 2)
        if len(parts) < 2 or parts[0] in done:
            continue
        sid, step = parts[0], parts[1].lower()
        note = parts[2] if len(parts) > 2 else ""
        title = STEPS.get(step, (None, "Unknown step", False))[1]
        out.append({"id": sid, "step": step, "title": title, "note": note, "known": step in STEPS})
    return out


def history() -> list[dict]:
    done = read_lines(DONE)
    notes = {}
    for line in read_lines(PEND):
        parts = line.split(None, 2)
        if len(parts) >= 2:
            notes[parts[0]] = (parts[1], parts[2] if len(parts) > 2 else "")
    out = []
    for sid in reversed([d for d in done if d]):
        step, note = notes.get(sid, ("?", ""))
        log = LOGS / f"{sid}-{step}.log"
        out.append({"id": sid, "step": step, "note": note, "log": log.name if log.exists() else ""})
    return out[:30]


def claude_status() -> dict:
    try:
        return json.loads(STATUS.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"updated": "", "now": [], "waiting_on_you": [], "done": [], "note": "No status from Claude yet."}


def autopilot_on() -> bool:
    try:
        return bool(json.loads(AUTO.read_text(encoding="utf-8-sig")).get("on"))
    except Exception:
        return False


def set_autopilot(on: bool) -> None:
    AUTO.parent.mkdir(exist_ok=True)
    AUTO.write_text(json.dumps({"on": bool(on), "changed": time.strftime("%Y-%m-%d %H:%M:%S")}), encoding="utf-8")


def pending_stamp() -> float:
    try:
        return PEND.stat().st_mtime
    except OSError:
        return 0.0


def write_last(ids, ok, step=None) -> None:
    try:
        LAST.parent.mkdir(exist_ok=True)
        LAST.write_text(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "ids": ids, "ok": ok,
                                    "failed_step": step, "autopilot": autopilot_on()}, indent=1), encoding="utf-8")
    except OSError:
        pass


def start_run(msg: str, items=None, record=True, title="Starting") -> bool:
    with lock:
        if state["running"]:
            return False
        state["running"] = {"id": "", "step": "starting", "title": title}
        state["lines"] = []
    threading.Thread(target=run_all, args=(msg, items, record), daemon=True).start()
    return True


SELF = Path(__file__).resolve()
try:
    SELF_MTIME = SELF.stat().st_mtime
except OSError:
    SELF_MTIME = 0.0


def restart_if_updated() -> None:
    """When Claude ships a new control.py, the window restarts itself (minimised, Autopilot as it was) once idle."""
    try:
        if SELF.stat().st_mtime == SELF_MTIME or state["running"]:
            return
    except OSError:
        return
    emit("line", "== The control window was updated: restarting it (a few seconds).")
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen([sys.executable, str(SELF), "--quiet", "--wait-port"], cwd=str(ROOT), creationflags=flags)
    time.sleep(0.5)
    os._exit(0)


def autopilot_loop() -> None:
    """Runs Claude's new steps on their own while the switch is on; a server check every 3 hours."""
    next_check = time.time() + 300
    while True:
        time.sleep(30)
        restart_if_updated()
        if not autopilot_on():
            continue
        try:
            items = pending()
            failed = state.get("auto_failed")
            if items and not (failed and failed == pending_stamp()):
                start_run("", title="Autopilot")
            elif time.time() >= next_check:
                next_check = time.time() + 3 * 3600
                item = {"id": "check-auto-" + time.strftime("%Y%m%d-%H%M%S"), "step": "check",
                        "title": STEPS["check"][1], "note": "", "known": True}
                start_run("", [item], False, "Autopilot server check")
        except Exception as e:                  # never let the loop die
            emit("line", f"!! autopilot: {e}")


def emit(kind: str, data) -> None:
    msg = json.dumps({"kind": kind, "data": data})
    with lock:
        if kind == "line":
            state["lines"].append(data)
            state["lines"] = state["lines"][-2000:]
        for q in list(listeners):
            q.put(msg)


def run_all(ship_message: str, items=None, record=True) -> None:
    ran = []
    try:
        LOGS.mkdir(exist_ok=True)
        queue = list(items if items is not None else pending())
        i = 0
        while i < len(queue):
            item = queue[i]
            i += 1
            if not item["known"]:
                emit("line", f"!! Unknown step '{item['step']}' ({item['id']}): ask Claude.")
                emit("result", {"ok": False, "step": item["step"]})
                state["auto_failed"] = pending_stamp()
                write_last([item["id"]], False, item["step"])
                return
            bat, title, interactive = STEPS[item["step"]]
            with lock:
                state["running"] = item
            emit("step", item)
            emit("line", f"===== {title} ({item['id']}) =====")
            # The step's own "press any key" lines get an empty answer. Nothing is answered through stdin (git can
            # swallow it); Ship to GitHub asks nothing and gets the hands-free switch (LEYLINE_SHIP_AUTO, and the older
            # WU_SHIP_AUTO) plus the owner's note, if he typed one (LEYLINE_SHIP_MSG / WU_SHIP_MSG); without a note
            # it commits as "Leyline update <date> <time>". Empty lines only clear "press any key".
            feed = "\n" * 8
            env = dict(os.environ)
            if interactive:
                env["WU_SHIP_AUTO"] = env["LEYLINE_SHIP_AUTO"] = "1"
                note = (ship_message or "").replace("!", "").replace("%", "").replace('"', "'").strip()
                for k in ("WU_SHIP_MSG", "LEYLINE_SHIP_MSG"):
                    env.pop(k, None)
                if note:
                    env["WU_SHIP_MSG"] = env["LEYLINE_SHIP_MSG"] = note
            log = LOGS / f"{item['id']}-{item['step']}.log"
            with open(log, "w", encoding="utf-8") as lf:
                p = subprocess.Popen(["cmd", "/c", "call", str(ROOT / bat)], cwd=str(ROOT), env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    p.stdin.write(feed.encode())
                    p.stdin.close()
                except OSError:
                    pass
                for raw in iter(p.stdout.readline, b""):
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line.strip().lower().startswith("press any key"):
                        continue
                    lf.write(line + "\n")
                    emit("line", line)
                rc = p.wait()
            if rc != 0:
                emit("line", f"!! {title} failed (exit {rc}). Send Claude a screenshot, or the log: logs/{log.name}")
                emit("result", {"ok": False, "step": item["step"]})
                if record:
                    state["auto_failed"] = pending_stamp()
                write_last([item["id"]], False, item["step"])
                return
            if record:
                with open(DONE, "a", encoding="utf-8") as d:
                    d.write(item["id"] + "\n")
            emit("line", f"== {title}: done")
            ran.append(item["id"])
            # Every save to GitHub (the private workspace repo) also refreshes the public Leyline copy (owner
            # 2026-10-25: "make sure it works with ... all changes we make"), unless a Leyline step
            # is already queued after it. A Leyline failure stops the run like any other step.
            if item["step"] == "ship" and not any(q["step"] == "leyline" for q in queue[i:]):
                queue.insert(i, {"id": item["id"] + "-leyline", "step": "leyline",
                                 "title": STEPS["leyline"][1], "note": "follows Save to GitHub",
                                 "known": True})
        emit("result", {"ok": True})
        if ran:
            write_last(ran, True)
    finally:
        with lock:
            state["running"] = None
        emit("state", {})


def check_health() -> None:
    while True:
        res = {}
        for name, url in CHECKS:
            t0 = time.time()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "WrathUnleashed-Control"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    res[name] = {"ok": r.status < 400, "ms": int((time.time() - t0) * 1000), "code": r.status}
            except urllib.error.HTTPError as e:
                ok = e.code in (401, 403, 410)     # the gate answering = up; 410 = game data switched off on purpose
                res[name] = {"ok": ok, "ms": int((time.time() - t0) * 1000), "code": e.code}
            except Exception as e:
                res[name] = {"ok": False, "ms": None, "code": type(e).__name__}
        with lock:
            state["health"], state["health_at"] = res, time.time()
        emit("state", {})
        time.sleep(30)


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(b)

    def _authed(self) -> bool:
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if host not in (f"127.0.0.1:{PORT}", f"localhost:{PORT}"):
            return False
        if origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return False
        return self.headers.get("X-Token") == TOKEN or f"t={TOKEN}" in self.path

    def _art(self, name: str):
        if self.headers.get("Host", "") not in (f"127.0.0.1:{PORT}", f"localhost:{PORT}"):
            return self._send(403, '{"error":"forbidden"}')
        name = urllib.parse.unquote(name)
        b = art_bytes(name)
        if b is None:
            return self._send(404, "not found", "text/plain")
        self.send_response(200)
        self.send_header("Content-Type", ART_TYPES[name])
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "public, max-age=604800")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/art/"):
            return self._art(path[len("/art/"):])
        if path == "/":
            if f"t={TOKEN}" not in self.path:
                return self._send(403, "This link is old. Close this tab and double-click 'Leyline Control.bat'.",
                                  "text/plain")
            return self._send(200, PAGE.replace("__TOKEN__", TOKEN).replace("__THEMEV__", theme_version()),
                              "text/html; charset=utf-8")
        if not self._authed():
            return self._send(403, '{"error":"forbidden"}')
        if path == "/api/state":
            with lock:
                running = state["running"]
                health, at = state["health"], state["health_at"]
                lines = state["lines"][-400:]
            return self._send(200, json.dumps({"pending": pending(), "history": history(),
                                               "claude": claude_status(), "running": running,
                                               "health": health, "health_at": at, "lines": lines,
                                               "autopilot": autopilot_on()}))
        if path == "/api/log":
            name = self.path.split("name=", 1)[-1]
            f = (LOGS / os.path.basename(urllib.request.unquote(name)))
            if not f.exists():
                return self._send(404, "no such log", "text/plain")
            return self._send(200, f.read_text(encoding="utf-8", errors="replace"), "text/plain; charset=utf-8")
        if path == "/api/events":
            q: queue.Queue = queue.Queue()
            with lock:
                listeners.append(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    try:
                        msg = q.get(timeout=15)
                        self.wfile.write(f"data: {msg}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                with lock:
                    if q in listeners:
                        listeners.remove(q)
            return
        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        if not self._authed():
            return self._send(403, '{"error":"forbidden"}')
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if self.path == "/api/launch":
            msg = str(body.get("message") or "")[:200].replace("\n", " ")
            state["auto_failed"] = None
            if not start_run(msg):
                return self._send(409, '{"error":"already running"}')
            return self._send(200, '{"ok":true}')
        if self.path == "/api/autopilot":
            set_autopilot(bool(body.get("on")))
            state["auto_failed"] = None
            emit("state", {})
            return self._send(200, json.dumps({"ok": True, "on": autopilot_on()}))
        if self.path == "/api/check":
            item = {"id": "check-" + time.strftime("%Y%m%d-%H%M%S"), "step": "check",
                    "title": STEPS["check"][1], "note": "", "known": True}
            if not start_run("", [item], False, "Server check"):
                return self._send(409, '{"error":"already running"}')
            return self._send(200, '{"ok":true}')
        if self.path == "/api/gm-console":
            bat = ROOT / "gmconsole" / "Open GM Console.bat"
            if not bat.exists():
                return self._send(404, '{"error":"gmconsole\\Open GM Console.bat is missing"}')
            # Its own window (it keeps the SSH tunnel open; closing that window closes the console).
            subprocess.Popen(["cmd", "/c", "start", "Leyline GM Console", "cmd", "/k", "call", str(bat)],
                             cwd=str(bat.parent), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return self._send(200, '{"ok":true}')
        if self.path == "/api/open-game":
            webbrowser.open("https://play.openvanilla.app/wrath")
            return self._send(200, '{"ok":true}')
        self._send(404, '{"error":"not found"}')


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Leyline Control</title>
<style>
/* The fallback look, readable on its own; the shared theme (/art/wu-theme.css, linked after this) adds the
   starfield, the corner ornaments, the dragons, Cinzel and the red and gold buttons. */
:root{--bg:#07060f;--panel:#12101e;--line:#3a2f18;--line2:#4a3b1c;--text:#ece6d6;--dim:#b4ab96;--gold:#d8b25a;--gold2:#f0d389;
--ok:#6fd88a;--bad:#ff8f80;--warn:#f5c35a;--blue:#9cc2ff;--mono:ui-monospace,SFMono-Regular,Consolas,monospace}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
body{min-height:100vh;overflow-x:hidden}
header{display:flex;align-items:center;gap:10px 14px;padding:14px 28px;flex-wrap:wrap;border-bottom:1px solid var(--line2);
background:linear-gradient(180deg,rgba(18,14,32,.92),rgba(7,6,15,.78))}
.brand{gap:10px}
h1{margin:0;font-size:22px;letter-spacing:.05em;font-weight:600;color:var(--gold2);font-family:Georgia,serif;white-space:nowrap}
.health{display:flex;gap:8px;margin-left:auto;flex-wrap:wrap}
.pill{display:flex;align-items:center;gap:7px;padding:4px 11px;border:1px solid var(--line2);border-radius:99px;
font-size:12.5px;color:var(--dim);background:var(--panel)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--dim)}
.dot.ok{background:var(--ok);box-shadow:0 0 8px var(--ok)}.dot.bad{background:var(--bad);box-shadow:0 0 8px var(--bad)}
.actions{display:flex;gap:8px;flex-wrap:wrap}
main{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.35fr);gap:20px;padding:24px 28px;
max-width:1400px;margin:0 auto}
@media (max-width:900px){main{grid-template-columns:minmax(0,1fr)}}
.card{background:var(--panel);border:1px solid var(--line2);border-radius:4px;padding:20px 22px;min-width:0}
.card h2{margin:0 0 12px;font-size:15px;letter-spacing:.06em;color:var(--gold2);font-weight:600;font-family:Georgia,serif;
padding-bottom:10px;border-bottom:1px solid var(--line)}
.stack{display:flex;flex-direction:column;gap:20px;min-width:0}
.item{display:flex;gap:12px;padding:10px 0;border-top:1px solid var(--line)}
.item:first-of-type{border-top:0}
.item>div{min-width:0;overflow-wrap:anywhere}
.tag{flex:none;font-size:11.5px;padding:2px 8px;border-radius:4px;height:fit-content;border:1px solid var(--line2);
color:var(--gold2);background:rgba(5,4,12,.7);font-family:var(--mono)}
.sub{color:var(--dim);font-size:13px}
.you .tag{color:var(--warn)}.now .tag{color:var(--blue)}.fin .tag{color:var(--ok)}
.launch{display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap}
button{font:600 14px Georgia,serif;cursor:pointer;border-radius:4px;border:1px solid var(--gold);background:#7a1810;color:var(--gold2);
padding:8px 14px}
button.primary{background:linear-gradient(180deg,var(--gold2),var(--gold));color:#2a1a06;border-color:#fff0bf;padding:9px 20px}
button.primary:disabled,button:disabled{opacity:.5;cursor:not-allowed}
#go{padding:10px 22px}
input{font:inherit;flex:1;min-width:180px;background:rgba(5,4,12,.85);border:1px solid var(--line2);border-radius:4px;
color:var(--text);padding:9px 12px}
.console{font-family:var(--mono);font-size:12.5px;background:rgba(3,2,8,.92);border:1px solid var(--line2);border-radius:4px;
height:420px;overflow:auto;padding:12px 14px;white-space:pre-wrap;word-break:break-word;color:#d6d0c2;
box-shadow:inset 0 2px 8px rgba(0,0,0,.6)}
.console .err{color:var(--bad)}.console .hdr{color:var(--gold2)}.console .ok{color:var(--ok)}
.status{display:flex;align-items:center;gap:10px;margin-bottom:10px;font-weight:600}
.spinner{width:14px;height:14px;border:2px solid #3a2f18;border-top-color:var(--gold2);border-radius:50%;
animation:s 0.8s linear infinite}@keyframes s{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.spinner{animation:none;border-color:var(--gold2)}}
.empty{color:var(--dim);font-style:italic}
a{color:var(--gold2)}.hist a{font-family:var(--mono);font-size:12px}
.updated{font-size:12px;color:var(--dim);margin-top:8px}
@media (max-width:640px){header{padding:12px 16px}.health{margin-left:0;width:100%}
.brand{width:100%;justify-content:center}.actions{width:100%}.actions button{flex:1 1 calc(50% - 8px)}
main{padding:16px;gap:16px}.stack{gap:16px}.card{padding:16px}h1{font-size:16px;white-space:normal;text-align:center;min-width:0}.console{height:340px}}
</style><link rel="stylesheet" href="/art/wu-theme.css?v=__THEMEV__"></head><body class="wu">
<header><div class="brand wu-brand"><h1>Leyline Control</h1></div>
<div class="health" id="health"></div>
<div class="actions"><button id="auto" title="While this window is open, Claude's updates run on their own">Autopilot: …</button>
<button id="gmc" title="Opens the GM console (bug reports, players, health, logs) in your browser">GM console</button>
<button id="check">Check server</button><button id="game">Open the game</button></div></header>
<main>
<div class="stack">
  <section class="card"><h2>Waiting on you</h2><div id="you"></div></section>
  <section class="card"><h2>Claude is working on</h2><div id="now"></div><div class="updated" id="cupd"></div></section>
  <section class="card"><h2>Finished</h2><div id="fin"></div></section>
</div>
<div class="stack">
  <section class="card"><h2>Ready to launch</h2><div id="pending"></div>
    <div class="launch"><input id="msg" placeholder="GitHub save note (only used if 'Save to GitHub' is in the list)">
    <button class="primary" id="go">Launch all</button></div></section>
  <section class="card"><h2>Live output</h2><div class="status" id="run"></div><div class="console" id="con"></div></section>
  <section class="card hist"><h2>History</h2><div id="hist"></div></section>
</div></main>
<script>
const T="__TOKEN__",H={"X-Token":T};
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function list(el,items,cls,empty){el.innerHTML=items&&items.length?items.map(i=>{const o=typeof i==="string"?{text:i}:i;
return `<div class="item ${cls}"><span class="tag">${esc(o.tag||"•")}</span><div>${esc(o.text)}${o.detail?`<div class="sub">${esc(o.detail)}</div>`:""}</div></div>`}).join(""):`<div class="empty">${empty}</div>`}
function line(t){const c=$("con"),d=document.createElement("div");d.textContent=t;
if(/^=====/.test(t))d.className="hdr";else if(/^!!|FAILED|error/i.test(t))d.className="err";else if(/^== .*done|OK$/.test(t))d.className="ok";
const stick=c.scrollTop+c.clientHeight>=c.scrollHeight-30;c.appendChild(d);if(stick)c.scrollTop=c.scrollHeight}
let last=null;
async function refresh(){const r=await fetch("/api/state",{headers:H});if(!r.ok)return;const s=await r.json();last=s;
const h=$("health");h.innerHTML=Object.entries(s.health||{}).map(([k,v])=>`<span class="pill"><span class="dot ${v.ok?"ok":"bad"}"></span>${esc(k)}${v.ms!=null?` · ${v.ms} ms`:` · ${esc(v.code)}`}</span>`).join("")||'<span class="pill">checking…</span>';
const c=s.claude||{};list($("you"),c.waiting_on_you,"you","Nothing. You're clear.");
list($("now"),c.now,"now",c.note||"Idle.");list($("fin"),c.done,"fin","Nothing yet.");
$("cupd").textContent=c.updated?`Updated ${c.updated}`:"";
list($("pending"),(s.pending||[]).map(p=>({tag:p.step,text:p.title,detail:p.note})),"","Nothing to launch. You're up to date.");
const a=$("auto");a.textContent=s.autopilot?"Autopilot: ON":"Autopilot: OFF";a.className=s.autopilot?"primary":"";a.dataset.on=s.autopilot?"1":"";
$("go").disabled=!!s.running||!(s.pending||[]).length;
$("run").innerHTML=s.running?`<span class="spinner"></span>${esc(s.running.title||"Running")}…`:'<span class="sub">Idle</span>';
$("hist").innerHTML=(s.history||[]).map(x=>`<div class="item fin"><span class="tag">${esc(x.step)}</span><div>${esc(x.note||x.id)} ${x.log?`<a href="/api/log?t=${T}&name=${encodeURIComponent(x.log)}" target="_blank">log</a>`:""}</div></div>`).join("")||'<div class="empty">No runs yet.</div>';
if(!$("con").childElementCount&&s.lines)s.lines.forEach(line)}
$("go").onclick=async()=>{$("con").innerHTML="";const r=await fetch("/api/launch",{method:"POST",headers:{...H,"Content-Type":"application/json"},body:JSON.stringify({message:$("msg").value})});if(!r.ok)alert("Couldn't start: "+(await r.text()));refresh()};
$("check").onclick=async()=>{$("con").innerHTML="";const r=await fetch("/api/check",{method:"POST",headers:H});if(!r.ok)alert("Busy: "+(await r.text()));refresh()};
$("auto").onclick=async()=>{await fetch("/api/autopilot",{method:"POST",headers:{...H,"Content-Type":"application/json"},body:JSON.stringify({on:!$("auto").dataset.on})});refresh()};
$("gmc").onclick=async()=>{const r=await fetch("/api/gm-console",{method:"POST",headers:H});if(!r.ok)alert("Couldn't open it: "+(await r.text()))};
$("game").onclick=()=>fetch("/api/open-game",{method:"POST",headers:H});
const es=new EventSource(`/api/events?t=${T}`);
es.onmessage=e=>{const m=JSON.parse(e.data);if(m.kind==="line")line(m.data);else refresh()};
refresh();setInterval(refresh,10000);
</script></body></html>"""


def main() -> int:
    url = f"http://127.0.0.1:{PORT}/?t={TOKEN}"
    class Server(http.server.ThreadingHTTPServer):
        # Windows' SO_REUSEADDR lets a second process share the port while the old one keeps answering;
        # claim it exclusively instead, so a stale copy can never serve the page.
        allow_reuse_address = False

        def server_bind(self):
            import socket
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    srv = None
    # --wait-port: started by restart_if_updated(); the old copy is still letting go of the port.
    for _ in range(40 if "--wait-port" in sys.argv else 1):
        try:
            srv = Server(("127.0.0.1", PORT), H)
            break
        except OSError:
            if "--wait-port" in sys.argv:
                time.sleep(0.5)
    if srv is None:
        # Already running (another window): just open it.
        print("Leyline Control is already running; opening it.")
        if not QUIET:
            webbrowser.open(url)
        return 0
    threading.Thread(target=check_health, daemon=True).start()
    threading.Thread(target=autopilot_loop, daemon=True).start()
    print(f"Leyline Control: {url}\n(close this window to stop it)")
    print("Autopilot is " + ("ON: Claude's updates run on their own." if autopilot_on() else "OFF (switch it on in the window)."))
    if not QUIET:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
