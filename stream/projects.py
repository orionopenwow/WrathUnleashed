"""Community projects for the Leyline Workshop: links people submit, listed at once (no review queue).

A project is a link only: a public repo on GitHub, GitLab, Codeberg or another forge, or a project page.
Nothing is downloaded or hosted from a submission. On submit the server asks the forge's public API for
the repo's name, description, licence, stars, last push and owner (GitHub, GitLab, Codeberg; never the
submitted URL itself, so a link can not make the server fetch anything else). A dead or slow API never
blocks a submission: the record keeps what the submitter typed and last_checked stays empty.

Storage: one JSON object per line in $WU_PORTAL_DATA/projects.jsonl (default /data, a writable mount beside
the read-only /app). Every change rewrites the file atomically (temp file, fsync, rename) under a lock.
The portal has no database, so this keeps to plain files like the rest of it.

Record (the file; all.json publishes the public fields, never "submitter" or "reports"):
    id            12 hex chars of sha256(canonical url)
    url           the canonical https URL (forges: https://<host>/<owner>/<repo>)
    host, forge   "github.com", "github" | "gitlab" | "codeberg" | "" (other)
    title, author, author_url, licence, description, category, builds ["3.3.5a"] | ["1.12"] |
                  ["3.3.5a", "1.12"] | ["any"]
    stars, last_push   from the forge (null when unknown)
    submitted_by  the submitter's display name;  submitter  their account id (private)
    submitted_at, last_checked   ISO 8601 UTC ("" when the forge was never reached)
    reports       account ids that reported it (private);  hidden, hidden_by, hidden_at

Settings (environment):
    WU_PORTAL_DATA       the data folder (default /data)
    WU_PROJECTS_PER_DAY  submissions per account per 24 h (default 3)
    WU_PROJECTS_DAY_MAX  submissions from everyone per 24 h (default 100)
    WU_PROJECTS_MAX      records in all (default 2000)
    WU_PROJECT_HOSTS     extra allowed hosts, comma separated (".example.org" allows its subdomains)
    WU_MODS_ADMINS       account ids that may hide and unhide records, comma separated
    WU_GITHUB_TOKEN      optional, raises GitHub's rate limit; sent only to the GitHub API, never logged
    WU_GITHUB_API, WU_GITLAB_API, WU_CODEBERG_API   API bases (tests point them at a fake)
Standard library only.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import fcntl
except ImportError:   # not on the server (Linux), but keep the module importable anywhere
    fcntl = None

log = logging.getLogger("wrath-portal.projects")

BUILDS = {"3.3.5a": ["3.3.5a"], "1.12": ["1.12"], "both": ["3.3.5a", "1.12"], "any": ["any"]}
BUILD_LABEL = {"3.3.5a": "3.3.5a", "1.12": "1.12", "any": "Any build"}
MAX_URL = 300
MAX_DESC = 140
MIN_DESC = 10
MAX_TEXT = 120
PID_RE = re.compile(r"^[0-9a-f]{12}$")
SEG_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
HOST_RE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
BRAND_RE = re.compile(r"(?i)world\s*of\s*warcraft|warcraft|lich\s*king|blizzard|\bwow\b")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")

FORGES = {"github.com": "github", "gitlab.com": "gitlab", "codeberg.org": "codeberg"}
DEFAULT_HOSTS = ("github.com", "gitlab.com", "codeberg.org", "bitbucket.org", "git.sr.ht", "sr.ht", "gitea.com",
                 "sourceforge.net", "notabug.org", "framagit.org", "itch.io", "curseforge.com", "www.curseforge.com",
                 "wago.io", "addons.wago.io", ".github.io", ".gitlab.io", ".codeberg.page", ".itch.io")
# First path parts on the forges that are their own pages, never a user's repo.
FORGE_RESERVED = {"about", "explore", "settings", "topics", "orgs", "users", "search", "marketplace", "login",
                  "signup", "features", "pricing", "sponsors", "trending", "collections", "notifications", "api",
                  "help", "admin", "dashboard", "new", "-"}


def _now_iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _iso_time(s: str) -> float:
    try:
        return float(calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")))
    except (ValueError, TypeError, OverflowError):
        return 0.0


def clean_text(v, n: int = MAX_TEXT) -> str:
    """One line of plain text: control and direction characters dropped, spaces collapsed, cut to n."""
    if not isinstance(v, str):
        return ""
    return re.sub(r"\s+", " ", CTRL_RE.sub(" ", v)).strip()[:n]


def scrub(v: str) -> str:
    """Metadata from a forge, shown on our pages: the game's brand names replaced with plain words."""
    def rep(m):
        w = m.group(0).lower()
        return "Wrath" if "lich" in w else "the publisher" if "blizzard" in w else "the game"
    return BRAND_RE.sub(rep, v)


def account_of(me) -> str:
    """The account id in the website's /api/me answer (its Hero Key account), or ''."""
    if not isinstance(me, dict):
        return ""
    for k in ("id", "user_id", "account_id", "username"):
        v = me.get(k)
        if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v).strip():
            return clean_text(str(v), 64)
    return ""


def display_of(me) -> str:
    if not isinstance(me, dict):
        return ""
    return clean_text(str(me.get("display_name") or me.get("username") or ""), 40) or "a player"


def allowed_hosts() -> tuple[str, ...]:
    extra = tuple(h.strip().lower() for h in os.environ.get("WU_PROJECT_HOSTS", "").split(",") if h.strip())
    return DEFAULT_HOSTS + extra


def host_ok(host: str, hosts=None) -> bool:
    for h in hosts or allowed_hosts():
        if h.startswith("."):
            if host.endswith(h) and len(host) > len(h):
                return True
        elif host == h:
            return True
    return False


def normalize_url(raw: str, hosts=None) -> dict:
    """The canonical form of a submitted link, or ValueError with a message for the submitter."""
    if not isinstance(raw, str):
        raise ValueError("Paste the project's link.")
    raw = raw.strip()
    if not raw:
        raise ValueError("Paste the project's link.")
    if len(raw) > MAX_URL:
        raise ValueError(f"That link is longer than {MAX_URL} characters.")
    if CTRL_RE.search(raw) or re.search(r"\s", raw):
        raise ValueError("That link has spaces or hidden characters in it.")
    try:
        u = urllib.parse.urlsplit(raw)
        port = u.port
    except ValueError:
        raise ValueError("That doesn't look like a link.") from None
    if u.scheme.lower() != "https":
        raise ValueError("Links must start with https://.")
    if u.username is not None or u.password is not None or "@" in u.netloc:
        raise ValueError("Links can't carry a login.")
    if port not in (None, 443):
        raise ValueError("Links can't name a port.")
    host = (u.hostname or "").lower().rstrip(".")
    if not HOST_RE.fullmatch(host):
        raise ValueError("That link's site name isn't a normal web address.")
    if not host_ok(host, hosts):
        raise ValueError(f"Links from {host} aren't accepted yet. Use a repo on GitHub, GitLab or Codeberg, "
                         "or ask us to add the site.")
    path = urllib.parse.unquote(u.path or "/")
    if CTRL_RE.search(path) or ".." in path.split("/"):
        raise ValueError("That link's path isn't valid.")
    parts = [p for p in path.split("/") if p]
    forge = FORGES.get(host, "")
    owner = repo = ""
    if forge:
        if "-" in parts:
            parts = parts[:parts.index("-")]
        if forge == "gitlab":
            parts = parts[:4]
        else:
            parts = parts[:2]
        if len(parts) < 2 or parts[0].lower() in FORGE_RESERVED or not all(SEG_RE.fullmatch(p) for p in parts):
            raise ValueError(f"Link the repo itself: https://{host}/<owner>/<project>.")
        if parts[-1].lower().endswith(".git"):
            parts[-1] = parts[-1][:-4]
            if not parts[-1]:
                raise ValueError(f"Link the repo itself: https://{host}/<owner>/<project>.")
        owner, repo = "/".join(parts[:-1]), parts[-1]
        canon = f"https://{host}/" + "/".join(parts)
    else:
        clean = "/".join(urllib.parse.quote(p, safe="-._~!$&'()*+,;=:@") for p in parts)
        canon = f"https://{host}/" + clean
    return {"url": canon, "host": host, "forge": forge, "owner": owner, "repo": repo,
            "key": canon.lower().rstrip("/")}


# ---------------------------------------------------------------- forge metadata

class Meta:
    """Public repo metadata from the forges' APIs, cached in memory (an hour; five minutes after a failure)."""

    def __init__(self, timeout: float = 4.0):
        self.timeout = timeout
        self.cache: dict[str, tuple[float, object]] = {}
        self.lock = threading.Lock()

    @staticmethod
    def api_url(forge: str, owner: str, repo: str) -> str:
        if forge == "github":
            base = os.environ.get("WU_GITHUB_API", "https://api.github.com").rstrip("/")
            return f"{base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}"
        if forge == "gitlab":
            base = os.environ.get("WU_GITLAB_API", "https://gitlab.com/api/v4").rstrip("/")
            return f"{base}/projects/{urllib.parse.quote(owner + '/' + repo, safe='')}?license=true"
        if forge == "codeberg":
            base = os.environ.get("WU_CODEBERG_API", "https://codeberg.org/api/v1").rstrip("/")
            return f"{base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}"
        return ""

    def _get(self, forge: str, url: str):
        """The decoded JSON, "missing" for a 404, or None when the API could not be reached."""
        headers = {"Accept": "application/json", "User-Agent": "leyline-workshop"}
        if forge == "github":
            headers["Accept"] = "application/vnd.github+json"
            tok = os.environ.get("WU_GITHUB_TOKEN", "").strip()
            if tok:
                headers["Authorization"] = "Bearer " + tok
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=self.timeout) as r:
                return json.loads(r.read(262144).decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (404, 410, 451):
                return "missing"
            log.info("%s metadata: HTTP %s", forge, e.code)   # never the headers: they may hold the token
            return None
        except (urllib.error.URLError, OSError, ValueError, UnicodeDecodeError) as e:
            log.info("%s metadata unavailable: %s", forge, type(e).__name__)
            return None

    def fetch(self, forge: str, owner: str, repo: str):
        """A dict of {title, description, licence, stars, last_push, author, author_url, private},
        "missing", or None (unknown: the API is down, slow or rate limited)."""
        url = self.api_url(forge, owner, repo)
        if not url:
            return None
        now = time.time()
        with self.lock:
            hit = self.cache.get(url)
            if hit and hit[0] > now:
                return hit[1]
        doc = self._get(forge, url)
        out = doc if doc == "missing" else (self._parse(forge, doc) if isinstance(doc, dict) else None)
        with self.lock:
            if len(self.cache) > 500:
                self.cache.clear()
            self.cache[url] = (now + (3600 if out is not None else 300), out)
        return out

    @staticmethod
    def _parse(forge: str, d: dict) -> dict:
        def num(v):
            return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None

        def txt(v, n=MAX_TEXT):
            return scrub(clean_text(v, n)) if isinstance(v, str) else ""
        owner = d.get("owner") if isinstance(d.get("owner"), dict) else {}
        if forge == "github":
            lic = d.get("license") if isinstance(d.get("license"), dict) else {}
            spdx = lic.get("spdx_id") if lic.get("spdx_id") not in (None, "NOASSERTION") else lic.get("name")
            return {"title": txt(d.get("name"), 80), "description": txt(d.get("description"), 300),
                    "licence": clean_text(spdx or "", 60), "stars": num(d.get("stargazers_count")),
                    "last_push": clean_text(d.get("pushed_at") or "", 25), "author": txt(owner.get("login"), 60),
                    "author_url": _https(owner.get("html_url")), "private": bool(d.get("private"))}
        if forge == "gitlab":
            lic = d.get("license") if isinstance(d.get("license"), dict) else {}
            ns = d.get("namespace") if isinstance(d.get("namespace"), dict) else {}
            return {"title": txt(d.get("name"), 80), "description": txt(d.get("description"), 300),
                    "licence": clean_text(lic.get("nickname") or lic.get("name") or "", 60),
                    "stars": num(d.get("star_count")), "last_push": clean_text(d.get("last_activity_at") or "", 25),
                    "author": txt(ns.get("name") or ns.get("path"), 60), "author_url": _https(ns.get("web_url")),
                    "private": d.get("visibility") not in (None, "public")}
        lic = ""
        if isinstance(d.get("licenses"), list) and d["licenses"] and isinstance(d["licenses"][0], str):
            lic = d["licenses"][0]
        return {"title": txt(d.get("name"), 80), "description": txt(d.get("description"), 300),
                "licence": clean_text(lic, 60), "stars": num(d.get("stars_count")),
                "last_push": clean_text(d.get("updated_at") or "", 25), "author": txt(owner.get("login"), 60),
                "author_url": _https(owner.get("html_url")), "private": bool(d.get("private"))}


def _https(v) -> str:
    """A link from a forge's answer, kept only when it is a plain https URL."""
    if not isinstance(v, str) or len(v) > MAX_URL or not v.startswith("https://") or CTRL_RE.search(v) or re.search(r"\s", v):
        return ""
    try:
        h = (urllib.parse.urlsplit(v).hostname or "").lower()
    except ValueError:
        return ""
    return v if HOST_RE.fullmatch(h) else ""


# ---------------------------------------------------------------- the store

class Projects:
    def __init__(self, data_dir: str | None = None, categories=None, meta: Meta | None = None, now=time.time):
        self.dir = data_dir or os.environ.get("WU_PORTAL_DATA", "/data")
        self.path = os.path.join(self.dir, "projects.jsonl")
        self._categories = categories   # a list of ids, or a callable returning one (read at each submit)
        self.meta = meta or Meta()
        self.now = now
        self.lock = threading.RLock()
        self._cache = (None, [])
        self._sweep_at = 0.0
        self.per_day = int(os.environ.get("WU_PROJECTS_PER_DAY", "3") or 3)
        self.day_max = int(os.environ.get("WU_PROJECTS_DAY_MAX", "100") or 100)
        self.max_records = int(os.environ.get("WU_PROJECTS_MAX", "2000") or 2000)
        self.reports_per_day = 20
        self._report_log: dict[str, list[float]] = {}

    def category_ids(self) -> set[str]:
        c = self._categories
        try:
            return set(c() if callable(c) else (c or ()))
        except Exception:   # noqa: BLE001
            return set()

    @staticmethod
    def admins() -> set[str]:
        return {a.strip() for a in os.environ.get("WU_MODS_ADMINS", "").split(",") if a.strip()}

    def is_admin(self, me) -> bool:
        a = account_of(me)
        return bool(a) and a in self.admins()

    def writable(self) -> bool:
        return os.path.isdir(self.dir) and os.access(self.dir, os.W_OK)

    # -------------------------------------------------- file
    def _stat(self):
        try:
            st = os.stat(self.path)
            return (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            return None

    def load(self) -> list[dict]:
        """Every record (hidden ones too), reread only when the file changes. A bad line is skipped."""
        key = self._stat()
        with self.lock:
            if key is not None and self._cache[0] == key:
                return self._cache[1]
            recs = []
            if key is not None:
                try:
                    with open(self.path, encoding="utf-8") as f:
                        for line in f:
                            try:
                                r = json.loads(line)
                            except ValueError:
                                continue
                            if isinstance(r, dict) and isinstance(r.get("id"), str) and PID_RE.fullmatch(r["id"]):
                                recs.append(r)
                except (OSError, UnicodeDecodeError):
                    recs = []
            self._cache = (key, recs)
            return recs

    def _save(self, recs: list[dict]) -> None:
        os.makedirs(self.dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".projects-", suffix=".tmp", dir=self.dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for r in recs:
                    f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        try:
            dfd = os.open(self.dir, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
        self._cache = (None, [])

    def _locked(self):
        """The threading lock plus a file lock, so two portal processes never interleave writes."""
        outer = self

        class _L:
            def __enter__(self):
                outer.lock.acquire()
                self.fh = None
                if fcntl is not None:
                    try:
                        os.makedirs(outer.dir, exist_ok=True)
                        self.fh = open(os.path.join(outer.dir, ".projects.lock"), "a")
                        fcntl.flock(self.fh, fcntl.LOCK_EX)
                    except OSError:
                        self.fh = None
                return self

            def __exit__(self, *a):
                if self.fh is not None:
                    try:
                        fcntl.flock(self.fh, fcntl.LOCK_UN)
                    finally:
                        self.fh.close()
                outer.lock.release()
        return _L()

    # -------------------------------------------------- reads
    def visible(self) -> list[dict]:
        return [r for r in self.load() if not r.get("hidden")]

    def get(self, pid: str) -> dict | None:
        if not isinstance(pid, str) or not PID_RE.fullmatch(pid):
            return None
        for r in self.load():
            if r["id"] == pid:
                return r
        return None

    # -------------------------------------------------- writes
    def submit(self, me, form: dict) -> tuple[bool, object]:
        """(True, record) or (False, message for the submitter). me is the /api/me answer."""
        who = account_of(me)
        if not who:
            return False, "Sign in to add a link."
        if not self.writable():
            return False, "Adding links is closed right now. Please try again later."
        try:
            link = normalize_url(form.get("url", ""))
        except ValueError as e:
            return False, str(e)
        category = form.get("category", "")
        if category not in self.category_ids():
            return False, "Pick a category."
        build = form.get("builds", "")
        if build not in BUILDS:
            return False, "Pick the client builds it works with."
        raw_desc = form.get("description", "") if isinstance(form.get("description"), str) else ""
        if "\n" in raw_desc.strip() or "\r" in raw_desc.strip():
            return False, "Keep the description to one line."
        desc = clean_text(raw_desc, 10_000)
        if len(desc) < MIN_DESC:
            return False, f"Write a one-line description (at least {MIN_DESC} characters)."
        if len(desc) > MAX_DESC:
            return False, f"Keep the description to {MAX_DESC} characters."
        if re.search(r"(?i)https?://|www\.", desc):
            return False, "Put the link in the link box, not in the description."
        if BRAND_RE.search(desc):
            return False, "Describe it without the game's brand names (say \"the game\" or \"Wrath\")."
        now = self.now()
        with self._locked():
            recs = list(self.load())
            for r in recs:
                if r.get("key") == link["key"]:
                    return False, ("That project is already listed." if not r.get("hidden")
                                   else "That link was taken down and can't be added again.") + f"|{r['id']}"
            day = now - 86400
            mine = [r for r in recs if r.get("submitter") == who and _iso_time(r.get("submitted_at", "")) > day]
            if len(mine) >= self.per_day:
                return False, f"You can add {self.per_day} links a day. Please come back tomorrow."
            if sum(1 for r in recs if _iso_time(r.get("submitted_at", "")) > day) >= self.day_max:
                return False, "Lots of links came in today. Please try again tomorrow."
            if len(recs) >= self.max_records:
                return False, "The list is full right now. Please try again later."
        meta = self.meta.fetch(link["forge"], link["owner"], link["repo"]) if link["forge"] else None
        if meta == "missing" or (isinstance(meta, dict) and meta.get("private")):
            return False, "We couldn't find a public repo at that link. Is it public, and spelled right?"
        meta = meta if isinstance(meta, dict) else {}
        tail = link["url"][len("https://" + link["host"]):].strip("/")
        fallback_title = link["repo"] or (tail.rsplit("/", 1)[-1] if tail else link["host"])
        rec = {
            "id": hashlib.sha256(link["key"].encode()).hexdigest()[:12],
            "key": link["key"], "url": link["url"], "host": link["host"], "forge": link["forge"],
            "title": meta.get("title") or scrub(clean_text(urllib.parse.unquote(fallback_title), 80)) or link["host"],
            "author": meta.get("author") or scrub(clean_text(link["owner"].split("/")[0], 60)) or scrub(link["host"]),
            "author_url": meta.get("author_url") or (f"https://{link['host']}/{link['owner'].split('/')[0]}"
                                                     if link["owner"] else ""),
            "licence": meta.get("licence", ""), "stars": meta.get("stars"), "last_push": meta.get("last_push", ""),
            "repo_description": meta.get("description", ""),
            "description": desc, "category": category, "builds": BUILDS[build],
            "submitted_by": display_of(me), "submitter": who, "submitted_at": _now_iso(now),
            "last_checked": _now_iso(now) if meta else "", "reports": [], "hidden": False,
        }
        with self._locked():
            recs = list(self.load())
            if any(r.get("key") == rec["key"] for r in recs):
                return False, "That project is already listed.|" + rec["id"]
            recs.append(rec)
            self._save(recs)
        log.info("community project added: %s (%s)", rec["id"], rec["host"])
        return True, rec

    def report(self, pid: str, me) -> tuple[bool, str]:
        who = account_of(me)
        if not who:
            return False, "Sign in to report a link."
        now = self.now()
        with self._locked():
            recent = [t for t in self._report_log.get(who, []) if t > now - 86400]
            if len(recent) >= self.reports_per_day:
                return False, "You've sent a lot of reports today. Thank you; please come back tomorrow."
            recs = list(self.load())
            for r in recs:
                if r["id"] == pid and not r.get("hidden"):
                    reps = r.get("reports") if isinstance(r.get("reports"), list) else []
                    if who not in reps:
                        r["reports"] = (reps + [who])[-200:]
                        self._save(recs)
                    self._report_log[who] = recent + [now]
                    log.info("community project reported: %s (%d reports)", pid, len(r["reports"]))
                    return True, "Thanks: the admins will take a look."
        return False, "That link isn't listed."

    def set_hidden(self, pid: str, me, hidden: bool, staff: bool = False) -> tuple[bool, str]:
        """staff=True: the Admin Console (stream/admin.py) already checked the caller's role."""
        if not staff and not self.is_admin(me):
            return False, "Only the Workshop's admins can do that."
        with self._locked():
            recs = list(self.load())
            for r in recs:
                if r["id"] == pid:
                    r["hidden"] = bool(hidden)
                    r["hidden_by"] = account_of(me) if hidden else ""
                    r["hidden_at"] = _now_iso(self.now()) if hidden else ""
                    if not hidden:
                        r["reports"] = []
                    self._save(recs)
                    log.info("community project %s: %s", "hidden" if hidden else "shown again", pid)
                    return True, "Hidden." if hidden else "Shown again."
        return False, "That link isn't listed."

    def clear_reports(self, pid: str) -> tuple[bool, str]:
        """The Admin Console's "dismiss reports": the link stays listed, its report list is emptied."""
        with self._locked():
            recs = list(self.load())
            for r in recs:
                if r["id"] == pid:
                    r["reports"] = []
                    self._save(recs)
                    return True, "Reports dismissed."
        return False, "That link isn't listed."

    def refresh_stale(self, limit: int = 10, age: float = 86400) -> int:
        """Ask the forges again for the oldest records not checked within `age` seconds. Returns how many."""
        now = self.now()
        stale = sorted((r for r in self.visible() if r.get("forge") and _iso_time(r.get("last_checked", "")) < now - age),
                       key=lambda r: r.get("last_checked", ""))[:limit]
        done = 0
        for r in stale:
            parts = r["url"].split("/")[3:]
            meta = self.meta.fetch(r["forge"], "/".join(parts[:-1]), parts[-1])
            if not isinstance(meta, dict):
                continue
            with self._locked():
                recs = list(self.load())
                for x in recs:
                    if x["id"] == r["id"]:
                        for k in ("title", "author", "author_url", "licence"):
                            if meta.get(k):
                                x[k] = meta[k]
                        x["stars"], x["last_push"] = meta.get("stars"), meta.get("last_push", "")
                        x["repo_description"] = meta.get("description", "")
                        x["last_checked"] = _now_iso(now)
                        self._save(recs)
                        done += 1
                        break
        return done

    def maybe_refresh(self, every: float = 3600) -> None:
        """At most once an hour, refresh a few stale records on a background thread (never slows a page)."""
        now = time.time()
        with self.lock:
            if now < self._sweep_at:
                return
            self._sweep_at = now + every
        if not self.writable():
            return
        threading.Thread(target=self._sweep, daemon=True).start()

    def _sweep(self):
        try:
            self.refresh_stale()
        except Exception:   # noqa: BLE001: a background refresh never takes the portal down
            log.exception("project refresh failed")
