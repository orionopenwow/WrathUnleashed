#!/usr/bin/env python3
"""Add "Play with my own game files" (ownfiles.js) and "Download this section" (sections.js) to a
browser client build in place: copies the six scripts from www-files/ and edits index.html and
boot.js by anchors (the same edits as www-files/web.patch), so it works on the build you uploaded
whatever small differences its page has. Safe to run again (already-edited files are left alone).

It also adds the page layer (touch controls, the account dock, the "Signing in" cover, stage
timings, fetch-ahead, the service worker switch, the busy-realm note, "Your addons" (drop an addon
on the page): wrath-page.js and the files it loads) when www-files/ has it: those files are copied and index.html gets one classic
<script src="./wrath-early.js"> before its module script. That part never stops the rest: a
missing file or anchor is a warning, and the page then runs without the page layer.

    python3 -I www-patch.py <www folder> <www-files folder>
"""
import os
import shutil
import sys

SCRIPTS = ["ownfiles.js", "ownfiles-worker.js", "mpq.js", "chain.js", "sections.js", "sections-worker.js"]

# The page layer (wrath-page.js): optional, copied when www-files/ has them all.
PAGE_LAYER = ["wrath-early.js", "wrath-page.js", "stages.js", "input.js", "touch.js", "touch-driver.js",
              "ahead.js", "sw-register.js", "wrath-sw.js", "wu-diag.js", "wu-loading.js", "wu-loading.css", "tab.html",
              "wu-addons.js", "wu-addons-core.js"]
# the loading screens' art and font (www-files/art/ -> www/art/), the 1.12 boot screen's
PAGE_ART = ["wu-load-bg.webp", "wu-load-orion.webp", "wu-corner-tl.webp", "wu-corner-tr.webp", "wu-corner-bl.webp",
            "wu-corner-br.webp", "wu-divider.webp", "wu-dragon-l.webp", "wu-dragon-r.webp",
            "Cinzel-SemiBold.woff2", "Cinzel-OFL.txt"]
PAGE_TAG = '<script src="./wrath-early.js"></script>\n'
# where the tag goes, first anchor found wins: after the sign-in env (so __wenilla_env is set when
# it runs), else before the page's module script; else at the end of the page
PAGE_AFTER = '<script src="/__env.js"></script>\n'
PAGE_BEFORE = '<script type="module">'

IMPORT_ANCHOR = "  import { boot } from './boot.js';\n"
IMPORTS = ("  import { ensureDataSource } from './ownfiles.js';\n"
           "  import { installSections, mountSectionsUi } from './sections.js';\n")
BOOT_CALL = "  const w = await boot(init);\n"
BOOT_NEW = """  // "Use my own game files" (ownfiles.js): when this origin serves no /data, the player's own
  // 3.3.5a Data folder is read in the page (nothing is uploaded); `?ownfiles=1` shows the chooser.
  // "Download this section" (sections.js): on a streamed slice, downloaded tiers are read from
  // Cache Storage. Both are in place before the client starts.
  const dataReady = ensureDataSource({ streamUrl: window.WU_STREAM_URL }).then(async (src) => {
    if (!src || src.mode === 'host') {
      await installSections();
      mountSectionsUi(document.getElementById('dl'));
    }
    return src;
  });
  const w = await boot(init, { dataReady });
"""
CSS = """  /* "Download this section" (sections.js), left of the bell; shown only on a streamed slice. */
  #dl { position: fixed; top: 0; right: 8.4rem; z-index: 10; padding: .3rem .6rem; color: #ddd;
        background: rgba(0,0,0,.55); border: 0; border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;
        cursor: pointer; font: 12px system-ui, sans-serif; text-decoration: underline; }
  #dl[hidden] { display: none; }
"""
BUTTON = ('<button type="button" id="dl" hidden title="Download whole parts of the streamed game ahead of time, '
          'or remove them.">download sections</button>\n')

BOOT_OLD = """  const prefetch = skipPrefetch
    ? Promise.resolve()
    : prefetchManifest('./boot-manifest.json', (done, total) => ui.setData(done, total)).catch(
        () => ui.setData(0, 0)
      );
"""
BOOT_NEW_PREFETCH = """  // `opts.dataReady`: a promise for the /data source (ownfiles.js: the player's own game files;
  // sections.js: downloaded sections). The wasm download starts now regardless; the prefetch and
  // init() wait for it, since both read /data. A rejection fails the boot visibly.
  const dataReady = Promise.resolve(opts.dataReady);
  const prefetch = dataReady.then(() =>
    skipPrefetch
      ? undefined
      : prefetchManifest('./boot-manifest.json', (done, total) => ui.setData(done, total)).catch(
          () => ui.setData(0, 0)
        )
  );
"""


def patch_index(s: str) -> str:
    if "sections.js" in s:
        return s
    for anchor in (IMPORT_ANCHOR, BOOT_CALL, "</style>", '<canvas id="benilla"></canvas>'):
        if anchor not in s:
            raise ValueError(f"index.html: no {anchor.strip()!r} to attach to")
    s = s.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORTS, 1)
    s = s.replace(BOOT_CALL, BOOT_NEW, 1)
    s = s.replace("</style>", CSS + "</style>", 1)
    s = s.replace('<canvas id="benilla"></canvas>', BUTTON + '<canvas id="benilla"></canvas>', 1)
    return s


def patch_boot(s: str) -> str:
    if "opts.dataReady" in s:
        return s
    if BOOT_OLD in s:
        return s.replace(BOOT_OLD, BOOT_NEW_PREFETCH, 1)
    # Newer boot.js (its prefetch block changed): wait for the data source right before the prefetch
    # starts. The wasm download is already under way above that line, so nothing is lost.
    anchor = "  const prefetch = skipPrefetch"
    if s.count(anchor) != 1:
        raise ValueError("boot.js: no prefetch line to attach to (update www-patch.py)")
    return s.replace(anchor, "  // opts.dataReady: the /data source (own game files / downloaded sections) is ready first.\n"
                             "  await Promise.resolve(opts.dataReady);\n" + anchor, 1)


def patch_page_layer(s: str) -> str:
    """index.html with the page layer's one script tag (idempotent; never raises)."""
    if "wrath-early.js" in s:
        return s
    if PAGE_AFTER in s:
        return s.replace(PAGE_AFTER, PAGE_AFTER + PAGE_TAG, 1)
    if PAGE_BEFORE in s:
        return s.replace(PAGE_BEFORE, PAGE_TAG + PAGE_BEFORE, 1)
    print("  WARNING: index.html has no /__env.js or module script to attach the page layer to: "
          "it goes at the end of the page", file=sys.stderr)
    return s.rstrip("\n") + "\n" + PAGE_TAG


def install_page_layer(www: str, files: str) -> None:
    """Copy the page layer and tag index.html; a problem is a warning, never a failure."""
    missing = [n for n in PAGE_LAYER if not os.path.isfile(os.path.join(files, n))]
    if missing:
        if len(missing) < len(PAGE_LAYER):
            print(f"  WARNING: page layer not installed, missing in www-files: {', '.join(missing)}", file=sys.stderr)
        return
    try:
        for name in PAGE_LAYER:
            shutil.copyfile(os.path.join(files, name), os.path.join(www, name))
            for ext in (".br", ".gz"):
                if os.path.exists(os.path.join(www, name + ext)):
                    os.remove(os.path.join(www, name + ext))
        art = [n for n in PAGE_ART if os.path.isfile(os.path.join(files, "art", n))]
        if len(art) < len(PAGE_ART):
            print("  WARNING: www-files/art is incomplete: the loading screens lose some of their art", file=sys.stderr)
        if art:
            os.makedirs(os.path.join(www, "art"), exist_ok=True)
            for name in art:
                shutil.copyfile(os.path.join(files, "art", name), os.path.join(www, "art", name))
        p = os.path.join(www, "index.html")
        with open(p, encoding="utf-8") as f:
            old = f.read()
        new = patch_page_layer(old)
        if new != old:
            with open(p, "w", encoding="utf-8") as f:
                f.write(new)
            print("  index.html: page layer tag added")
        for ext in (".br", ".gz"):
            if os.path.exists(p + ext):
                os.remove(p + ext)
        print(f"  {len(PAGE_LAYER)} page layer files and {len(art)} art files copied (touch controls, dock, signing in, loading screens)")
    except OSError as e:
        print(f"  WARNING: page layer not installed: {e}", file=sys.stderr)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    www, files = argv
    for name in SCRIPTS:
        src = os.path.join(files, name)
        if not os.path.isfile(src):
            print(f"www-patch.py: {src} missing", file=sys.stderr)
            return 1
        shutil.copyfile(src, os.path.join(www, name))
        for ext in (".br", ".gz"):
            if os.path.exists(os.path.join(www, name + ext)):
                os.remove(os.path.join(www, name + ext))
    try:
        for name, fn in (("index.html", patch_index), ("boot.js", patch_boot)):
            p = os.path.join(www, name)
            with open(p, encoding="utf-8") as f:
                old = f.read()
            new = fn(old)
            if new != old:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(new)
                print(f"  {name}: edited")
            # a precompressed copy of the old file would be served instead (static_site.rs)
            for ext in (".br", ".gz"):
                if os.path.exists(p + ext):
                    os.remove(p + ext)
    except (OSError, ValueError) as e:
        print(f"www-patch.py: {e}", file=sys.stderr)
        install_page_layer(www, files)   # the page layer does not depend on the edits above
        return 1
    print(f"  {len(SCRIPTS)} scripts copied (own game files, download sections)")
    install_page_layer(www, files)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
