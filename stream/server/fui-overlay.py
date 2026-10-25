#!/usr/bin/env python3
"""Lay Forever UI (github.com/Adrestie/mod-forever-ui, GPL-2.0, by Adrestie) over a streamed slice.

Run by fui-install.sh on the server (python3 -I, standard library only):

  fui-overlay.py check         <overlay>            what the overlay holds
  fui-overlay.py apply-slice   <overlay> <slice>    (re)lay it over a slice folder
  fui-overlay.py unapply-slice <slice>              take it off again, exactly
  fui-overlay.py apply-www     <slice> <www>        its text files (+ some login art) into boot-manifest.json
  fui-overlay.py unapply-www   <www>
  fui-overlay.py status        <slice> [<www>]

<overlay> is a folder in game-path layout (Interface/AddOns/ForeverUI/..., Interface/ForeverUI/...,
Interface/GlueXML/ForeverUI*). Only those three places are taken, like the player's own install:
  * files the slice does not have are hard-linked in (no second copy on disk);
  * a file the slice already has is left alone (at home the archives' copy wins over loose files
    too), except Interface/GlueXML/GlueXML.toc, which gets the one line Forever UI adds
    ("ForeverUIGlue.xml"), made from the slice's own stock toc; the stock copy is kept;
  * the slice's tier-0 list (.tiers/0.txt + index.json) lists the added files ("# foreverui
    overlay" lines; the text and up to 48 MB of the art the code names go ahead of the stock
    entries, the rest after), so the client's interface prefetch and "Download this section"
    see them.
Everything done is recorded in <slice>/.overlay-foreverui/ (a dot folder: wenilla-host neither
lists nor serves it), so unapply is exact and apply is idempotent (it unapplies first). A freshly
uploaded slice has no record, so nothing stale is ever "restored" over it.
"""
import json
import os
import re
import shutil
import sys

STATE = ".overlay-foreverui"
MARK = "# foreverui overlay (fui-overlay.py): the rest"
MARK_FIRST = "# foreverui overlay (fui-overlay.py): first, ahead of the stock interface art"
MARK_STOCK = "# the slice's own tier 0"
WWW_KEY = "foreverui_overlay"
TOC_REL = ("Interface", "GlueXML", "GlueXML.toc")
GLUE_ENTRY = "ForeverUIGlue.xml"
# WrathUnleashed (fui-glue): extra glue files listed right after GLUE_ENTRY when the overlay has
# them (stream\fui-web, copied in by "Add Forever UI to the stream.bat"). Not Forever UI's own.
GLUE_EXTRA = ("ForeverUIGlueWeb.xml",)
TEXT_EXT = (".toc", ".lua", ".xml")
# Login-screen art fetched with the boot set, smallest first (one round trip saved per file).
BOOT_ART_BUDGET = 8 * 1024 * 1024
# Forever UI art listed ahead of the stock entries in tier 0 (the client's interface prefetch
# takes art in list order up to its 160 MB budget); the rest of its art goes after them.
TIER0_FIRST_ART = int(os.environ.get("FUI_TIER0_FIRST_MB", "48")) * 1024 * 1024


def die(msg):
    print(f"fui-overlay: {msg}", file=sys.stderr)
    sys.exit(1)


def taken(parts):
    """Is this overlay path one Forever UI owns (the install .bat's three places)?"""
    low = [p.lower() for p in parts]
    if len(low) < 3 or low[0] != "interface" or any(p.startswith(".") or not p for p in low):
        return False
    if low[1] == "addons" and low[2] == "foreverui" and len(low) >= 4:
        return True
    if low[1] == "foreverui" and len(low) >= 3:
        return True
    if low[1] == "gluexml" and len(low) == 3 and (low[2].startswith("foreverui") or low[2] == "gluexml.toc"):
        return True
    return False


def overlay_files(root):
    """[(parts, abs path)] of the overlay's files Forever UI owns, sorted; plus the ignored count."""
    out, ignored = [], 0
    for d, dirs, files in os.walk(root):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(d, f)
            parts = tuple(os.path.relpath(p, root).split(os.sep))
            if taken(parts) and os.path.isfile(p) and not os.path.islink(p):
                out.append((parts, p))
            else:
                ignored += 1
    return out, ignored


def child(d, name):
    """`d/name`, matched case-insensitively like wenilla-host's patch lookup; None when absent."""
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


def is_text(name):
    return name.lower().endswith(TEXT_EXT)


def art_refs(overlay_files_list, glue_only):
    """Lower-case art keys (no .blp) the glue (or addon) code names in string literals."""
    refs = set()
    for parts, p in overlay_files_list:
        low = [x.lower() for x in parts]
        is_glue = low[1] == "gluexml"
        is_addon = low[1] == "addons"
        if not is_text(parts[-1]) or (glue_only and not is_glue) or (not glue_only and not is_addon):
            continue
        try:
            s = open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for m in re.findall(r"[\"']([^\"'\n]*foreverui[\\/][^\"'\n]*)[\"']", s, re.I):
            k = re.sub(r"[\\/]+", "\\\\", m).lower()
            refs.add(k[:-4] if k.endswith(".blp") else k)
    return refs


def ref_match(name, refs):
    k = name.lower()
    k = k[:-4] if k.endswith(".blp") else k
    return k in refs or any(r.endswith("\\") and k.startswith(r) for r in refs)


def write_atomic(path, data, like=None):
    tmp = path + ".fui-tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.chmod(tmp, (os.stat(like).st_mode & 0o7777) if like and os.path.exists(like) else 0o644)
    os.replace(tmp, path)


def patched_toc(stock: bytes, extra=()) -> bytes:
    """The stock GlueXML.toc with Forever UI's one entry (and the WrathUnleashed `extra` entries
    right after it), before the always-last localisation file."""
    text = stock.decode("latin-1")
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    low = [l.strip().lower() for l in lines]
    if GLUE_ENTRY.lower() in low:
        at = low.index(GLUE_ENTRY.lower()) + 1
        missing = [e for e in extra if e.lower() not in low]
        if not missing:
            return stock
        lines[at:at] = missing
        return nl.join(lines).encode("latin-1")
    at = None
    for i, l in enumerate(lines):
        s = l.strip().lower()
        if s.startswith("## this always runs last") or s == "gluelocalizationpost.xml":
            at = i
            break
    entries = [GLUE_ENTRY] + [e for e in extra if e.lower() not in low]
    if at is None:
        while lines and lines[-1] == "":
            lines.pop()
        lines += entries + [""]
    else:
        lines[at:at] = entries + [""]
    return nl.join(lines).encode("latin-1")


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
    bk = os.path.join(st, "backup")
    if os.path.isdir(bk):
        for d, _, files in os.walk(bk):
            for f in files:
                src = os.path.join(d, f)
                dst = os.path.join(slice_dir, os.path.relpath(src, bk))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                write_atomic(dst, open(src, "rb").read(), like=src)
    shutil.rmtree(st)
    if not quiet:
        print(f"  Forever UI taken off {slice_dir}: {removed} files")
    return removed


def apply_slice(overlay, slice_dir):
    if not os.path.isdir(slice_dir):
        die(f"no slice folder {slice_dir}")
    files, ignored = overlay_files(overlay)
    names_low = {"\\".join(p).lower() for p, _ in files}
    if "interface\\addons\\foreverui\\foreverui.toc" not in names_low:
        die("the overlay has no Interface/AddOns/ForeverUI/ForeverUI.toc")
    if f"interface\\gluexml\\{GLUE_ENTRY.lower()}" not in names_low:
        die(f"the overlay has no Interface/GlueXML/{GLUE_ENTRY}")
    unapply_slice(slice_dir, quiet=True)
    st = state_dir(slice_dir)
    os.makedirs(os.path.join(st, "backup"))
    added, made_dirs, kept_stock = [], [], 0
    toc_src = None
    for parts, src in files:
        if tuple(x.lower() for x in parts) == tuple(x.lower() for x in TOC_REL):
            toc_src = src
            continue
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
            kept_stock += 1
            continue
        dst = os.path.join(d, parts[-1])
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
        os.chmod(dst, 0o644)
        added.append((chain_name(slice_dir, dst), os.path.getsize(dst)))
    # GlueXML.toc: the slice's own stock list plus Forever UI's entry (the stock copy is kept).
    gx = slice_dir
    for comp in TOC_REL[:-1]:
        nxt = child(gx, comp)
        if nxt is None:
            nxt = os.path.join(gx, comp)
            os.mkdir(nxt)
            made_dirs.append(chain_name(slice_dir, nxt))
        gx = nxt
    toc = child(gx, TOC_REL[-1])
    extra = [e for e in GLUE_EXTRA if f"interface\\gluexml\\{e.lower()}" in names_low]
    if toc is not None:
        stock = open(toc, "rb").read()
        bk = os.path.join(st, "backup", chain_name(slice_dir, toc).replace("\\", os.sep))
        os.makedirs(os.path.dirname(bk), exist_ok=True)
        write_atomic(bk, stock, like=toc)
        new = patched_toc(stock, extra)
        write_atomic(toc, new, like=toc)
        toc_note = "patched from the slice's stock copy (kept)" + (f", + {', '.join(extra)}" if extra else "")
    elif toc_src is not None:
        toc = os.path.join(gx, TOC_REL[-1])
        write_atomic(toc, patched_toc(open(toc_src, "rb").read(), extra))
        os.chmod(toc, 0o644)
        added.append((chain_name(slice_dir, toc), os.path.getsize(toc)))
        toc_note = "the slice had none: Forever UI's own copy"
    else:
        die("neither the slice nor the overlay has Interface/GlueXML/GlueXML.toc")
    with open(os.path.join(st, "added.txt"), "w", encoding="utf-8") as f:
        f.write("".join(n + "\n" for n, _ in added))
    with open(os.path.join(st, "dirs.txt"), "w", encoding="utf-8") as f:
        f.write("".join(n + "\n" for n in made_dirs))
    tier0(slice_dir, files, added)
    total = sum(b for _, b in added)
    print(f"  Forever UI laid over {slice_dir}: {len(added)} files, {total / 1048576:.0f} MB"
          f" (hard links), GlueXML.toc {toc_note}"
          + (f", {kept_stock} kept the slice's copy" if kept_stock else "")
          + (f", {ignored} overlay files outside Forever UI's folders skipped" if ignored else ""))


def order_for_prefetch(files, added):
    """(first, rest): text, then the art the login screens name, then the art the addon names
    (smallest first: one round trip saved per file), the art up to TIER0_FIRST_ART; then the rest."""
    glue = art_refs(files, glue_only=True)
    addon = art_refs(files, glue_only=False)

    def rank(item):
        n = item[0]
        if is_text(n):
            return 0
        if "\\credits\\" not in n.lower() and ref_match(n, glue):
            return 1
        if ref_match(n, addon):
            return 2
        return 3

    ranked = sorted(added, key=lambda it: (rank(it), it[1] if rank(it) else 0))
    first, rest, used = [], [], 0
    for it in ranked:
        r = rank(it)
        if r == 0 or (r < 3 and used + it[1] <= TIER0_FIRST_ART):
            first.append(it)
            used += it[1] if r else 0
        else:
            rest.append(it)
    return first, rest


def tier0(slice_dir, files, added):
    """Forever UI into the slice's tier-0 list, which the client's interface prefetch reads
    (boot.js uiPrefetchNames: its art tier takes .blp names in list order up to 160 MB). The
    first block goes BEFORE the stock entries, so Forever UI's own frames win the budget over the
    stock ones it replaces; the rest goes after them (still listed for "Download this section")."""
    tiers = os.path.join(slice_dir, ".tiers")
    t0 = os.path.join(tiers, "0.txt")
    if not os.path.isfile(t0):
        return
    st = state_dir(slice_dir)
    bk = os.path.join(st, "backup", ".tiers")
    os.makedirs(bk, exist_ok=True)
    shutil.copy2(t0, os.path.join(bk, "0.txt"))
    idx = os.path.join(tiers, "index.json")
    if os.path.isfile(idx):
        shutil.copy2(idx, os.path.join(bk, "index.json"))
    lines = open(t0, "rb").read().decode("utf-8").split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    head = lines[:1] if lines and lines[0].startswith("# tier") else []
    body = lines[len(head):]
    have = {l.split("\t", 1)[1].strip().lower() for l in body if l and not l.startswith("#") and "\t" in l}
    first, rest = order_for_prefetch(files, [it for it in added if it[0].lower() not in have])
    if not first and not rest:
        return
    extra = first + rest
    add_files, add_bytes = len(extra), sum(b for _, b in extra)
    if head:
        h = head[0].split("\t")
        if len(h) >= 3 and h[-1].isdigit() and h[-2].isdigit():
            h[-2], h[-1] = str(int(h[-2]) + add_files), str(int(h[-1]) + add_bytes)
            head = ["\t".join(h)]
    row = lambda it: f"{it[1]}\t{it[0]}"
    out = head + [MARK_FIRST] + [row(it) for it in first] + [MARK_STOCK] + body + [MARK] + [row(it) for it in rest]
    write_atomic(t0, ("\n".join(out) + "\n").encode("utf-8"), like=t0)
    if os.path.isfile(idx):
        try:
            tiers_json = json.load(open(idx, encoding="utf-8"))
            for t in tiers_json:
                if isinstance(t, dict) and t.get("tier") == 0:
                    t["files"] = int(t.get("files", 0)) + add_files
                    t["bytes"] = int(t.get("bytes", 0)) + add_bytes
            write_atomic(idx, json.dumps(tiers_json, indent=2).encode("utf-8"), like=idx)
        except (ValueError, TypeError) as e:
            print(f"  WARNING: .tiers/index.json not updated ({e})")
    fa = sum(b for n, b in first if not is_text(n))
    print(f"  tier 0 list: +{add_files} files, +{add_bytes / 1048576:.0f} MB"
          f" ({len(first)} ahead of the stock entries: the text and {fa / 1048576:.0f} MB of art)")


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
        print(f"  boot-manifest.json: {len(drop)} Forever UI names taken out")


def apply_www(slice_dir, www, backup_dir=None):
    bm = os.path.join(www, "boot-manifest.json")
    if not os.path.isfile(bm):
        print("  no boot-manifest.json in the client build: Forever UI's files load on demand")
        return
    added_txt = os.path.join(state_dir(slice_dir), "added.txt")
    if not os.path.isfile(added_txt):
        unapply_www(www)
        return
    m = json.load(open(bm, encoding="utf-8"))
    if WWW_KEY not in m and backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
        shutil.copy2(bm, os.path.join(backup_dir, "boot-manifest.before-foreverui.json"))
    unapply_www(www, quiet=True)
    m = json.load(open(bm, encoding="utf-8"))
    names = [n for n in open(added_txt, encoding="utf-8").read().splitlines() if n]
    sizes = {}
    for n in names:
        try:
            sizes[n] = os.path.getsize(os.path.join(slice_dir, *n.split("\\")))
        except OSError:
            sizes[n] = 0
    glue_toc = "\\".join(TOC_REL)
    files = [(tuple(n.split("\\")), os.path.join(slice_dir, *n.split("\\"))) for n in names]
    glue_refs = art_refs(files, glue_only=True)
    text = [n for n in names if is_text(n)]
    art = sorted((n for n in names if n.lower().endswith(".blp") and "\\credits\\" not in n.lower()
                  and ref_match(n, glue_refs)), key=lambda n: sizes[n])
    boot_art, used = [], 0
    for n in art:
        if used + sizes[n] > BOOT_ART_BUDGET:
            break
        boot_art.append(n)
        used += sizes[n]
    have = {store_key(n) for n in m.get("names", [])}
    ours = [n for n in text + boot_art if store_key(n) not in have]
    m["names"] = list(m.get("names", [])) + ours
    m[WWW_KEY] = ours
    write_atomic(bm, json.dumps(m, indent=1).encode("utf-8"), like=bm)
    for ext in (".br", ".gz"):
        if os.path.exists(bm + ext):
            os.unlink(bm + ext)
    note = "" if any(store_key(n) == store_key(glue_toc) for n in m["names"]) else " (GlueXML.toc is not in it!)"
    print(f"  boot-manifest.json: +{len(ours)} Forever UI files ({len(text)} text, {len(boot_art)} login art,"
          f" {(sum(sizes[n] for n in ours)) / 1048576:.1f} MB){note}")


def check(overlay):
    files, ignored = overlay_files(overlay)
    if not any("\\".join(p).lower() == "interface\\addons\\foreverui\\foreverui.toc" for p, _ in files):
        die("not a Forever UI overlay (no Interface/AddOns/ForeverUI/ForeverUI.toc)")
    total = sum(os.path.getsize(p) for _, p in files)
    groups = {}
    for p, _ in files:
        g = "\\".join(p[:3]) if p[1].lower() != "gluexml" else "Interface\\GlueXML"
        groups[g] = groups.get(g, 0) + 1
    print(f"  overlay: {len(files)} files, {total / 1048576:.0f} MB "
          + ", ".join(f"{k} {v}" for k, v in sorted(groups.items()))
          + (f"; {ignored} other files ignored" if ignored else ""))


def status(slice_dir, www=None):
    st = state_dir(slice_dir)
    if os.path.isdir(st):
        n = len([l for l in open(os.path.join(st, "added.txt"), encoding="utf-8") if l.strip()])
        print(f"  {slice_dir}: Forever UI on ({n} files added, GlueXML.toc patched)")
    else:
        print(f"  {slice_dir}: no Forever UI")
    if www:
        bm = os.path.join(www, "boot-manifest.json")
        if os.path.isfile(bm):
            m = json.load(open(bm, encoding="utf-8"))
            print(f"  boot-manifest.json: {len(m.get(WWW_KEY, []))} Forever UI names")


def main(argv):
    if len(argv) < 2:
        die(__doc__)
    cmd, args = argv[1], argv[2:]
    if cmd == "check" and len(args) == 1:
        check(args[0])
    elif cmd == "apply-slice" and len(args) == 2:
        apply_slice(args[0], args[1])
    elif cmd == "unapply-slice" and len(args) == 1:
        unapply_slice(args[0])
    elif cmd == "apply-www" and len(args) in (2, 3):
        apply_www(args[0], args[1], args[2] if len(args) == 3 else None)
    elif cmd == "unapply-www" and len(args) == 1:
        unapply_www(args[0])
    elif cmd == "status" and len(args) in (1, 2):
        status(*args)
    else:
        die(f"bad command: {' '.join(argv[1:])}")


if __name__ == "__main__":
    main(sys.argv)
