#!/usr/bin/env python3
"""Add "Play with my own game files" (ownfiles.js) and "Download this section" (sections.js) to a
browser client build in place: copies the six scripts from www-files/ and edits index.html and
boot.js by anchors (the same edits as www-files/web.patch), so it works on the build you uploaded
whatever small differences its page has. Safe to run again (already-edited files are left alone).

    python3 -I www-patch.py <www folder> <www-files folder>
"""
import os
import shutil
import sys

SCRIPTS = ["ownfiles.js", "ownfiles-worker.js", "mpq.js", "chain.js", "sections.js", "sections-worker.js"]

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
        return 1
    print(f"  {len(SCRIPTS)} scripts copied (own game files, download sections)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
