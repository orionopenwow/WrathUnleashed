"""Just enough HTTP/1.1 for the relay's few endpoints (one request per connection, small bodies),
standard library only. Caddy in front does TLS, HTTP/2 and HTTP/3."""
import asyncio
import json
import urllib.parse

MAX_HEAD = 16384
MAX_BODY = 16384

REASONS = {200: "OK", 201: "Created", 204: "No Content", 400: "Bad Request", 401: "Unauthorized",
           403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 409: "Conflict",
           413: "Payload Too Large", 429: "Too Many Requests", 500: "Internal Server Error",
           502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout"}


class BadRequest(Exception):
    def __init__(self, status=400, msg="bad request"):
        super().__init__(msg)
        self.status = status


class Request:
    def __init__(self, method, target, headers, body, peer):
        self.method, self.headers, self.body, self.peer = method, headers, body, peer
        u = urllib.parse.urlsplit(target)
        self.path = urllib.parse.unquote(u.path)
        self.query = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        self.ip = peer

    def json(self):
        try:
            doc = json.loads(self.body.decode("utf-8") or "null")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise BadRequest(400, "body is not JSON") from None
        if not isinstance(doc, dict):
            raise BadRequest(400, "body must be a JSON object")
        return doc


async def read_request(reader, peer, timeout=10):
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout)
    except asyncio.LimitOverrunError:
        raise BadRequest(400, "headers too large") from None
    if len(head) > MAX_HEAD:
        raise BadRequest(400, "headers too large")
    lines = head.decode("latin-1").split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) != 3 or not parts[2].startswith("HTTP/1."):
        raise BadRequest(400, "bad request line")
    headers = {}
    for line in lines[1:]:
        if not line:
            continue
        if ":" not in line:
            raise BadRequest(400, "bad header")
        k, v = line.split(":", 1)
        headers[k.strip().lower()] = v.strip()
    cl = headers.get("content-length", "0") or "0"
    if not cl.isdigit():
        raise BadRequest(400, "bad content-length")
    n = int(cl)
    if n > MAX_BODY:
        raise BadRequest(413, "body too large")
    if "chunked" in headers.get("transfer-encoding", "").lower():
        raise BadRequest(400, "chunked bodies are not accepted")
    body = await asyncio.wait_for(reader.readexactly(n), timeout) if n else b""
    return Request(parts[0].upper(), parts[1], headers, body, peer)


def response(status, body=b"", ctype="application/json", headers=None) -> bytes:
    if isinstance(body, (dict, list)):
        body = (json.dumps(body, separators=(",", ":")) + "\n").encode()
    elif isinstance(body, str):
        body = body.encode("utf-8")
    lines = [f"HTTP/1.1 {status} {REASONS.get(status, 'Status')}", f"Content-Length: {len(body)}",
             "Connection: close", "X-Content-Type-Options: nosniff"]
    if body or ctype:
        lines.append(f"Content-Type: {ctype}")
    for k, v in (headers or {}).items():
        lines.append(f"{k}: {v}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body
