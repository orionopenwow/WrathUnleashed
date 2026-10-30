#!/usr/bin/env python3
"""Turn on Leyline's own updates: everything "Turn on launcher updates.bat" does, on the owner's PC.

    py -3 tools\\launcher-updates\\launcher_updates.py [--new-key]

The launcher updates itself from GitHub releases of the PUBLIC repo orionopenwow/Leyline. Each release is signed
with an updater key; the launcher checks downloads against the matching public key in
launcher/src-tauri/tauri.conf.json. This makes that key pair, once:

1. `npx @tauri-apps/cli signer generate` makes the pair in a throwaway folder (outside the repo), with a random
   password.
2. The private key and its password go straight into the Leyline repo's GitHub Actions secrets
   (TAURI_SIGNING_PRIVATE_KEY, TAURI_SIGNING_PRIVATE_KEY_PASSWORD) through `gh secret set`, fed on stdin: never
   printed, never in a command line, never saved in the repo. The throwaway folder is wiped.
3. The PUBLIC key is written into launcher/src-tauri/tauri.conf.json (plugins.updater.pubkey) for the next Ship,
   and kept as the repo variable TAURI_UPDATER_PUBKEY so running this again can put it back.

Safe to run again: when the secret is already there it only puts the public key back. A new key (--new-key) is
only for a lost or leaked key: launchers already installed with the old key can't update themselves to a release
signed with a new one (their players download the new version once from the release page).

Exit codes: 0 ok, 1 stopped (nothing half-done: the secrets are set before the file is changed). Standard library.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONF = ROOT / "launcher" / "src-tauri" / "tauri.conf.json"
REPO = "orionopenwow/Leyline"
SECRET_KEY = "TAURI_SIGNING_PRIVATE_KEY"
SECRET_PASS = "TAURI_SIGNING_PRIVATE_KEY_PASSWORD"
VAR_PUB = "TAURI_UPDATER_PUBKEY"
NOT_OWNER = ("chumpton",)
PUBKEY_RE = re.compile(r"^[A-Za-z0-9+/=]{80,400}$")


class Fail(Exception):
    pass


def say(*a):
    print(*a, flush=True)


class Runner:
    """Runs a command; `stdin` bytes are fed to it and never echoed. Returns (code, stdout text)."""

    def run(self, args, stdin: bytes | None = None, cwd=None):
        exe = shutil.which(args[0]) or args[0]
        try:
            p = subprocess.run([exe, *args[1:]], input=stdin, capture_output=True, cwd=cwd, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as e:
            return 1, str(e)
        return p.returncode, p.stdout.decode("utf-8", "replace")


def pubkey_ok(s: str) -> bool:
    return bool(PUBKEY_RE.match(s.strip()))


def read_conf(path: Path = CONF) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_pubkey(pub: str, path: Path = CONF) -> bool:
    """Puts the public key in tauri.conf.json. True when the file changed."""
    conf = read_conf(path)
    upd = conf.setdefault("plugins", {}).setdefault("updater", {})
    if upd.get("pubkey") == pub:
        return False
    upd["pubkey"] = pub
    upd.setdefault("windows", {"installMode": "passive"})
    path.write_text(json.dumps(conf, indent=2) + "\n", encoding="utf-8", newline="\n")
    return True


def wipe(d: Path) -> None:
    for p in d.rglob("*"):
        if p.is_file():
            try:
                p.write_bytes(b"\0" * p.stat().st_size)
            except OSError:
                pass
    shutil.rmtree(d, ignore_errors=True)


def generate(r: Runner) -> tuple[bytes, str, str]:
    """A new key pair: (private key file bytes, its password, public key)."""
    password = secrets.token_urlsafe(32)
    tmp = Path(tempfile.mkdtemp(prefix="leyline-signer-"))
    try:
        key = tmp / "leyline-updater.key"
        rc, out = r.run(["npx", "--yes", "@tauri-apps/cli@2", "signer", "generate", "--ci", "--force",
                         "--write-keys", str(key), "--password", password])
        if rc != 0 or not key.is_file() or not Path(str(key) + ".pub").is_file():
            raise Fail("Could not make the key with the Tauri CLI (npx). Is Node.js installed? "
                       "https://nodejs.org (then run this again).")
        private = key.read_bytes().strip()
        pub = Path(str(key) + ".pub").read_text(encoding="utf-8").strip()
        if not pubkey_ok(pub) or not private:
            raise Fail("The Tauri CLI made a key Leyline can't read. Nothing was stored.")
        return private, password, pub
    finally:
        wipe(tmp)


def main(argv=None, r: Runner | None = None, conf: Path = CONF) -> int:
    ap = argparse.ArgumentParser(description="Turn on Leyline's own updates (signing key into GitHub secrets).")
    ap.add_argument("--new-key", action="store_true", help="replace the key (only for a lost or leaked one)")
    a = ap.parse_args(argv)
    r = r or Runner()
    try:
        for tool, hint in (("gh", "The GitHub CLI is missing: winget install GitHub.cli   then: gh auth login"),
                           ("npx", "Node.js is missing: https://nodejs.org (LTS), then run this again")):
            if r.run([tool, "--version"])[0] != 0:
                raise Fail(hint)
        say("[1/4] GitHub sign-in")
        rc, who = r.run(["gh", "api", "user", "--jq", ".login"])
        who = who.strip()
        if rc != 0 or not who:
            raise Fail("Not signed in to the GitHub CLI. Run once: gh auth login  (as orionopenwow)")
        if who.lower() in NOT_OWNER:
            raise Fail(f"The GitHub CLI is signed in as {who}. Leyline's keys are the owner's: gh auth switch")
        say(f"  signed in as {who}")
        if r.run(["gh", "repo", "view", REPO, "--json", "name"])[0] != 0:
            raise Fail(f"{REPO} is not on GitHub yet: run the Leyline step (Update Leyline repo.bat) first.")

        say("[2/4] Is there a key already?")
        rc, out = r.run(["gh", "secret", "list", "-R", REPO, "--json", "name"])
        if rc != 0:
            raise Fail(f"Could not read {REPO}'s secrets (gh needs admin rights on it).")
        have_secret = f'"{SECRET_KEY}"' in out
        rc, out = r.run(["gh", "variable", "get", VAR_PUB, "-R", REPO])
        known_pub = out.strip() if rc == 0 and pubkey_ok(out) else ""
        if have_secret and not a.new_key:
            if not known_pub:
                raise Fail(f"{REPO} has a signing key but no {VAR_PUB} variable, so its public key is unknown here. "
                           "If no signed release is out yet, run this again with --new-key. Otherwise ask Claude.")
            say("  the signing key is already in GitHub: putting its public key back in tauri.conf.json")
            changed = write_pubkey(known_pub, conf)
            say("  tauri.conf.json " + ("updated" if changed else "already has it"))
            say("\nLAUNCHER UPDATES OK (already on)")
            return 0

        say("[3/4] Making the key pair (in a throwaway folder)")
        private, password, pub = generate(r)
        say("  storing the private key and its password as GitHub secrets (never shown)")
        for name, value in ((SECRET_KEY, private), (SECRET_PASS, password.encode())):
            rc, _ = r.run(["gh", "secret", "set", name, "-R", REPO, "--app", "actions"], stdin=value)
            if rc != 0:
                raise Fail(f"Could not store the secret {name} in {REPO}. Nothing was changed in tauri.conf.json; "
                           "run this again.")
        del private, password
        rc, _ = r.run(["gh", "variable", "set", VAR_PUB, "-R", REPO], stdin=pub.encode())
        if rc != 0:
            say(f"  (could not keep the public key as the variable {VAR_PUB}; it is still in tauri.conf.json)")

        say("[4/4] The public key into launcher/src-tauri/tauri.conf.json")
        write_pubkey(pub, conf)
        say("  done. It goes out with the next Ship and Leyline steps.")
        say()
        say("Next, in this order:")
        say("  1. Ship (Autopilot step 'ship'): commits tauri.conf.json with the public key.")
        say("  2. Leyline (Autopilot step 'leyline'): copies the launcher to the public Leyline repo.")
        say("  3. Turn on GitHub builds.bat: pushes the tag launcher-v<version>; GitHub builds the signed release.")
        say("\nLAUNCHER UPDATES OK")
        return 0
    except Fail as e:
        say(f"\nProblem: {e}")
        say("LAUNCHER UPDATES FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
