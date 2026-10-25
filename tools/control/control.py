#!/usr/bin/env python3
"""WrathUnleashed Control: the owner's one window for launching what Claude has ready.

    py -3 tools\\control\\control.py          (or double-click "WrathUnleashed Control.bat")

Serves a page on http://127.0.0.1:8097 (this PC only) and opens it. The page shows:
  * Live: the realm, Play page and game files answering (checked from this PC every 30 s).
  * Claude: what Claude is working on, what is waiting for you, what finished (control/claude-status.json,
    which Claude keeps up to date in this folder).
  * Ready to launch: the steps in UPDATES-PENDING.txt not yet in UPDATES-DONE.txt; "Launch all" runs them in
    order (the same steps UPDATE.bat runs) and streams each step's output live; it stops at a failure.
  * History: finished steps with their logs (logs/<id>-<step>.log).
Only this PC can open it: it listens on 127.0.0.1, and every action needs the session token in the page.
Standard library only.
"""
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
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # the WrathUnleashed folder
PEND = ROOT / "UPDATES-PENDING.txt"
DONE = ROOT / "UPDATES-DONE.txt"
LOGS = ROOT / "logs"
STATUS = ROOT / "control" / "claude-status.json"
PORT = int(os.environ.get("WU_CONTROL_PORT", "8097"))
TOKEN_FILE = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WrathUnleashed" / "control-token"


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
    "scripts": ("realm/Server pass - finder 10 and bug reports.bat", "Realm scripts (live reload)", False),
    "realm":   ("realm/Server pass - finder 10 and bug reports.bat", "Realm settings (5-min restart)", False),
    "foreverui": ("stream/Add Forever UI to the stream.bat", "Forever UI look (menus and character select)", False),
    "slice":   ("stream/Make mini slice.bat", "Streamed game files (30-60 min)", False),
    "ship":    ("Ship WrathUnleashed.bat", "Save everything to GitHub", True),
    "check":   ("realm/Server check.bat", "Server check (read-only)", False),
    "gm":      ("gmconsole/Install GM Console.bat", "GM console update (game keeps running)", False),
    "lean":    ("realm/Lean server.bat", "Lean server: fewer bots, idle areas unload (5-min restart)", False),
}
CHECKS = [
    ("Play page", "https://play.openvanilla.app/wrath"),
    ("Game files", "https://wrath.openvanilla.app/data/__tier/index.json"),
    ("Client", "https://wrath.openvanilla.app/boot-manifest.json"),
]

state = {"running": None, "lines": [], "health": {}, "health_at": 0}
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


def emit(kind: str, data) -> None:
    msg = json.dumps({"kind": kind, "data": data})
    with lock:
        if kind == "line":
            state["lines"].append(data)
            state["lines"] = state["lines"][-2000:]
        for q in list(listeners):
            q.put(msg)


def run_all(ship_message: str, items=None, record=True) -> None:
    try:
        LOGS.mkdir(exist_ok=True)
        for item in (items if items is not None else pending()):
            if not item["known"]:
                emit("line", f"!! Unknown step '{item['step']}' ({item['id']}): ask Claude.")
                emit("result", {"ok": False, "step": item["step"]})
                return
            bat, title, interactive = STEPS[item["step"]]
            with lock:
                state["running"] = item
            emit("step", item)
            emit("line", f"===== {title} ({item['id']}) =====")
            # The step's own "press any key" lines get an empty answer; ship gets yes + the message.
            # Nothing is answered through stdin (git can swallow it); steps with a question get a hands-free
            # switch instead (Ship: WU_SHIP_AUTO / WU_SHIP_MSG). Empty lines only clear "press any key".
            feed = "\n" * 8
            env = dict(os.environ)
            if interactive:
                env["WU_SHIP_AUTO"] = "1"
                env["WU_SHIP_MSG"] = (ship_message or "Updates from Claude").replace("!", "").replace("%", "")
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
                return
            if record:
                with open(DONE, "a", encoding="utf-8") as d:
                    d.write(item["id"] + "\n")
            emit("line", f"== {title}: done")
        emit("result", {"ok": True})
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
                ok = e.code in (401, 403)          # the gate answering = up
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

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            if f"t={TOKEN}" not in self.path:
                return self._send(403, "This link is old. Close this tab and double-click 'WrathUnleashed Control.bat'.",
                                  "text/plain")
            return self._send(200, PAGE.replace("__TOKEN__", TOKEN), "text/html; charset=utf-8")
        if not self._authed():
            return self._send(403, '{"error":"forbidden"}')
        if path == "/api/state":
            with lock:
                running = state["running"]
                health, at = state["health"], state["health_at"]
                lines = state["lines"][-400:]
            return self._send(200, json.dumps({"pending": pending(), "history": history(),
                                               "claude": claude_status(), "running": running,
                                               "health": health, "health_at": at, "lines": lines}))
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
            with lock:
                if state["running"]:
                    return self._send(409, '{"error":"already running"}')
                state["running"] = {"id": "", "step": "starting", "title": "Starting"}
                state["lines"] = []
            msg = str(body.get("message") or "")[:200].replace("\n", " ")
            threading.Thread(target=run_all, args=(msg,), daemon=True).start()
            return self._send(200, '{"ok":true}')
        if self.path == "/api/check":
            with lock:
                if state["running"]:
                    return self._send(409, '{"error":"already running"}')
                state["running"] = {"id": "", "step": "check", "title": "Server check"}
                state["lines"] = []
            item = {"id": "check-" + time.strftime("%Y%m%d-%H%M%S"), "step": "check",
                    "title": STEPS["check"][1], "note": "", "known": True}
            threading.Thread(target=run_all, args=("", [item], False), daemon=True).start()
            return self._send(200, '{"ok":true}')
        if self.path == "/api/open-game":
            webbrowser.open("https://play.openvanilla.app/wrath")
            return self._send(200, '{"ok":true}')
        self._send(404, '{"error":"not found"}')


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WrathUnleashed Control</title>
<style>
:root{--bg:#0b0d12;--panel:#12151d;--line:#232837;--text:#e7e9ee;--dim:#8b93a7;--gold:#d8b25a;--gold2:#f0d389;
--ok:#4fd18b;--bad:#ff6b6b;--warn:#f5b84a;--blue:#7aa7ff;--mono:ui-monospace,SFMono-Regular,Consolas,monospace}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.45 Inter,Segoe UI,system-ui,sans-serif}
header{display:flex;align-items:center;gap:16px;padding:18px 28px;border-bottom:1px solid var(--line);
background:linear-gradient(180deg,#141824,#0b0d12)}
h1{margin:0;font-size:18px;letter-spacing:.04em;font-weight:650}
h1 span{color:var(--gold)}
.health{display:flex;gap:8px;margin-left:auto;flex-wrap:wrap}
.pill{display:flex;align-items:center;gap:7px;padding:5px 11px;border:1px solid var(--line);border-radius:99px;
font-size:12px;color:var(--dim);background:var(--panel)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--dim)}
.dot.ok{background:var(--ok);box-shadow:0 0 8px var(--ok)}.dot.bad{background:var(--bad);box-shadow:0 0 8px var(--bad)}
main{display:grid;grid-template-columns:minmax(320px,1fr) minmax(380px,1.35fr);gap:20px;padding:22px 28px;
max-width:1400px;margin:0 auto}
@media (max-width:900px){main{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px}
.card h2{margin:0 0 12px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim);font-weight:600}
.stack{display:flex;flex-direction:column;gap:20px}
.item{display:flex;gap:12px;padding:10px 0;border-top:1px solid var(--line)}
.item:first-of-type{border-top:0}
.tag{flex:none;font-size:11px;padding:2px 8px;border-radius:6px;height:fit-content;border:1px solid var(--line);
color:var(--gold2);background:#1a1d27;font-family:var(--mono)}
.sub{color:var(--dim);font-size:12.5px}
.you .tag{color:var(--warn)}.now .tag{color:var(--blue)}.fin .tag{color:var(--ok)}
.launch{display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap}
button{font:inherit;cursor:pointer;border-radius:10px;border:1px solid var(--line);background:#1a1e2a;color:var(--text);
padding:9px 14px}button:hover{border-color:#3a4157}
button.primary{background:linear-gradient(180deg,var(--gold2),var(--gold));color:#1b1406;border:0;font-weight:650;
padding:11px 20px}button.primary:disabled{opacity:.45;cursor:not-allowed}
input{font:inherit;flex:1;min-width:180px;background:#0e1118;border:1px solid var(--line);border-radius:10px;
color:var(--text);padding:9px 12px}
.console{font-family:var(--mono);font-size:12.5px;background:#07090d;border:1px solid var(--line);border-radius:10px;
height:420px;overflow:auto;padding:12px 14px;white-space:pre-wrap;word-break:break-word;color:#c9cfdb}
.console .err{color:var(--bad)}.console .hdr{color:var(--gold2)}.console .ok{color:var(--ok)}
.status{display:flex;align-items:center;gap:10px;margin-bottom:10px;font-weight:600}
.spinner{width:14px;height:14px;border:2px solid #39405a;border-top-color:var(--gold);border-radius:50%;
animation:s 0.8s linear infinite}@keyframes s{to{transform:rotate(360deg)}}
.empty{color:var(--dim);font-style:italic}
a{color:var(--blue)}.hist a{font-family:var(--mono);font-size:12px}
.updated{font-size:11.5px;color:var(--dim);margin-top:8px}
</style></head><body>
<header><h1>WrathUnleashed <span>Control</span></h1>
<div class="health" id="health"></div>
<button id="check">Check server</button><button id="game">Open the game</button></header>
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
$("go").disabled=!!s.running||!(s.pending||[]).length;
$("run").innerHTML=s.running?`<span class="spinner"></span>${esc(s.running.title||"Running")}…`:'<span class="sub">Idle</span>';
$("hist").innerHTML=(s.history||[]).map(x=>`<div class="item fin"><span class="tag">${esc(x.step)}</span><div>${esc(x.note||x.id)} ${x.log?`<a href="/api/log?t=${T}&name=${encodeURIComponent(x.log)}" target="_blank">log</a>`:""}</div></div>`).join("")||'<div class="empty">No runs yet.</div>';
if(!$("con").childElementCount&&s.lines)s.lines.forEach(line)}
$("go").onclick=async()=>{$("con").innerHTML="";const r=await fetch("/api/launch",{method:"POST",headers:{...H,"Content-Type":"application/json"},body:JSON.stringify({message:$("msg").value})});if(!r.ok)alert("Couldn't start: "+(await r.text()));refresh()};
$("check").onclick=async()=>{$("con").innerHTML="";const r=await fetch("/api/check",{method:"POST",headers:H});if(!r.ok)alert("Busy: "+(await r.text()));refresh()};
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

    try:
        srv = Server(("127.0.0.1", PORT), H)
    except OSError:
        # Already running (another window): just open it.
        print("WrathUnleashed Control is already running; opening it.")
        webbrowser.open(url)
        return 0
    threading.Thread(target=check_health, daemon=True).start()
    print(f"WrathUnleashed Control: {url}\n(close this window to stop it)")
    webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
