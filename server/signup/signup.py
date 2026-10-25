#!/usr/bin/env python3
"""WrathUnleashed account sign-up service (Python 3 standard library only).

Serves a small HTML form at /signup and creates game accounts by sending
`account create <name> <pass>` to the worldserver's SOAP endpoint (127.0.0.1:7878),
logged in as a GM service account (SOAP_USER / SOAP_PASS from the environment).

Runs behind Caddy on 127.0.0.1:8090 (systemd unit: wu-signup.service).

Settings (environment, normally /srv/wrath/signup.env):
  SOAP_USER, SOAP_PASS        GM level 3 account the service logs in to SOAP as (required)
  SOAP_URL                    default http://127.0.0.1:7878/
  SIGNUP_BIND, SIGNUP_PORT    default 127.0.0.1 and 8090
  SIGNUP_PER_IP_PER_HOUR      accounts one IP may create per hour (default 3)
  SIGNUP_ATTEMPTS_PER_IP_PER_HOUR  form posts one IP may send per hour (default 30)
  SIGNUP_GLOBAL_PER_MINUTE    accounts created per minute across all IPs (default 60)
  TURNSTILE_SITEKEY, TURNSTILE_SECRET  optional Cloudflare Turnstile; the check is on only
                              when TURNSTILE_SECRET is set
  SIGNUP_TITLE                page heading (default "Create account")

Rules (3.3.5a client + AzerothCore):
  * account name: 3-16 letters or digits (AzerothCore stores it upper-case)
  * password: 6-16 printable characters, no spaces (16 = AzerothCore MAX_PASS_STR and the
    3.3.5a login field; the SRP6 login upper-cases it, so passwords are not case-sensitive)

The password is never logged, echoed back, or written anywhere by this service.
"""

from __future__ import annotations

import base64
import collections
import html
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape as xml_escape

# --------------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------------


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


SOAP_URL = os.environ.get("SOAP_URL", "http://127.0.0.1:7878/")
SOAP_USER = os.environ.get("SOAP_USER", "")
SOAP_PASS = os.environ.get("SOAP_PASS", "")
BIND = os.environ.get("SIGNUP_BIND", "127.0.0.1")
PORT = env_int("SIGNUP_PORT", 8090)
PER_IP_PER_HOUR = env_int("SIGNUP_PER_IP_PER_HOUR", 3)
ATTEMPTS_PER_IP_PER_HOUR = env_int("SIGNUP_ATTEMPTS_PER_IP_PER_HOUR", 30)
GLOBAL_PER_MINUTE = env_int("SIGNUP_GLOBAL_PER_MINUTE", 60)
TURNSTILE_SITEKEY = os.environ.get("TURNSTILE_SITEKEY", "")
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET", "")
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TITLE = os.environ.get("SIGNUP_TITLE", "Create account")

MAX_BODY = 4096  # the form is tiny; anything bigger is not a real browser submit

USERNAME_RE = re.compile(r"^[A-Za-z0-9]{3,16}$")
# Printable ASCII without space (0x21-0x7E). Space would split the console command.
PASSWORD_RE = re.compile(r"^[\x21-\x7e]{6,16}$")
# Names players must not get: mod-playerbots' random bot accounts ("rndbot..."), the SOAP
# service account, and a few that invite impersonation.
RESERVED_PREFIXES = ("RNDBOT",)
RESERVED_NAMES = {"ADMIN", "ADMINISTRATOR", "GM", "GAMEMASTER", "ROOT", "SYSTEM", "SUPPORT"}

log = logging.getLogger("wu-signup")


# --------------------------------------------------------------------------------------------
# In-memory rate limiting (resets when the service restarts; that is acceptable here)
# --------------------------------------------------------------------------------------------


class SlidingWindow:
    """Counts events per key inside a time window."""

    def __init__(self, window_seconds: int):
        self.window = window_seconds
        self.events: dict[str, collections.deque] = {}
        self.lock = threading.Lock()

    def _trim(self, q: collections.deque, now: float) -> None:
        while q and now - q[0] > self.window:
            q.popleft()

    def count(self, key: str) -> int:
        now = time.monotonic()
        with self.lock:
            q = self.events.get(key)
            if not q:
                return 0
            self._trim(q, now)
            return len(q)

    def add(self, key: str) -> None:
        now = time.monotonic()
        with self.lock:
            self.events.setdefault(key, collections.deque()).append(now)
            # Keep memory bounded: drop idle keys now and then.
            if len(self.events) > 20000:
                for k in list(self.events):
                    self._trim(self.events[k], now)
                    if not self.events[k]:
                        del self.events[k]


created_per_ip = SlidingWindow(3600)
attempts_per_ip = SlidingWindow(3600)
created_global = SlidingWindow(60)

# AzerothCore's SOAP server handles one request at a time; queue ours instead of piling up.
soap_lock = threading.Lock()


# --------------------------------------------------------------------------------------------
# SOAP and Turnstile
# --------------------------------------------------------------------------------------------


class SoapError(Exception):
    """kind: 'exists', 'rejected' (server refused the command), 'auth', 'down'."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(kind)
        self.kind = kind
        self.detail = detail


def _soap_text(body: bytes, tag: str) -> str:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return ""
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == tag and el.text:
            return el.text.strip()
    return ""


def soap_command(command: str) -> str:
    """Runs one console command over AzerothCore SOAP and returns its output.

    Envelope: method executeCommand in namespace urn:AC, one <command> string, HTTP basic
    auth with a GM level 3 account (see ACSoap.cpp in azerothcore-wotlk).
    """
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/" '
        'xmlns:xsi="http://www.w3.org/1999/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/1999/XMLSchema" '
        'xmlns:ns1="urn:AC">'
        "<SOAP-ENV:Body><ns1:executeCommand>"
        f"<command>{xml_escape(command)}</command>"
        "</ns1:executeCommand></SOAP-ENV:Body></SOAP-ENV:Envelope>"
    ).encode("utf-8")
    token = base64.b64encode(f"{SOAP_USER}:{SOAP_PASS}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        SOAP_URL,
        data=envelope,
        method="POST",
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"urn:AC#executeCommand"',
            "Authorization": f"Basic {token}",
        },
    )
    with soap_lock:
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return _soap_text(resp.read(), "result")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SoapError("auth", f"HTTP {e.code}") from None
            fault = _soap_text(e.read(), "faultstring")
            if "exist" in fault.lower():
                raise SoapError("exists", fault) from None
            raise SoapError("rejected", fault or f"HTTP {e.code}") from None
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
            raise SoapError("down", str(e)) from None


def turnstile_ok(token: str, ip: str) -> bool:
    """Server-side Turnstile check. Fails closed (False) on any error."""
    if not token or len(token) > 2048:
        return False
    data = urllib.parse.urlencode(
        {"secret": TURNSTILE_SECRET, "response": token, "remoteip": ip}
    ).encode("ascii")
    req = urllib.request.Request(TURNSTILE_VERIFY_URL, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, socket.timeout, OSError, ValueError) as e:
        log.warning("turnstile verify failed: %s", e)
        return False
    if not result.get("success"):
        log.info("turnstile rejected ip=%s codes=%s", ip, result.get("error-codes"))
        return False
    return True


def soap_reachable() -> bool:
    parsed = urllib.parse.urlsplit(SOAP_URL)
    try:
        with socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 7878), timeout=3):
            return True
    except OSError:
        return False


# --------------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------------


def validate(username: str, password: str, password2: str) -> str | None:
    """Returns an error message for the player, or None when the input is acceptable."""
    if not USERNAME_RE.match(username):
        return "Account name: 3 to 16 letters or digits, no spaces or symbols."
    upper = username.upper()
    if upper.startswith(RESERVED_PREFIXES) or upper in RESERVED_NAMES or upper == SOAP_USER.upper():
        return "That account name is not available. Please pick another."
    if password != password2:
        return "The two passwords do not match."
    if not PASSWORD_RE.match(password):
        return "Password: 6 to 16 characters, no spaces."
    if password.upper() == upper:
        return "The password must not be the same as the account name."
    return None


# --------------------------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------------------------


def page(message: str = "", ok: bool = False, username: str = "") -> bytes:
    note = ""
    if message:
        cls = "ok" if ok else "err"
        note = f'<p class="{cls}" role="status">{html.escape(message)}</p>'
    turnstile_head = turnstile_widget = ""
    if TURNSTILE_SECRET and TURNSTILE_SITEKEY:
        turnstile_head = '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>'
        turnstile_widget = f'<div class="cf-turnstile" data-sitekey="{html.escape(TURNSTILE_SITEKEY)}"></div>'
    form = "" if ok else f"""
<form method="post" action="/signup" autocomplete="off">
  <label>Account name<br>
    <input name="username" required minlength="3" maxlength="16" pattern="[A-Za-z0-9]{{3,16}}"
           value="{html.escape(username)}" autocapitalize="off" spellcheck="false"></label>
  <label>Password<br>
    <input name="password" type="password" required minlength="6" maxlength="16"
           autocomplete="new-password"></label>
  <label>Password again<br>
    <input name="password2" type="password" required minlength="6" maxlength="16"
           autocomplete="new-password"></label>
  {turnstile_widget}
  <button type="submit">Create account</button>
</form>
<p class="hint">Account name: 3-16 letters or digits. Password: 6-16 characters, no spaces.
Passwords are not case-sensitive in this game client.</p>"""
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(TITLE)}</title>
{turnstile_head}
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 26rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.4; }}
  label {{ display: block; margin: .8rem 0; }}
  input {{ width: 100%; padding: .4rem; font-size: 1rem; box-sizing: border-box; }}
  button {{ margin-top: .8rem; padding: .5rem 1rem; font-size: 1rem; }}
  .err {{ color: #a40000; }} .ok {{ color: #006400; }} .hint {{ color: #555; font-size: .9rem; }}
</style></head>
<body>
<h1>{html.escape(TITLE)}</h1>
{note}
{form}
<p><a href="/">Back</a></p>
</body></html>"""
    return doc.encode("utf-8")


# --------------------------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "wu-signup"
    sys_version = ""

    # Quiet the default per-request stderr log (it would include paths and IPs only, but we
    # log our own structured lines instead).
    def log_message(self, fmt: str, *args) -> None:  # noqa: D401
        return

    def client_ip(self) -> str:
        """Real client IP. Only trust X-Forwarded-For when the peer is the local Caddy; take
        the last entry, which is the one Caddy itself appended."""
        peer = self.client_address[0]
        if peer in ("127.0.0.1", "::1"):
            xff = self.headers.get("X-Forwarded-For", "")
            if xff:
                return xff.split(",")[-1].strip()[:64] or peer
        return peer

    def send_page(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        # Only the Turnstile widget (when on) may load scripts/frames, and only from Cloudflare.
        src = "https://challenges.cloudflare.com" if TURNSTILE_SECRET else "'none'"
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
            f"script-src {src}; frame-src {src}; connect-src {src}",
        )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_text(self, status: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def path_only(self) -> str:
        return urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        path = self.path_only()
        if path == "/signup":
            self.send_page(HTTPStatus.OK, page())
        elif path == "/signup/healthz":
            # For Uptime Kuma: 200 when the SOAP port answers, 503 when it does not.
            if soap_reachable():
                self.send_text(HTTPStatus.OK, "ok\n")
            else:
                self.send_text(HTTPStatus.SERVICE_UNAVAILABLE, "soap unreachable\n")
        else:
            self.send_text(HTTPStatus.NOT_FOUND, "not found\n")

    def do_POST(self) -> None:  # noqa: N802
        if self.path_only() != "/signup":
            self.send_text(HTTPStatus.NOT_FOUND, "not found\n")
            return
        ip = self.client_ip()

        # Basic cross-site check: a browser always sends Origin on a form POST; it must be us.
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if origin and urllib.parse.urlsplit(origin).netloc != host:
            log.info("rejected ip=%s reason=cross-origin origin=%s", ip, origin[:100])
            self.send_page(HTTPStatus.FORBIDDEN, page("Please submit the form from this page."))
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self.send_page(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, page("The form data is too large."))
            return

        if attempts_per_ip.count(ip) >= ATTEMPTS_PER_IP_PER_HOUR:
            log.info("rejected ip=%s reason=attempt-limit", ip)
            self.send_page(HTTPStatus.TOO_MANY_REQUESTS, page("Too many attempts. Please try again in an hour."))
            return
        attempts_per_ip.add(ip)

        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        form = urllib.parse.parse_qs(raw, keep_blank_values=True, max_num_fields=10)
        username = form.get("username", [""])[0].strip()
        password = form.get("password", [""])[0]
        password2 = form.get("password2", [""])[0]
        shown_name = username if USERNAME_RE.match(username) else ""

        error = validate(username, password, password2)
        if error:
            log.info("rejected ip=%s user=%s reason=validation", ip, shown_name or "-")
            self.send_page(HTTPStatus.BAD_REQUEST, page(error, username=shown_name))
            return

        if created_per_ip.count(ip) >= PER_IP_PER_HOUR:
            log.info("rejected ip=%s user=%s reason=ip-limit", ip, username)
            self.send_page(
                HTTPStatus.TOO_MANY_REQUESTS,
                page("This connection has made the maximum number of accounts for now. Please try again later.",
                     username=shown_name),
            )
            return
        if created_global.count("all") >= GLOBAL_PER_MINUTE:
            log.warning("rejected ip=%s user=%s reason=global-limit", ip, username)
            self.send_page(HTTPStatus.SERVICE_UNAVAILABLE,
                           page("Lots of sign-ups right now. Please try again in a minute.", username=shown_name))
            return

        if TURNSTILE_SECRET:
            token = form.get("cf-turnstile-response", [""])[0]
            if not turnstile_ok(token, ip):
                self.send_page(HTTPStatus.FORBIDDEN,
                               page("The anti-bot check failed. Please try again.", username=shown_name))
                return

        try:
            # The command contains the password: it is sent to SOAP and nowhere else.
            soap_command(f"account create {username} {password}")
        except SoapError as e:
            if e.kind == "exists":
                log.info("rejected ip=%s user=%s reason=exists", ip, username)
                self.send_page(HTTPStatus.CONFLICT,
                               page("That account name is already taken. Please pick another."))
            elif e.kind == "auth":
                log.error("SOAP login failed (%s): check SOAP_USER/SOAP_PASS and its GM level", e.detail)
                self.send_page(HTTPStatus.SERVICE_UNAVAILABLE,
                               page("Sign-up is temporarily unavailable. Please try again later.", username=shown_name))
            elif e.kind == "down":
                log.error("SOAP unreachable at %s: %s", SOAP_URL, e.detail)
                self.send_page(HTTPStatus.SERVICE_UNAVAILABLE,
                               page("The game server is not reachable right now. Please try again later.",
                                    username=shown_name))
            else:
                # The fault text comes from the core and names the account at most.
                log.warning("SOAP refused account create user=%s: %s", username, e.detail[:200])
                self.send_page(HTTPStatus.BAD_REQUEST,
                               page("The server could not create that account. Please try a different name.",
                                    username=shown_name))
            return

        created_per_ip.add(ip)
        created_global.add("all")
        log.info("created user=%s ip=%s", username.upper(), ip)
        self.send_page(
            HTTPStatus.OK,
            page(f"Account {username.upper()} created. You can log in now.", ok=True),
        )


def main() -> int:
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if not SOAP_USER or not SOAP_PASS:
        log.error("SOAP_USER and SOAP_PASS must be set (see /srv/wrath/signup.env)")
        return 2
    if TURNSTILE_SECRET and not TURNSTILE_SITEKEY:
        log.warning("TURNSTILE_SECRET is set but TURNSTILE_SITEKEY is empty: the widget cannot render")
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    server.daemon_threads = True
    log.info(
        "listening on %s:%d, soap=%s, per-ip/hour=%d, turnstile=%s",
        BIND, PORT, SOAP_URL, PER_IP_PER_HOUR, "on" if TURNSTILE_SECRET else "off",
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
