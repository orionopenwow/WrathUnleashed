#!/usr/bin/env python3
"""Tests for export.py (the Leyline repo copy) and the Autopilot step that runs it. Temp folders only.

    python3 -I tools/leyline-repo/test_export.py
"""
import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location("export", HERE / "export.py")
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)

fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    fails += 0 if cond else 1


def run(src, dst, **kw):
    buf = io.StringIO()
    with redirect_stdout(buf):
        res = ex.export(Path(src), Path(dst), out=print, **kw)
    return res, buf.getvalue()


def refused(src, dst):
    try:
        run(src, dst)
    except ex.Refused as e:
        return str(e)
    return None


def put(root, rel, data=b"x\n"):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return p


def files_of(root):
    root = Path(root)
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def snapshot(root):
    root = Path(root)
    return {r: (root / r).read_bytes() for r in files_of(root)}


tmp = Path(tempfile.mkdtemp(prefix="leyline-test-"))
try:
    # ------------------------------------------------------------------ the allow-list, from this repo
    out1 = tmp / "out1"
    res, log = run(REPO, out1)
    got = set(files_of(out1))
    want = ["hosting/relay/wurelay/relay.py", "hosting/relay/Dockerfile", "hosting/relay/deploy/relay.env.example",
            "hosting/kit/leyline", "hosting/kit/host-wrath-realm.sh", "hosting/kit/tools/wunet/mux.py",
            "hosting/kit/tools/wuhost/agent.py", "hosting/kit/tools/wunet/leyline.env",
            "hosting/discord/wudiscord/bridge.py", "hosting/discord/deploy/discord.env.example",
            "hosting/tests/test_relay.py", "hosting/tests/helpers.py", "hosting/README.md",
            "hosting/INSTALL-OPERATE.md", f"{ex.ADDON}/Leyline.lua", "realm/custom/lua_scripts/ov_leyline.lua",
            "stream/links.py", "stream/www-files/art/leyline-display-OFL.txt",
            "stream/www-files/art/leyline-display.woff2", "stream/www-files/art/leyline-emblem.webp",
            "docs/leyline/index.md", "docs/leyline/mods.md", "docs/leyline/cross-server.md",
            "launcher/README.md", "launcher/ui/index.html", "launcher/src-tauri/Cargo.toml",
            "launcher/src-tauri/src/clients.rs", "launcher/ui/art/leyline-emblem.webp",
            "README.md", "LICENSE", "THIRD-PARTY-NOTICES.md", ".gitignore"]
    missing = [w for w in want if w not in got]
    check("allow-list: the relay, kit, tools, bridge, tests, addon, links, art and top files are there", not missing, missing)
    art = sorted(n for n in os.listdir(REPO / "stream/www-files/art") if n.startswith("leyline-"))
    docs = sorted(n for n in os.listdir(REPO / "docs/leyline") if n.endswith(".md"))
    check("allow-list: every docs/leyline page", docs and all(f"docs/leyline/{n}" in got for n in docs), docs)
    check("brand check covers the docs pages", ex.user_facing("docs/leyline/index.md")
          and ex.brand_hits("docs/leyline/index.md", b"Play WoW") and not ex.user_facing("docs/other.txt"))
    check("allow-list: every leyline-* art file", all(f"stream/www-files/art/{n}" in got for n in art), len(art))
    outside = [g for g in got if g not in ex.GENERATED and g.split("/")[0] not in ex.MANAGED]
    check("allow-list: nothing outside the managed folders but the top files", not outside, outside)
    check("allow-list: no ModsPanel.lua, control.py or other addon files",
          not any(g.endswith(("ModsPanel.lua", "control.py", "WrathUnleashedUI.lua", "Collections.lua")) for g in got))
    check("allow-list: the launcher without its build output (target/, gen/, node_modules/)",
          not any(g.startswith("launcher/") and any(f"/{d}/" in g for d in ("target", "gen", "node_modules")) for g in got))
    check("allow-list: no labs/, client patches or private ops folders (2026-10-30 repo map)",
          not any(g.split("/")[0] in ("labs", "client", "server", "tools", "control", "gmconsole", "play", "players")
                  for g in got) and not any(e.split("/")[0] == "labs" for e in ex.ALLOW))
    check("allow-list: no __pycache__ / .pyc", not any("__pycache__" in g or g.endswith(".pyc") for g in got))
    lic = (out1 / "LICENSE").read_text()
    check("LICENSE: the repo's MIT license", lic.startswith("MIT License") and "WrathUnleashed contributors" in lic)
    check("notices: the font's OFL and the third parties", all(s in (out1 / "THIRD-PARTY-NOTICES.md").read_text()
                                                              for s in ("SIL Open Font License", "AzerothCore", "ed25519")))
    readme = (out1 / "README.md").read_text()
    check("README: what Leyline is, leyline host, relay, open source, links back",
          all(s in readme for s in ("leyline host", "relay", "Open source", "browser",
                                    "https://github.com/orionopenwow/WrathUnleashed", "## Layout", "## Quick start")))
    check("README: no brand words", not ex.brand_hits("README.md", readme.encode()))
    gi = (out1 / ".gitignore").read_text()
    check(".gitignore: state, .env, keys, game data", all(s in gi for s in ("**/state/", ".env", "*.pem", "*.mpq", "*.blp")))
    check("--list-exec: the leyline command and the shell scripts", "hosting/kit/leyline" in res["exec"]
          and all(r.endswith((".sh", "leyline")) for r in res["exec"]))
    if os.name != "nt":
        check("exec bit set on leyline", os.access(out1 / "hosting/kit/leyline", os.X_OK))

    # ------------------------------------------------------------------ deterministic, idempotent
    snap = snapshot(out1)
    mt = {r: (out1 / r).stat().st_mtime_ns for r in snap}
    res2, log2 = run(REPO, out1)
    check("idempotent: a second run writes nothing", res2["written"] == [] and res2["deleted"] == [], res2["written"][:3])
    check("idempotent: no file was touched", all((out1 / r).stat().st_mtime_ns == mt[r] for r in snap))
    out2 = tmp / "out2"
    run(REPO, out2)
    check("deterministic: two exports are byte-identical", snapshot(out2) == snap)
    _, dry = run(REPO, tmp / "never", dry=True)
    check("dry run writes nothing", not (tmp / "never").exists() and "dry run" in dry)

    # ------------------------------------------------------------------ refusals (a source made from the export)
    src = tmp / "src"
    shutil.copytree(out1, src)
    planted_bad = {
        "hosting/relay/data/patch-enUS.MPQ": "game data", "hosting/kit/model.m2": "game data",
        "hosting/kit/city.wmo": "game data", "hosting/kit/tile_32_48.adt": "game data",
        "hosting/tests/icon.blp": "game data", "hosting/tests/Spell.dbc": "game data",
        "hosting/tests/x00.skin": "game data", "hosting/tests/x.anim": "game data",
        "hosting/kit/fui-src.tgz.part00": "game data", "hosting/kit/slice.tgz": "game data",
        "hosting/kit/wasm.part.03": "game data",
        "hosting/kit/.env": "secret", "hosting/discord/deploy/discord.env": "secret",
        "hosting/relay/deploy/server.pem": "secret", "hosting/kit/tools/realm.key": "secret",
        "hosting/discord/bot-token.txt": "secret", "hosting/kit/id_ed25519": "secret",
        "hosting/relay/relay.log": "log", "hosting/tests/run.log.1": "log",
        "hosting/kit/decompiled/client.c": "decompiled", "hosting/kit/tools/Wow.exe.i64": "decompiled",
    }
    for rel in planted_bad:
        put(src, rel)
    put(src, "hosting/tests/fixture.py", "K = '''-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n'''\n")
    put(src, "hosting/kit/tools/wuhost/gen.c", "/* Generated by Ghidra */ int f(void);\n")
    cites = {"hosting/kit/tools/c1.rs": "// test (`CanTargetUnit 0x6e4440`).\n",
             "hosting/kit/tools/c2.rs": "/// The last-input stamp `[0xcf0bc8]` is read\n",
             "hosting/kit/tools/c3.md": "`CGGameUI::SetUIScale` scales the frame\n",
             "hosting/kit/tools/c4.lua": "-- as the reference's callback clamps\n",
             "hosting/kit/tools/c5.patch": "--- a/x\n+++ b/x\n@@ -1 +1 @@\n+// at `0x689110`\n"}
    fine = {"hosting/kit/tools/f1.rs": "let c = 0xffcc00; let s = CStr::from_ptr(p); // see the reference docs\n",
            "hosting/kit/tools/f2.patch": "--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n /// upstream `CanTargetUnit 0x6e4440`\n+// plain\n"}
    for rel, text in {**cites, **fine}.items():
        put(src, rel, text)
    put(src, "hosting/relay/ghp.txt", "ghp_" + "a" * 36 + "\n")
    put(src, "hosting/kit/state/realm.key", "secret key")
    put(src, "hosting/kit/state/host.json", "{}")
    put(src, "hosting/kit/cache/blob.bin", "cache")
    put(src, "hosting/kit/realm-files/profiles/main.env", "X=1")
    put(src, "hosting/logs/x.txt", "log")
    put(src, "hosting/relay/deploy/extra.env.example", "RELAY_DOMAIN=\n")      # examples are fine
    out3 = tmp / "out3"
    res3, log3 = run(src, out3)
    got3 = set(files_of(out3))
    leaked = [r for r in list(planted_bad) + ["hosting/tests/fixture.py", "hosting/kit/tools/wuhost/gen.c",
                                              "hosting/relay/ghp.txt"] if r in got3]
    check("refusal: game data, secrets, logs, decompiled code are not copied", not leaked, leaked)
    whys = dict(res3["refused"])
    wrong = [r for r, k in planted_bad.items() if k not in whys.get(r, "")]
    check("refusal: each one is listed as REFUSED with the right reason", not wrong, [(r, whys.get(r)) for r in wrong][:4])
    check("refusal: private-key text and tokens inside a file", "secret" in whys.get("hosting/tests/fixture.py", "")
          and "secret" in whys.get("hosting/relay/ghp.txt", ""))
    check("refusal: decompiled text inside a file", "decompiled" in whys.get("hosting/kit/tools/wuhost/gen.c", ""))
    check("refusal: original-binary citations (addresses, client symbols) are refused",
          all("original-binary citation" in whys.get(r, "") and r not in got3 for r in cites), [(r, whys.get(r)) for r in cites])
    check("refusal: ordinary hex, CStr and upstream patch context are not citations",
          all(r in got3 for r in fine), [(r, whys.get(r)) for r in fine])
    check("refusal: state/, cache/, realm-files/, logs/ never entered",
          not any(re.search(r"/(state|cache|realm-files|logs)/", "/" + g) for g in got3)
          and "skipped hosting/kit/state/" in log3)
    check("refusal: *.env.example and the public leyline.env are copied",
          "hosting/relay/deploy/extra.env.example" in got3 and "hosting/kit/tools/wunet/leyline.env" in got3)
    check("refusal: REFUSED lines in the output", log3.count("REFUSED ") == len(res3["refused"]) >= len(planted_bad))

    src_b = tmp / "src_b"
    shutil.copytree(out1, src_b)
    put(src_b, "hosting/kit/tools/wunet/leyline.env", "LEYLINE_DOMAIN=example.org\nDB_PASSWORD=hunter2\n")
    run(src_b, tmp / "out_b")
    check("refusal: leyline.env with any other key is left out",
          not (tmp / "out_b/hosting/kit/tools/wunet/leyline.env").exists())
    src_c = tmp / "src_c"
    shutil.copytree(out1, src_c)
    put(src_c, "stream/links.py", "KEY = '-----BEGIN RSA PRIVATE KEY-----'\n")
    e = refused(src_c, tmp / "out_c")
    check("refusal: a file named on the allow-list that looks like a secret stops the export",
          e is not None and "stream/links.py" in e and not (tmp / "out_c").exists(), e)
    src_d = tmp / "src_d"
    shutil.copytree(out1, src_d)
    os.remove(src_d / "stream/links.py")
    e = refused(src_d, tmp / "out_d")
    check("a missing allow-list entry stops the export", e is not None and "missing" in e, e)
    e = refused(REPO, REPO / "tools" / "leyline-out")
    check("a target inside the WrathUnleashed folder is refused", e is not None and not (REPO / "tools/leyline-out").exists())
    src_r = tmp / "src_r"
    shutil.copytree(out1, src_r)
    res_r, _ = run(src_r, src_r / ".repos" / "leyline-public")
    check("the workspace's .repos/leyline-public is a valid target (Move to Leyline)",
          res_r is not None and (src_r / ".repos/leyline-public/hosting/relay/wurelay/relay.py").is_file()
          and not any(f.startswith(".repos") for f in res_r["files"]))
    e = refused(src_r, src_r / ".repos")
    check("but not .repos itself, nor the workspace", e is not None and refused(src_r, src_r) is not None)

    # ------------------------------------------------------------------ banned words
    def banned_case(rel, text):
        s = tmp / ("bw-" + re.sub(r"\W", "_", rel + text[:12]))
        shutil.copytree(out1, s)
        put(s, rel, text)
        dst = tmp / (s.name + "-out")
        shutil.copytree(out1, dst)
        before = snapshot(dst)
        err = refused(s, dst)
        return err, snapshot(dst) == before

    for rel, text in (("hosting/README.md", "Host a World of Warcraft realm\n"),
                      ("hosting/README.md", "a warcraft server\n"),
                      ("hosting/relay/wurelay/www/join.html", "<p>Join our WoW realm</p>\n"),
                      ("hosting/relay/wurelay/www/join.html", "<p>Wrath of the Lich King</p>\n"),
                      ("hosting/relay/wurelay/www/new.html", "<title>Blizzard</title>\n")):
        err, untouched = banned_case(rel, text)
        check(f"banned words: {text.strip()!r} in {rel.rsplit('/', 1)[-1]} stops it, target untouched",
              err is not None and rel in err and untouched, err)
    err, _ = banned_case("hosting/relay/wurelay/www/join.html", "<p>wow, a realm! Wowza.</p>\n")
    check("banned words: 'wow'/'Wowza' are not the whole word WoW", err is None, err)
    err, _ = banned_case("hosting/kit/tools/wunet/srp6.py", "# WoW SRP6, Blizzard's variant\n")
    check("banned words: code and tests are not user-facing", err is None, err)
    check("banned words: the generated README is checked too",
          ex.brand_hits("README.md", b"Play WoW") and ex.user_facing("README.md"))

    # ------------------------------------------------------------------ deletion scope
    tgt = tmp / "tgt"
    shutil.copytree(out1, tgt)
    put(tgt, "hosting/relay/wurelay/old_module.py")          # stale, managed: deleted
    put(tgt, "stream/old-page.html")                          # stale, managed: deleted
    put(tgt, "hosting/gone/deep/file.txt")                    # stale, managed: deleted with its folders
    put(tgt, ".git/config", "[core]\n")                       # never touched
    put(tgt, ".git/objects/ab/cdef")
    put(tgt, "hosting/.git/HEAD", "ref\n")                    # a .git inside a managed folder: never touched
    put(tgt, "notes/notes.md")                                # not managed: kept
    put(tgt, "CONTRIBUTING.md")                               # not managed: kept
    put(tgt, ".github/workflows/ci.yml")                      # not managed: kept
    res5, _ = run(REPO, tgt)
    g5 = set(files_of(tgt))
    check("deletion: stale files in managed folders are deleted",
          not {"hosting/relay/wurelay/old_module.py", "stream/old-page.html", "hosting/gone/deep/file.txt"} & g5
          and not (tgt / "hosting/gone").exists())
    check("deletion: .git (top and nested) is never touched",
          {".git/config", ".git/objects/ab/cdef", "hosting/.git/HEAD"} <= g5)
    check("deletion: files outside the managed folders are kept",
          {"notes/notes.md", "CONTRIBUTING.md", ".github/workflows/ci.yml"} <= g5)
    check("deletion: exactly the three stale files", sorted(res5["deleted"]) ==
          ["hosting/gone/deep/file.txt", "hosting/relay/wurelay/old_module.py", "stream/old-page.html"], res5["deleted"])
    src_e = tmp / "src_e"
    shutil.copytree(out1, src_e)
    os.remove(src_e / "hosting/tests/test_crypto.py")
    tgt_e = tmp / "tgt_e"
    shutil.copytree(out1, tgt_e)
    res6, _ = run(src_e, tgt_e)
    check("deletion: a file removed from the source goes on the next run",
          res6["deleted"] == ["hosting/tests/test_crypto.py"] and not (tgt_e / "hosting/tests/test_crypto.py").exists())
    put(tgt_e, "README.md", "edited by hand\n")
    res7, _ = run(src_e, tgt_e)
    check("a hand edit to a generated file is put back", res7["written"] == ["README.md"])

    # ------------------------------------------------------------------ the Autopilot step and its .bat
    ctl = (REPO / "tools/control/control.py").read_text()
    m = re.search(r'"leyline":\s*\("([^"]+)",\s*"([^"]+)",\s*(True|False)\)', ctl)
    check("control.py: a 'leyline' step, not interactive", m is not None and m.group(3) == "False")
    bat_path = REPO / m.group(1) if m else None
    check("control.py: its .bat exists", bat_path is not None and bat_path.is_file(), m and m.group(1))
    bat = bat_path.read_text() if bat_path and bat_path.is_file() else ""
    low = bat.lower()
    check("bat: exports into .repos\\leyline-public in the workspace", r'set "LY=%WU%\.repos\leyline-public"' in bat
          and "export.py" in bat)
    check("bat: the old Desktop\\Leyline clone only before the move, and never the workspace itself",
          r'if not exist "%LY%\.git" if exist "%USERPROFILE%\Desktop\Leyline\.git" if /i not "%USERPROFILE%\Desktop\Leyline"=="%WU%"' in bat
          and bat.index(r'set "LY=%WU%\.repos') < bat.index("LEYLINE_REPO_DIR"))
    check("bat: git init -b main when there is no .git", 'if exist ".git"' in bat and "git init -q -b main" in bat)
    check("bat: gh repo view before gh repo create, orionopenwow/Leyline, public",
          'set "SLUG=orionopenwow/Leyline"' in bat and 0 < low.find("gh repo view %slug%") < low.find("gh repo create %slug%")
          and "--public --source . --remote origin" in bat)
    check("bat: never force-pushes", not re.search(r"--force|push\s+-f\b|\+head|\+main", low))
    check("bat: add -A, commit only if changed, push", "git add -A" in bat and "git diff --cached --quiet" in bat
          and "git push -q -u origin HEAD:main" in bat)
    wu_git = re.findall(r'git -C "%WU%" ([a-z-]+)', bat)
    check("bat: the WrathUnleashed git is only read", wu_git and set(wu_git) <= {"config", "rev-parse"}
          and all(not re.search(r'git -C "%WU%" config user\.\w+ "', bat) for _ in [0]), wu_git)
    check("bat: Chumpton only ever refused", all("chumpton" not in l.lower() or "goto :fail" in l
                                                 for l in bat.splitlines() if not l.lower().startswith("rem")))
    check("bat: ok/fail lines and exit codes like the other steps",
          "exit /b 0" in bat and "exit /b 1" in bat and "LEYLINE OK" in bat and "LEYLINE FAILED" in bat)
    raw = bat_path.read_bytes()
    check("bat: one line-ending style (LF in git, CRLF on the PC: the deploy converts)",
          (b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")) or b"\r" not in raw)
    spec_c = importlib.util.spec_from_file_location("control_t", REPO / "tools/control/control.py")
    os.environ.setdefault("LOCALAPPDATA", str(tmp / "appdata"))
    ctlmod = importlib.util.module_from_spec(spec_c)
    spec_c.loader.exec_module(ctlmod)
    check("control.py: imports, every step's .bat exists", "leyline" in ctlmod.STEPS
          and all((REPO / b).is_file() for b, _, _ in ctlmod.STEPS.values()))
    check("control.py: the self-restart is still there", "restart_if_updated()" in ctl and "SELF_MTIME" in ctl)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
