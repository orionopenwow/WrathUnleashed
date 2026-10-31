#!/usr/bin/env python3
"""Leyline HQ's link to the owner's PC (the Autopilot steps hq-sync, hqnote and hq-inbox: "HQ sync.bat").

    py -3 tools\\hq\\hq_sync.py build OUTDIR        write OUTDIR\\changes.json and OUTDIR\\claude-notes.json
    py -3 tools\\hq\\hq_sync.py inbox NOTES.jsonl    turn the server's owner-notes.jsonl into control\\notes-from-owner.json

build: the last 30 Autopilot steps (UPDATES-PENDING.txt + UPDATES-DONE.txt + control/last-run.json; the time is the
log file's time) as {id, step, title, note, ok, at}: names and outcomes only, never a line of any log. The last
server check comes from control/last-check.json. Claude's notes come from control/hq-notes.json, which the main
Claude session writes:

    {"format": 1, "notes": [{"id": "n20261031a", "date": "2026-10-31", "title": "Leyline HQ is live",
                             "items": ["one plain line", "another"]}],
     "ack": ["o20261031120000ab12"]}          <- owner notes Claude has read (HQ shows them as "seen")

Newest first, at most 50 notes, 8 items each. A note that names the game's brand is refused (the owner reads these;
say "the game", "Wrath", "3.3.5a"), so the step fails and nothing is uploaded.

inbox: the owner's notes still open (not closed), newest first, for the main session to read:
    control/notes-from-owner.json  {"fetched_at", "notes": [{"id", "at", "text", "status"}]}
Standard library only.
"""
import ast
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("LEYLINE_ROOT") or Path(__file__).resolve().parents[2])
CONTROL = ROOT / "control"
BRAND_RE = re.compile(r"(?i)world\s*of\s*warcraft|warcraft|lich\s*king|blizzard|\bwow\b")
ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,48}$")
NOTE_ID_RE = re.compile(r"^o\d{14}[0-9a-f]{4}$")


def lines(p: Path) -> list[str]:
    try:
        return [x.strip() for x in p.read_text(encoding="utf-8-sig", errors="replace").splitlines()]
    except OSError:
        return []


def read_json(p: Path, default):
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        return d if isinstance(d, type(default)) else default
    except (OSError, ValueError):
        return default


def step_titles() -> dict:
    """STEPS from control.py's source (importing it would start nothing, but it writes a token file)."""
    try:
        tree = ast.parse((ROOT / "tools" / "control" / "control.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "STEPS" for t in node.targets):
                return {k: v[1] for k, v in ast.literal_eval(node.value).items()}
    except (OSError, SyntaxError, ValueError):
        pass
    return {}


def one_line(v, n: int) -> str:
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(v or "")).split())[:n]


def iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def changes(n: int = 30) -> dict:
    done = set(lines(ROOT / "UPDATES-DONE.txt"))
    last = read_json(CONTROL / "last-run.json", {})
    failed_ids = set(last.get("ids") or []) if last.get("ok") is False else set()
    titles = step_titles()
    steps = []
    for line in lines(ROOT / "UPDATES-PENDING.txt"):
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 2)
        if len(parts) < 2 or not ID_RE.fullmatch(parts[0]):
            continue
        sid, step = parts[0], parts[1].lower()
        note = parts[2] if len(parts) > 2 else ""
        log = ROOT / "logs" / f"{sid}-{step}.log"
        try:
            at = iso(log.stat().st_mtime)
        except OSError:
            at = ""
        ok = True if sid in done else False if sid in failed_ids else None
        steps.append({"id": sid, "step": one_line(step, 24), "title": one_line(titles.get(step, step), 100),
                      "note": one_line(note, 200), "ok": ok, "at": at})
    steps = steps[-n:][::-1]
    chk = read_json(CONTROL / "last-check.json", {})
    out = {"format": 1, "made_at": iso(time.time()), "steps": steps}
    if chk.get("at"):
        out["last_check"] = {"at": one_line(chk.get("at"), 25), "ok": chk.get("ok") is True, "id": one_line(chk.get("id"), 48)}
    return out


class Bad(Exception):
    pass


def claude_notes() -> dict:
    doc = read_json(CONTROL / "hq-notes.json", {})
    notes = []
    for nt in (doc.get("notes") if isinstance(doc.get("notes"), list) else [])[:50]:
        if not isinstance(nt, dict):
            continue
        nid = str(nt.get("id", ""))
        if not ID_RE.fullmatch(nid):
            raise Bad(f"note id {nid!r}: letters, digits, . _ - only (up to 48)")
        title = one_line(nt.get("title"), 120)
        items = [one_line(x, 300) for x in (nt.get("items") if isinstance(nt.get("items"), list) else [])][:8]
        for text in [title] + items:
            if BRAND_RE.search(text):
                raise Bad(f"note {nid}: the owner reads these; leave out the game-brand names ({text[:60]!r})")
        if not title:
            raise Bad(f"note {nid}: no title")
        notes.append({"id": nid, "date": one_line(nt.get("date"), 25), "title": title, "items": [x for x in items if x]})
    ack = [str(x) for x in (doc.get("ack") if isinstance(doc.get("ack"), list) else []) if NOTE_ID_RE.fullmatch(str(x))][:500]
    return {"format": 1, "updated_at": iso(time.time()), "notes": notes, "ack": ack}


def build(outdir: str) -> int:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        cn = claude_notes()
    except Bad as e:
        print(f"!! control/hq-notes.json: {e}. Nothing was uploaded.")
        return 1
    ch = changes()
    (out / "changes.json").write_text(json.dumps(ch, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "claude-notes.json").write_text(json.dumps(cn, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"HQ: {len(ch['steps'])} recent steps, {len(cn['notes'])} notes from Claude, {len(cn['ack'])} owner notes marked seen.")
    return 0


def inbox(path: str) -> int:
    notes, status = {}, {}
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        raw = ""
    for line in raw.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict) or not NOTE_ID_RE.fullmatch(str(r.get("id", ""))):
            continue
        if "text" in r:
            notes[r["id"]] = {"id": r["id"], "at": one_line(r.get("at"), 25), "text": str(r.get("text") or "")[:2000]}
        elif r.get("status") in ("open", "closed"):
            status[r["id"]] = r["status"]
    ack = set(read_json(CONTROL / "hq-notes.json", {}).get("ack") or [])
    keep = [dict(n, status="seen" if n["id"] in ack else "new") for n in notes.values() if status.get(n["id"]) != "closed"]
    keep.sort(key=lambda n: n["at"], reverse=True)
    CONTROL.mkdir(exist_ok=True)
    doc = {"fetched_at": iso(time.time()), "notes": keep,
           "how": "Notes the owner left on Leyline HQ (Note to Claude). Read them, then add their ids to \"ack\" in "
                  "control/hq-notes.json and queue the hqnote step so HQ shows them as seen."}
    tmp = CONTROL / "notes-from-owner.json.tmp"
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, CONTROL / "notes-from-owner.json")
    new = sum(1 for n in keep if n["status"] == "new")
    print(f"HQ: {len(keep)} open notes from the owner ({new} new) in control/notes-from-owner.json.")
    return 0


def main(argv) -> int:
    if len(argv) == 3 and argv[1] == "build":
        return build(argv[2])
    if len(argv) == 3 and argv[1] == "inbox":
        return inbox(argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
