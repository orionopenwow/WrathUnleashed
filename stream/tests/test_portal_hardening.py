"""The portal's hardening (stream/wrath_portal.py): the shared limiter is in use (and a stand-in when ratelimit.py is
missing), callers idle on their socket are dropped, a full server answers 503 at once, the SOAP lock never makes a
caller wait past SOAP_TIMEOUT, the SOAP bridge checks BRIDGE_PASS (constant time) when it is set, and the Admin
Console's dispatch returns.

    python3 -I stream/tests/test_portal_hardening.py stream/wrath_portal.py
"""
import base64, importlib.util, os, shutil, socket, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler

PORTAL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wrath_portal.py")
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL="http://127.0.0.1:9",
                  WU_PORTAL_DATA=tempfile.mkdtemp(prefix="wu-hard-"), SOAP_TIMEOUT="1", WU_HANDLER_TIMEOUT="5")
os.environ.pop("BRIDGE_PASS", None)
fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    fails += 0 if cond else 1


def load(path, name):
    sys.modules.pop("wu_ratelimit", None)
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


wp = load(PORTAL, "wp")
check("the shared limiter is loaded", wp.ratelimit.__file__.endswith("ratelimit.py"))
check("the modules share it", wp.social is None or wp.social._ratelimit() is wp.ratelimit)
check("IPv6 limits count the /64", wp.rl_bucket("2001:db8::1") == wp.rl_bucket("2001:db8::ffff"))
check("hk-all is a global cap", "hk-all" in wp.herokey_limit.global_keys)

# ---------------------------------------------------------------- a portal sent alone: the stand-in
tmp = tempfile.mkdtemp(prefix="wu-alone-")
shutil.copy(PORTAL, os.path.join(tmp, "wrath_portal.py"))
alone = load(os.path.join(tmp, "wrath_portal.py"), "wp_alone")
L = alone._Window(60, global_keys=("all",))
check("without ratelimit.py: a stand-in limiter", L.hit("a", 1) and not L.hit("a", 1))
check("stand-in keeps global caps through clear()", L.hit("all", 1) and (L.clear() or True) and not L.hit("all", 1))
sys.modules.pop("wu_ratelimit", None)
sys.modules["wu_ratelimit"] = wp.ratelimit

# ---------------------------------------------------------------- timeouts and the 503
check("page handler socket timeout", wp.PageHandler.timeout == 5.0)
check("bridge handler socket timeout", wp.BridgeHandler.timeout == 5.0)

gate = threading.Event()


class Slow(BaseHTTPRequestHandler):
    timeout = 5

    def log_message(self, *a): pass

    def do_GET(self):
        gate.wait(10)
        self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"ok")


srv = wp.Server(("127.0.0.1", 0), Slow, max_conn=2)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
held = []
for _ in range(2):
    s = socket.create_connection(("127.0.0.1", port)); s.sendall(b"GET / HTTP/1.0\r\n\r\n"); held.append(s)
time.sleep(0.3)
s = socket.create_connection(("127.0.0.1", port), timeout=3)
s.sendall(b"GET / HTTP/1.0\r\n\r\n")
got = s.recv(200)
check("full: the next caller gets 503 at once", got.startswith(b"HTTP/1.0 503"), got[:40])
check("busy counted", srv.busy_count == 1)
gate.set()
ok = all(h.recv(100).startswith(b"HTTP/1.0 200") for h in held)
check("the held requests finish", ok)
time.sleep(0.2)
s = socket.create_connection(("127.0.0.1", port), timeout=3); s.sendall(b"GET / HTTP/1.0\r\n\r\n")
check("slots come back", s.recv(100).startswith(b"HTTP/1.0 200"))


class Idle(BaseHTTPRequestHandler):
    timeout = 1

    def log_message(self, *a): pass

    def do_GET(self):
        self.send_response(200); self.end_headers()


srv2 = wp.Server(("127.0.0.1", 0), Idle, max_conn=4)
threading.Thread(target=srv2.serve_forever, daemon=True).start()
s = socket.create_connection(("127.0.0.1", srv2.server_address[1]), timeout=5)
s.sendall(b"GET / HT")   # slow-loris: never finishes the request line
t0 = time.monotonic()
try:
    closed = s.recv(10) == b""
except OSError:
    closed = True
check("an idle caller is dropped after the handler timeout", closed and time.monotonic() - t0 < 4)

# ---------------------------------------------------------------- SOAP lock
wp._soap_lock.acquire()
t0 = time.monotonic()
try:
    wp.ac_soap("server info")
    kind = ""
except wp.SoapError as e:
    kind = e.detail
took = time.monotonic() - t0
wp._soap_lock.release()
check("a stuck SOAP call makes others wait at most SOAP_TIMEOUT", "busy" in kind and took < 2.5, f"{kind} {took:.1f}s")
check("the lock is released after a failed call", (wp._soap_lock.acquire(timeout=0.1) and (wp._soap_lock.release() or True)))
try:
    wp.ac_soap("server info")
except wp.SoapError:
    pass
check("the lock is released after a down worldserver", wp._soap_lock.acquire(timeout=0.1))
wp._soap_lock.release()

# ---------------------------------------------------------------- the bridge's Basic auth


def basic(u, p):
    return "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()


check("legacy (no BRIDGE_PASS): the login name", wp.bridge_auth_ok(basic("wrsoap", "anything")))
check("legacy: an unknown login is refused", not wp.bridge_auth_ok(basic("someone", "x")))
check("no auth is refused", not wp.bridge_auth_ok("") and not wp.bridge_auth_ok("Basic !!!"))
wp.BRIDGE_PASS = "s3cret"
check("BRIDGE_PASS set: the right password passes", wp.bridge_auth_ok(basic("WRSOAP", "s3cret")))
check("BRIDGE_PASS set: a wrong password is refused", not wp.bridge_auth_ok(basic("WRSOAP", "s3cre")))
check("BRIDGE_PASS set: the right password with an unknown login is refused", not wp.bridge_auth_ok(basic("X", "s3cret")))
wp.BRIDGE_PASS = ""

# ---------------------------------------------------------------- the admin dispatch returns
src = open(PORTAL).read()
check("admin.post is followed by return", "admin.post(self, path)\n            return\n" in src)
check("admin.get is followed by return", "admin.get(self, path, query)\n            return\n" in src)

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
