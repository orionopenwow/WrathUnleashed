#!/usr/bin/env python3
"""Lay the catalog mods' addons (mods/catalog/<id>/ui/<Name>/) over a streamed slice. The sibling of
fui-overlay.py, run by mods-install.sh on the server (python3 -I, standard library only):

  mods-overlay.py build         <catalog.json> <catalog dir> <generated addons dir> <out>
                                     the overlay in game-path layout: Interface/AddOns/<Name>/...
  mods-overlay.py digest        <overlay>            one hash of every file (to skip a needless wu-play restart)
  mods-overlay.py apply-slice   <overlay> <slice>    (re)lay it over a slice folder
  mods-overlay.py unapply-slice <slice>              take it off again, exactly
  mods-overlay.py brand-toc     <overlay> on|off     the Leyline brand switch: our addons' .toc Title/Notes/Author
  mods-overlay.py apply-www     <slice> <www>        its files into the client's boot-manifest.json
  mods-overlay.py unapply-www   <www>
  mods-overlay.py status        <slice> [<www>]

Only Interface/AddOns/<Name>/ folders are taken, never ForeverUI or WrathUnleashedUI (those are
fui-overlay.py's). Files the slice does not have are hard-linked in; a file the slice already has is
left alone (and reported). What was added is recorded in <slice>/.overlay-mods/ (a dot folder:
wenilla-host neither lists nor serves it), so unapply is exact and apply is idempotent. The slice's
tier lists are not touched (fui-overlay.py restores them from its own backup); the addons are small
text files, listed in boot-manifest.json under "mods_overlay" so the client has them at start.
"""
import hashlib
import json
import os
import re
import shutil
import sys

STATE = ".overlay-mods"
WWW_KEY = "mods_overlay"
RESERVED = {"foreverui", "wrathunleashedui"}
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


def die(msg):
    print(f"mods-overlay: {msg}", file=sys.stderr)
    sys.exit(1)


def taken(parts):
    low = [p.lower() for p in parts]
    return (len(low) >= 4 and low[0] == "interface" and low[1] == "addons" and low[2] not in RESERVED
            and NAME_RE.match(parts[2]) is not None and not any(p.startswith(".") or not p for p in low))


def overlay_files(root):
    out = []
    for d, dirs, files in os.walk(root):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(d, f)
            parts = tuple(os.path.relpath(p, root).split(os.sep))
            if taken(parts) and os.path.isfile(p) and not os.path.islink(p):
                out.append((parts, p))
    return out


def child(d, name):
    """`d/name`, matched case-insensitively like wenilla-host's lookup; None when absent."""
    direct = os.path.join(d, name)
    if os.path.lexists(direct):
        return direct
    try:
        for e in os.listdir(d):
            if e.lower() == name.lower():
                return os.path.join(d, e)
    except FileNotFoundError:
        pass
    return None


def chain_name(slice_dir, path):
    return os.path.relpath(path, slice_dir).replace(os.sep, "\\")


def write_atomic(path, data, like=None):
    tmp = path + ".mods-tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.chmod(tmp, (os.stat(like).st_mode & 0o7777) if like and os.path.exists(like) else 0o644)
    os.replace(tmp, path)


def build(catalog_json, catalog_dir, gen_dir, out):
    """The overlay from the checked catalog: each mod's ui/<Name>/ plus the generated WUModCatalog."""
    cat = json.load(open(catalog_json, encoding="utf-8"))
    if os.path.exists(out):
        shutil.rmtree(out)
    addons = os.path.join(out, "Interface", "AddOns")
    os.makedirs(addons)
    n = 0
    for m in cat.get("mods", []):
        for name in m.get("addons", []):
            if not NAME_RE.match(name) or name.lower() in RESERVED:
                die(f"{m.get('id')}: addon folder {name!r} is not allowed")
            src = os.path.join(catalog_dir, m["id"], "ui", name)
            if not os.path.isdir(src):
                die(f"{m['id']}: ui/{name}/ is missing")
            shutil.copytree(src, os.path.join(addons, name))
            n += 1
    if gen_dir and os.path.isdir(gen_dir):
        for name in sorted(os.listdir(gen_dir)):
            if NAME_RE.match(name) and os.path.isdir(os.path.join(gen_dir, name)):
                shutil.copytree(os.path.join(gen_dir, name), os.path.join(addons, name))
                n += 1
    for d, _, files in os.walk(out):
        os.chmod(d, 0o755)
        for f in files:
            p = os.path.join(d, f)
            if f.lower().endswith((".lua", ".toc", ".xml")):   # uploaded from Windows: LF like the rest
                b = open(p, "rb").read()
                if b"\r\n" in b:
                    open(p, "wb").write(b.replace(b"\r\n", b"\n"))
            os.chmod(p, 0o644)
    print(f"  overlay: {n} addon folder(s) in {out}")


def digest(overlay):
    h = hashlib.sha256()
    if os.path.isdir(overlay):
        for parts, p in overlay_files(overlay):
            h.update("/".join(parts).encode("utf-8") + b"\0")
            h.update(hashlib.sha256(open(p, "rb").read()).digest())
    return h.hexdigest()


# The Leyline brand switch (realm/brand.sh; fui-install.sh / mods-install.sh brand on|off): the addon list's
# Title, Notes and Author lines of our own two addons, swapped both ways. Folder names, saved variables and every
# other line stay. Only these .toc files are touched (folder name, lower case).
BRAND_TOCS = {"wrathunleashedui": "WrathUnleashedUI.toc", "wumodcatalog": "WUModCatalog.toc"}
BRAND_SWAPS = [("## Title: WrathUnleashed UI", "## Title: Leyline UI"),
               ("## Notes: WrathUnleashed's ", "## Notes: Leyline's "),
               ("## Title: Mod list (WrathUnleashed)", "## Title: Mod list (Leyline)"),
               ("## Author: WrathUnleashed", "## Author: Leyline")]


def brand_toc_text(text: str, on: bool) -> str:
    out = []
    for line in text.split("\n"):
        cr = "\r" if line.endswith("\r") else ""
        body = line[:-1] if cr else line
        for old, new in BRAND_SWAPS:
            a, b = (old, new) if on else (new, old)
            if body == a or (a.endswith(" ") and body.startswith(a)):   # a whole line, or a prefix ending in a space
                body = b + body[len(a):]
                break
        out.append(body + cr)
    return "\n".join(out)


def brand_toc(overlay, mode):
    """Rewrites our addons' .toc header lines in the overlay (a new file each, so the slices keep the old one until
    apply-slice lays the overlay again). Prints what changed; 0 files is fine (the addon is not in this overlay)."""
    if mode not in ("on", "off"):
        die("brand-toc: on or off")
    n = 0
    for d, _, files in os.walk(overlay):
        folder = os.path.basename(d).lower()
        want = BRAND_TOCS.get(folder)
        if not want:
            continue
        for f in files:
            if f.lower() != want.lower():
                continue
            p = os.path.join(d, f)
            text = open(p, "rb").read().decode("utf-8", "replace")
            new = brand_toc_text(text, mode == "on")
            if new != text:
                write_atomic(p, new.encode("utf-8"), like=p)
                n += 1
                print(f"  {os.path.relpath(p, overlay)}: the {'Leyline' if mode == 'on' else 'old'} names")
    print(f"  brand {mode}: {n} addon list entr{'y' if n == 1 else 'ies'} changed")
    return n


def state_dir(slice_dir):
    return os.path.join(slice_dir, STATE)


def unapply_slice(slice_dir, quiet=False):
    st = state_dir(slice_dir)
    if not os.path.isdir(st):
        return 0
    removed = 0
    added = os.path.join(st, "added.txt")
    if os.path.exists(added):
        for rel in open(added, encoding="utf-8").read().splitlines():
            if not rel:
                continue
            p = os.path.join(slice_dir, *rel.split("\\"))
            if os.path.lexists(p):
                os.unlink(p)
                removed += 1
    dirs = os.path.join(st, "dirs.txt")
    if os.path.exists(dirs):
        for rel in sorted(open(dirs, encoding="utf-8").read().splitlines(), key=len, reverse=True):
            p = os.path.join(slice_dir, *rel.split("\\")) if rel else None
            if p and os.path.isdir(p) and not os.listdir(p):
                os.rmdir(p)
    shutil.rmtree(st)
    if not quiet:
        print(f"  mods taken off {slice_dir}: {removed} files")
    return removed


def apply_slice(overlay, slice_dir):
    if not os.path.isdir(slice_dir):
        die(f"no slice folder {slice_dir}")
    files = overlay_files(overlay)
    unapply_slice(slice_dir, quiet=True)
    st = state_dir(slice_dir)
    os.makedirs(st)
    added, made_dirs, kept = [], [], []
    for parts, src in files:
        d = slice_dir
        for comp in parts[:-1]:
            nxt = child(d, comp)
            if nxt is None:
                nxt = os.path.join(d, comp)
                os.mkdir(nxt)
                os.chmod(nxt, 0o755)
                made_dirs.append(chain_name(slice_dir, nxt))
            elif not os.path.isdir(nxt):
                die(f"{nxt} is a file where the overlay needs a folder")
            d = nxt
        if child(d, parts[-1]) is not None:
            kept.append("\\".join(parts))
            continue
        dst = os.path.join(d, parts[-1])
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
        os.chmod(dst, 0o644)
        added.append(chain_name(slice_dir, dst))
    with open(os.path.join(st, "added.txt"), "w", encoding="utf-8") as f:
        f.write("".join(n + "\n" for n in added))
    with open(os.path.join(st, "dirs.txt"), "w", encoding="utf-8") as f:
        f.write("".join(n + "\n" for n in made_dirs))
    addons = sorted({p[2] for p, _ in files})
    print(f"  mods laid over {slice_dir}: {len(added)} files ({', '.join(addons) or 'no addons'})"
          + (f"; {len(kept)} kept the slice's own copy: {', '.join(kept[:3])}" if kept else ""))
    return len(added)


def store_key(n):
    return n.replace("/", "\\").lower()


def unapply_www(www, quiet=False):
    bm = os.path.join(www, "boot-manifest.json")
    if not os.path.isfile(bm):
        return
    m = json.load(open(bm, encoding="utf-8"))
    ours = m.pop(WWW_KEY, None)
    if ours is None:
        return
    drop = {store_key(n) for n in ours}
    m["names"] = [n for n in m.get("names", []) if store_key(n) not in drop]
    write_atomic(bm, json.dumps(m, indent=1).encode("utf-8"), like=bm)
    for ext in (".br", ".gz"):
        if os.path.exists(bm + ext):
            os.unlink(bm + ext)
    if not quiet:
        print(f"  boot-manifest.json: {len(drop)} mod files taken out")


def apply_www(slice_dir, www):
    bm = os.path.join(www, "boot-manifest.json")
    if not os.path.isfile(bm):
        print("  no boot-manifest.json in the client build: the mods' files load on demand")
        return
    added_txt = os.path.join(state_dir(slice_dir), "added.txt")
    unapply_www(www, quiet=True)
    if not os.path.isfile(added_txt):
        return
    m = json.load(open(bm, encoding="utf-8"))
    names = [n for n in open(added_txt, encoding="utf-8").read().splitlines() if n]
    have = {store_key(n) for n in m.get("names", [])}
    ours = [n for n in names if store_key(n) not in have]
    m["names"] = list(m.get("names", [])) + ours
    m[WWW_KEY] = ours
    write_atomic(bm, json.dumps(m, indent=1).encode("utf-8"), like=bm)
    for ext in (".br", ".gz"):
        if os.path.exists(bm + ext):
            os.unlink(bm + ext)
    print(f"  boot-manifest.json: +{len(ours)} mod files")


def status(slice_dir, www=None):
    st = state_dir(slice_dir)
    if os.path.isdir(st):
        n = len([l for l in open(os.path.join(st, "added.txt"), encoding="utf-8") if l.strip()])
        print(f"  {slice_dir}: mods on ({n} files)")
    else:
        print(f"  {slice_dir}: no mods")
    if www and os.path.isfile(os.path.join(www, "boot-manifest.json")):
        m = json.load(open(os.path.join(www, "boot-manifest.json"), encoding="utf-8"))
        print(f"  boot-manifest.json: {len(m.get(WWW_KEY, []))} mod files")


def main(argv):
    cmd, args = (argv[1], argv[2:]) if len(argv) > 1 else ("", [])
    if cmd == "build" and len(args) == 4:
        build(*args)
    elif cmd == "digest" and len(args) == 1:
        print(digest(args[0]))
    elif cmd == "apply-slice" and len(args) == 2:
        apply_slice(*args)
    elif cmd == "brand-toc" and len(args) == 2:
        brand_toc(args[0], args[1])
    elif cmd == "unapply-slice" and len(args) == 1:
        unapply_slice(args[0])
    elif cmd == "apply-www" and len(args) == 2:
        apply_www(*args)
    elif cmd == "unapply-www" and len(args) == 1:
        unapply_www(args[0])
    elif cmd == "status" and len(args) in (1, 2):
        status(*args)
    else:
        die(__doc__)


if __name__ == "__main__":
    main(sys.argv)
