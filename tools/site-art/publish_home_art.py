#!/usr/bin/env python3
"""The launcher Home gallery's in-game screenshots: from the owner's folder to the website (never into the repo).

    py -3 tools\\site-art\\publish_home_art.py build [--src site-art\\home] [--out <folder>]
    py -3 tools\\site-art\\publish_home_art.py check [--src site-art\\home]

The owner drops PNG / JPG / WebP screenshots into site-art\\home\\ (in the workspace's top folder; gitignored, never shipped), each
named by the slide it is for:

    hangout.jpg   browser.jpg   host.jpg   den.jpg   news.jpg        (.png, .jpg or .webp; hangout-2.jpg ... more for
    mode-minigolf.jpg  mode-bumper-balls.jpg  mode-coin-dash.jpg      the same slide take turns, one a day; mode-<id>:
    street.jpg (a spare: published, not shown yet)                    the small tile)

Optional: site-art\\home\\captions.json, {"hangout": {"alt": "...", "credit": "..."}, "hangout-2": {...}}: the words
the launcher shows as plain text (alt for screen readers, credit in small type over the picture).

"build" makes each one at most 1600 px wide (never wider than it was), as WebP (quality 82) with no metadata (no EXIF,
no GPS, no colour profile), and writes home.json, the list the launcher reads, into --out (default: a fresh folder in
%TEMP%). "Publish home screenshots.bat" (the Autopilot step "homeart") then uploads that folder to the server's art
dir (/srv/wrath/portal/art/home, served at https://play.openvanilla.app/wrath/art/home/), keeping a backup of what was
there. "check" only says what it would do. Needs Pillow.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time

SLIDES = ("hangout", "news", "browser", "host", "den")       # the slides that show a screenshot (ui/home.js photo)
MODES = ("minigolf", "bumper-balls", "coin-dash", "community")
# spares: published and listed in home.json, but no slide shows them yet (a slide can take one up later without a new
# upload); "street" is a second Dalaran street shot
SPARES = ("street",)
# what each slide's picture should show, for the owner (and the default alt text)
WHAT = {
    "hangout": "Players together in Dalaran, the Hangout's meeting place",
    "news": "Something from the latest update, in game",
    "browser": "The game running in a browser tab",
    "host": "A player-hosted realm in play",
    "den": "A Den: a built-up room in edit mode, or friends in it",
    "street": "A street in Dalaran",
}
NAME = re.compile(r"^(?P<id>(?:mode-)?[a-z0-9][a-z0-9-]{0,30}?)(?:-(?P<n>[2-9]))?\.(?:png|jpe?g|webp)$", re.I)
MAX_W = 1600
TOO_BIG = 1_400_000      # the site refuses a screenshot over 1.5 MB (stream/wrath_portal.py HOME_ART_MAX)
TEXT_MAX = {"alt": 200, "credit": 120}

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def known(slide_id: str) -> bool:
    return slide_id in SLIDES or slide_id in SPARES or (slide_id.startswith("mode-") and slide_id[5:] in MODES)


def find(src: str):
    """[(slide id, out name, path)] for the pictures in src, in order; and the names it skips, with why."""
    out, skipped = [], []
    for f in sorted(os.listdir(src)) if os.path.isdir(src) else []:
        p = os.path.join(src, f)
        if not os.path.isfile(p) or f.lower() == "captions.json":
            continue
        m = NAME.match(f)
        if not m:
            skipped.append((f, "not a .png, .jpg or .webp named like hangout.png"))
            continue
        sid = m.group("id").lower()
        if not known(sid):
            skipped.append((f, f"no slide called {sid!r} (slides: {', '.join(SLIDES)}; tiles: mode-<id>)"))
            continue
        stem = sid + (f"-{m.group('n')}" if m.group("n") else "")
        if any(o[1] == stem + ".webp" for o in out):
            skipped.append((f, f"{stem} is there twice (two file types?)"))
            continue
        out.append((sid, stem + ".webp", p))
    return out, skipped


def captions(src: str) -> dict:
    p = os.path.join(src, "captions.json")
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8-sig") as f:
        j = json.load(f)
    if not isinstance(j, dict):
        raise SystemExit("captions.json must be {\"hangout\": {\"alt\": \"...\", \"credit\": \"...\"}}")
    return j


def clean(v, n):
    return re.sub(r"\s+", " ", v).strip()[:n] if isinstance(v, str) else ""


def convert(path: str, dest: str) -> tuple[int, int, int]:
    from PIL import Image   # only here: "check" works without Pillow
    with Image.open(path) as im:
        im.load()
        im = im.convert("RGB")        # drops alpha and palette; the profile and EXIF stay behind
        if im.width > MAX_W:
            im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
        q = 82
        while True:
            im.save(dest, "WEBP", quality=q, method=6)    # no exif=, icc_profile=: nothing but the pixels
            size = os.path.getsize(dest)
            if size <= TOO_BIG or q <= 50:
                return im.width, im.height, size
            q -= 8


def manifest(items, caps) -> dict:
    slides = {}
    for sid, name, _ in items:
        stem = name[:-5]
        c = caps.get(stem) or caps.get(sid) or {}
        c = c if isinstance(c, dict) else {}
        slides.setdefault(sid, []).append({"file": name, "alt": clean(c.get("alt"), TEXT_MAX["alt"]) or WHAT.get(sid, ""),
                                           "credit": clean(c.get("credit"), TEXT_MAX["credit"])})
    return {"version": 1, "updated": int(time.time()), "slides": slides}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["build", "check"])
    ap.add_argument("--src", default=os.path.join(ROOT, "site-art", "home"))
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    items, skipped = find(a.src)
    for f, why in skipped:
        print(f"  skipped {f}: {why}")
    if not items:
        print(f"No screenshots in {a.src}. Put hangout.jpg, browser.jpg, host.jpg, den.jpg, news.jpg there (.png works too).")
        return 1
    caps = captions(a.src)
    for sid in SLIDES:
        if not any(i[0] == sid for i in items):
            print(f"  no picture for {sid} ({WHAT[sid]}): that slide keeps its plain colour")
    if a.cmd == "check":
        for sid, name, p in items:
            print(f"  {os.path.basename(p)} -> {name}")
        return 0
    out = a.out or tempfile.mkdtemp(prefix="leyline-home-art-")
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):                     # a fresh set: what is uploaded is exactly this
        if f.endswith(".webp") or f == "home.json":
            os.remove(os.path.join(out, f))
    for sid, name, p in items:
        w, h, size = convert(p, os.path.join(out, name))
        print(f"  {os.path.basename(p)} -> {name} ({w}x{h}, {size // 1024} KB)")
    with open(os.path.join(out, "home.json"), "w", encoding="utf-8") as f:
        json.dump(manifest(items, caps), f, ensure_ascii=False, indent=1)
    print(f"OUT={out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
