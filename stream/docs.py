"""The Leyline documentation on the Wrath portal (stream/wrath_portal.py), in the Leyline look.

    GET /wrath/docs             the overview (docs/leyline/index.md)
    GET /wrath/docs/<page>      one page; <page> is one of PAGES below, anything else is a 404

The pages are Markdown files in docs/leyline/ (in the repo) or in docs/leyline/ beside this file (on the
server: $WU/portal/docs/leyline, which wu-portal sees as /app/docs/leyline; fastloop.sh installs them).
The portal sends each page through its site_chrome(), which puts in the site's one nav (with its Docs item) and
footer in place of the small nav here.
WU_DOCS_DIR overrides both.

The renderer is small and safe on purpose. It knows headings, paragraphs, lists, tables, fenced code,
block quotes, inline code, bold and links. Every character from a file is HTML-escaped: raw HTML in a file
shows as text, never as markup. Links go only to https:// pages, to /wrath/ paths, to #anchors, or to
another page of the fixed list (written "hosting.md" or "hosting.md#the-relay"); any other link shows its
text without a link. The page list is fixed: a file that isn't in PAGES is never read or served.

Standard library only. The portal loads this file from beside itself and runs without it (the routes then
answer 404). Nothing here raises to the caller.
"""
from __future__ import annotations

import html
import os
import re
import threading

# The fixed, allow-listed pages: (name, title in the table of contents). The order is the contents' order.
PAGES = (
    ("index", "Overview"),
    ("play", "Play"),
    ("commands", "Commands"),
    ("mods", "Mod format"),
    ("publishing", "Publishing"),
    ("hosting", "Hosting"),
    ("launcher", "Launcher"),
    ("hero-key", "Hero Key"),
    ("cross-server", "Other servers"),
    ("unite", "Working together"),
)
TITLES = dict(PAGES)
BASE = "/wrath/docs"
MAX_BYTES = 256 * 1024      # a page file larger than this is not served
HERE = os.path.dirname(os.path.abspath(__file__))


def docs_dir() -> str:
    """Where the Markdown files are: WU_DOCS_DIR, else docs/leyline beside this file, else the repo's."""
    env = os.environ.get("WU_DOCS_DIR", "").strip()
    if env:
        return env
    for d in (os.path.join(HERE, "docs", "leyline"), os.path.join(HERE, "..", "docs", "leyline")):
        if os.path.isfile(os.path.join(d, "index.md")):
            return d
    return os.path.join(HERE, "docs", "leyline")


def page_url(name: str) -> str:
    return BASE if name == "index" else f"{BASE}/{name}"


def match(path: str) -> bool:
    return path == BASE or path.startswith(BASE + "/")


# ------------------------------------------------------------------------------------------- Markdown
def slug(text: str) -> str:
    """A heading's anchor id: "The relay" -> "the-relay"."""
    s = re.sub(r"[^a-z0-9 -]", "", text.lower().replace("`", ""))
    s = re.sub(r"[\s-]+", "-", s).strip("-")
    return s or "section"


_SAFE_HTTPS = re.compile(r"^https://[A-Za-z0-9.-]+(?:/[A-Za-z0-9._~:/?#\[\]@!$&*+,;=%-]*)?$")
_SAFE_LOCAL = re.compile(r"^/wrath(?:/[A-Za-z0-9._~/?=&#%-]*)?$")
_ANCHOR = re.compile(r"^#[a-z0-9-]+$")
_PAGE_LINK = re.compile(r"^([a-z0-9-]+)\.md(?:#([a-z0-9-]+))?$")


def resolve(url: str) -> str | None:
    """The href for a link written in a page, or None when it is not allowed (the text shows unlinked)."""
    if _SAFE_HTTPS.match(url) or _SAFE_LOCAL.match(url) or _ANCHOR.match(url):
        return url
    m = _PAGE_LINK.match(url)
    if m and m.group(1) in TITLES:
        return page_url(m.group(1)) + (f"#{m.group(2)}" if m.group(2) else "")
    return None


_INLINE = re.compile(r"`([^`]+)`|\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)\s]+)\)")


def inline(text: str, links: bool = True) -> str:
    """One line of Markdown text as safe HTML: `code`, **bold**, [text](link); everything else escaped."""
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        if m.group(3) is not None and not links:
            continue
        out.append(html.escape(text[pos:m.start()]))
        if m.group(1) is not None:
            out.append(f"<code>{html.escape(m.group(1))}</code>")
        elif m.group(2) is not None:
            out.append(f"<strong>{inline(m.group(2), links)}</strong>")
        else:
            href = resolve(m.group(4))
            label = inline(m.group(3), links=False)
            if href is None:
                out.append(label)
            else:
                ext = href.startswith("https://")
                out.append(f'<a href="{html.escape(href, quote=True)}"'
                           + (' rel="noopener noreferrer"' if ext else "") + f">{label}</a>")
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


_HEAD = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")
_ITEM = re.compile(r"^\s*([-*]|\d+\.)\s+(.*)$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def render_markdown(text: str) -> tuple[str, list[tuple[int, str, str]]]:
    """(the HTML, the headings as (level, id, text)). Headings get unique ids for anchors."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    heads: list[tuple[int, str, str]] = []
    used: dict[str, int] = {}
    para: list[str] = []
    i = 0

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            flush()
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
            continue
        if not s:
            flush()
            i += 1
            continue
        m = _HEAD.match(s)
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2)
            base = slug(title)
            n = used.get(base, 0)
            used[base] = n + 1
            hid = base if n == 0 else f"{base}-{n + 1}"
            heads.append((level, hid, title))
            out.append(f'<h{level} id="{hid}">{inline(title, links=False)}</h{level}>')
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,})$", s):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1].strip()):
            flush()
            head = _cells(s)
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            th = "".join(f"<th>{inline(c)}</th>" for c in head)
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r[:len(head)])
                           + "<td></td>" * max(0, len(head) - len(r)) + "</tr>" for r in rows)
            out.append(f'<div class="ld-scroll"><table class="ld-table"><thead><tr>{th}</tr></thead>'
                       f"<tbody>{body}</tbody></table></div>")
            continue
        if s.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append(f"<blockquote><p>{inline(' '.join(q for q in quote if q))}</p></blockquote>")
            continue
        m = _ITEM.match(line)
        if m:
            flush()
            ordered = m.group(1)[0].isdigit()
            items: list[str] = []
            while i < len(lines):
                m2 = _ITEM.match(lines[i])
                if m2 and m2.group(1)[0].isdigit() == ordered:
                    items.append(m2.group(2))
                elif items and lines[i].startswith((" ", "\t")) and lines[i].strip() and not _ITEM.match(lines[i]):
                    items[-1] += " " + lines[i].strip()       # a wrapped item line
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(t)}</li>" for t in items) + f"</{tag}>")
            continue
        para.append(s)
        i += 1
    flush()
    return "".join(out), heads


def links_in(text: str) -> list[str]:
    """Every link target written in a page's Markdown (outside code blocks and code spans)."""
    found, fenced = [], False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        for m in _INLINE.finditer(line):
            if m.group(4) is not None:
                found.append(m.group(4))
    return found


# ------------------------------------------------------------------------------------------- pages
_cache: dict[str, tuple[float, str, list]] = {}
_lock = threading.Lock()


def load(name: str) -> tuple[str, list] | None:
    """(HTML, headings) for an allow-listed page, cached until its file changes; None when it is missing."""
    if name not in TITLES:
        return None
    path = os.path.join(docs_dir(), name + ".md")
    try:
        st = os.stat(path)
        if st.st_size > MAX_BYTES:
            return None
        with _lock:
            got = _cache.get(path)
            if got and got[0] == st.st_mtime:
                return got[1], got[2]
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(MAX_BYTES)
        body, heads = render_markdown(text)
        with _lock:
            _cache[path] = (st.st_mtime, body, heads)
        return body, heads
    except OSError:
        return None


DOCS_CSS = """
.ld-wrap{display:grid;grid-template-columns:230px minmax(0,1fr);gap:22px;align-items:start}
@media (max-width:860px){.ld-wrap{grid-template-columns:minmax(0,1fr)}}
.ld-toc{position:sticky;top:64px;background:rgba(10,12,34,.82);border:1px solid var(--ly-line);border-radius:8px;padding:14px 12px;margin:18px 0}
@media (max-width:860px){.ld-toc{position:static;margin:12px 0 0}}
.ld-toc p{margin:0 0 8px;font:600 11px/1 system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:var(--ly-dim)}
.ld-toc ol{list-style:none;margin:0;padding:0}
.ld-toc li{margin:2px 0}
.ld-toc a{display:block;padding:5px 8px;border-radius:4px;color:var(--ly-ink);text-decoration:none;font-size:15px}
.ld-toc a:hover,.ld-toc a:focus-visible{background:rgba(40,52,110,.6);color:#fff}
.ld-toc a[aria-current]{background:rgba(40,52,110,.9);color:var(--ly-cyan);box-shadow:inset 2px 0 0 var(--ly-cyan)}
.ld-toc ol ol{margin:2px 0 6px 10px;border-left:1px solid var(--ly-line)}
.ld-toc ol ol a{font-size:13px;color:var(--ly-dim);padding:3px 8px}
.ld-doc{min-width:0;padding:26px 26px 30px}
@media (max-width:560px){.ld-doc{padding:20px 16px}}
.ld-doc h1{font-size:clamp(34px,6vw,52px);text-align:left;margin:0 0 16px}
.ld-doc h2{text-align:left;font-size:24px;margin:30px 0 10px}
.ld-doc h2::after{margin:6px 0 0;width:min(240px,60%)}
.ld-doc h3{font:600 19px/1.2 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--ly-cyan);margin:22px 0 8px}
.ld-doc h4{font-size:16px;color:var(--ly-violet);margin:18px 0 6px}
.ld-doc p,.ld-doc li{max-width:72ch}
.ld-doc ul,.ld-doc ol{padding-left:1.4rem}
.ld-doc li{margin:5px 0}
.ld-doc code{background:rgba(5,6,18,.85);border:1px solid var(--ly-line);border-radius:4px;padding:1px 5px;font:14px ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}
.ld-doc pre{background:rgba(5,6,18,.9);border:1px solid var(--ly-line);border-radius:6px;padding:12px 14px;overflow-x:auto;max-width:100%}
.ld-doc pre code{background:none;border:0;padding:0;overflow-wrap:normal;white-space:pre}
.ld-doc blockquote{margin:14px 0;padding:10px 14px;border-left:3px solid var(--ly-violet);background:rgba(60,30,110,.25);border-radius:0 6px 6px 0}
.ld-doc blockquote p{margin:0}
.ld-doc strong{color:#fff}
.ld-doc hr{border:0;border-top:1px solid var(--ly-line);margin:24px 0}
.ld-scroll{overflow-x:auto;margin:12px 0;max-width:100%}
.ld-table{width:100%;border-collapse:collapse;font-size:15px}
.ld-table th{font:600 11px/1.2 system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--ly-dim);text-align:left;padding:9px 10px;border-bottom:1px solid var(--ly-line);white-space:nowrap}
.ld-table td{padding:9px 10px;border-bottom:1px solid rgba(120,150,255,.12);vertical-align:top}
.ld-foot{color:var(--ly-dim);font-size:14px;margin-top:26px}
"""


def _nav() -> str:
    """A stand-in nav for this page on its own; the portal swaps it for the site's nav and footer (site_chrome)."""
    return ('<nav class="ly-nav" aria-label="Leyline"><div class="grp">'
            '<a href="/wrath/leyline">Hub</a><a href="/wrath/modes">Modes</a><a href="/wrath/realms">Realms</a>'
            '<a href="/wrath/mods">Mods</a><a href="/wrath/docs">Docs</a></div>'
            '<div class="grp"><a href="/login?next=%2Fwrath">Sign in</a><a class="hot" href="/wrath">Play now</a></div></nav>')


def _toc(current: str, heads: list) -> str:
    items = []
    for name, title in PAGES:
        cur = ' aria-current="page"' if name == current else ""
        sub = ""
        if name == current:
            subs = [f'<li><a href="#{hid}">{inline(t, links=False)}</a></li>' for lvl, hid, t in heads if lvl == 2]
            sub = f"<ol>{''.join(subs)}</ol>" if subs else ""
        items.append(f'<li><a href="{page_url(name)}"{cur}>{html.escape(title)}</a>{sub}</li>')
    return (f'<aside class="ld-toc"><nav aria-label="Documentation"><p>Leyline docs</p>'
            f'<ol>{"".join(items)}</ol></nav></aside>')


def _shell(title: str, current: str, heads: list, body: str, css: str, meta: str) -> bytes:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">'
            f'<title>{html.escape(title)} · Leyline docs</title>{meta}<style>{css}{DOCS_CSS}</style></head>'
            f'<body class="ly"><div class="ly-glow"></div>{_nav()}'
            f'<div class="ly-wrap"><div class="ld-wrap">{_toc(current, heads)}'
            f'<article class="ly-panel ld-doc">{body}</article></div></div></body></html>').encode("utf-8")


def not_found(css: str = "") -> bytes:
    links = "".join(f'<li><a href="{page_url(n)}">{html.escape(t)}</a></li>' for n, t in PAGES)
    body = ("<h1>Not found</h1><p>There is no docs page with that name. These are the pages:</p>"
            f"<ul>{links}</ul>")
    return _shell("Not found", "", [], body, css, "")


def page(path: str, css: str = "", card_meta=None, realm_name: str = "WrathUnleashed") -> tuple[int, bytes]:
    """(status, HTML) for GET /wrath/docs and /wrath/docs/<page>. Never raises."""
    try:
        name = "index" if path == BASE else path[len(BASE) + 1:]
        if name not in TITLES:
            return 404, not_found(css)
        got = load(name)
        if got is None:
            return 404, not_found(css)
        body, heads = got
        title = TITLES[name] if name != "index" else "Leyline"
        meta = ""
        if card_meta is not None:
            try:
                meta = card_meta(page_url(name), f"{title} · Leyline docs")
            except Exception:  # noqa: BLE001: the page works without a preview card
                meta = ""
        foot = ('<p class="ld-foot">These pages are in the repo at docs/leyline. '
                '<a href="https://github.com/orionopenwow/WrathUnleashed/tree/main/docs/leyline" '
                'rel="noopener noreferrer">Source</a></p>')
        return 200, _shell(title, name, heads, body + foot, css, meta)
    except Exception:  # noqa: BLE001: never take the portal down
        return 404, b"not found\n"
