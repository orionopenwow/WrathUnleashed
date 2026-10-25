"""Host setup and small admin commands. Runs inside the tools container with the kit folder at
/kit (so the host's PC needs Docker only, no Python).

  python -m wuhost.setup init --name "Frost Haven" --profile main --visibility private
         [--image ghcr.io/... --tag stable] [--relay relay.openvanilla.app] [--site https://openvanilla.app]
         [--bots 40]
  python -m wuhost.setup show                       the invite link, login, status (plain text)
  python -m wuhost.setup get                        earlier answers as KEY=VALUE (for the .bat)
  python -m wuhost.setup friend NAME [PASSWORD]     SQL for a friend's account (piped into mysql)
  python -m wuhost.setup new-invite                 a new invite secret (old links stop working)
  python -m wuhost.setup visibility public|private
  python -m wuhost.setup claim TOKEN                the token the website gave your Hero Key account
  python -m wuhost.setup signup invite|open|off     who may make accounts from the join page
  python -m wuhost.setup rules                      re-read state/rules.txt and state/beacon.json (the
                                                    realm list text) after you edited them
  python -m wuhost.setup init --seed state/seed.b64 a realm made on the website (/wrath/host): its key,
                                                    links, claim token and answers, from the per-realm
                                                    download (base64 JSON). Used once, then deleted.

Re-running init keeps the realm key, passwords and invite (it only changes what you pass), so
running "Host a Wrath realm" again is always safe.
"""
import argparse
import base64
import json
import os
import re
import secrets
import string
import sys

from wunet import domains, keys, srp6

KIT = os.environ.get("WU_KIT", "/kit")
STATE = os.path.join(KIT, "state")
NAME_RE = re.compile(r"^[A-Za-z0-9 _'-]{1,32}$")
GM_RE = re.compile(r"^[A-Za-z0-9]{3,16}$")
PROFILES = {"main": "WrathUnleashed main: normal Wrath from level 1, or a one-time boost to 80",
            "brawl": "Brawl: everyone starts at 80 in Dalaran with everything unlocked",
            "progression": "Progression: blizzlike 1x, Vanilla then TBC then Wrath per character",
            "dalaran": "Dalaran hangout: light on your PC, no bots, boost to 80 straight to Dalaran"}
# Per-profile settings for .env (docker-compose.host.yml): a Dalaran hangout runs on a small PC.
PROFILE_ENV = {"dalaran": {"WU_DB_BUFFER": "256M", "WU_PLAYER_LIMIT": "40"}}
PROFILE_BOTS = {"dalaran": 0}
# The text the realm list and the join page show; the host edits these two files (then: Realm tools > rules).
EDITABLE = ("tagline", "summary", "type", "discord")
DEFAULT_RULES = {"dalaran": [
    "Be kind: no harassment, hate speech or spam.",
    "Duel anyone who agrees; no griefing in Dalaran.",
    "No cheats, bots or exploits. Report bugs with .bug",
    "The host's word is final: the host is the GM here.",
]}
DEFAULT_TAGLINE = {"dalaran": "A Dalaran hangout: boost to 80, duel, queue, meet."}
RULES_HELP = ("# Your realm's rules: one per line (up to 10, 120 characters each). Lines starting with # are\n"
              "# ignored. Shown on the realm list and your join page. After editing: Realm tools > rules.\n")
ALNUM = string.ascii_uppercase + string.digits
B32 = "ABCDEFGHJKMNPQRSTVWXYZ23456789"


SECRET_RE = re.compile(r"^[A-Z2-9]{16,40}$")
CLAIM_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def read_seed(rel):
    """The website's per-realm seed (base64 of a JSON object), checked field by field; None when the
    file is not there (already used). It never holds a password or an account: only this realm's own
    key, its invite and host links, the claim token for the host's Hero Key account and the answers."""
    p = rel if os.path.isabs(rel) else os.path.join(KIT, rel)
    try:
        with open(p, encoding="ascii") as f:
            doc = json.loads(base64.b64decode("".join(f.read().split()), validate=True).decode("utf-8"))
    except OSError:
        return None
    except (ValueError, UnicodeDecodeError):
        sys.exit("The realm file from the website is damaged: download it again.")
    ok = (isinstance(doc, dict) and doc.get("v") == 1 and isinstance(doc.get("realm_key"), str)
          and re.fullmatch(r"[0-9a-f]{64}", doc["realm_key"])
          and all(isinstance(doc.get(k), str) and SECRET_RE.match(doc[k]) for k in ("invite_secret", "host_secret"))
          and (doc.get("claim") is None or (isinstance(doc["claim"], str) and CLAIM_RE.match(doc["claim"])))
          and isinstance(doc.get("name"), str) and NAME_RE.match(doc["name"])
          and doc.get("profile") in PROFILES and doc.get("visibility") in ("public", "private")
          and isinstance(doc.get("gm_name"), str) and GM_RE.match(doc["gm_name"])
          and isinstance(doc.get("tagline", ""), str)
          and isinstance(doc.get("rules", []), list) and all(isinstance(r, str) for r in doc.get("rules", [])))
    if not ok:
        sys.exit("The realm file from the website is damaged: download it again.")
    if keys.realm_id(keys.public_key(bytes.fromhex(doc["realm_key"]))) != doc.get("realm_id"):
        sys.exit("The realm file from the website does not match its realm id: download it again.")
    doc["_path"] = p
    return doc


def apply_seed(seed, a, cfg):
    """Put the seed's realm key in state/realm.key (refused when this kit already holds another realm)
    and use its answers wherever this run did not pass its own."""
    kp = path("realm.key")
    want = bytes.fromhex(seed["realm_key"])
    if os.path.exists(kp):
        if keys.load_or_create(kp) != want:
            sys.exit("This kit folder already hosts another realm (state/realm.key). "
                     "Use a fresh copy of the host kit for this one.")
    else:
        os.makedirs(STATE, exist_ok=True)
        fd = os.open(kp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(want.hex() + "\n")
    for k in ("name", "profile", "visibility", "gm_name"):
        if getattr(a, k) is None and not cfg.get(k):
            setattr(a, k, seed[k])
    if a.tagline is None and seed.get("tagline") and not (cfg.get("record") or {}).get("tagline"):
        a.tagline = seed["tagline"]
    cfg.setdefault("invite_secret", seed["invite_secret"])
    cfg.setdefault("host_secret", seed["host_secret"])
    if seed.get("claim") and not cfg.get("claim"):
        cfg["claim"] = seed["claim"]
    if not os.path.exists(path("rules.txt")) and seed.get("rules"):
        with open(path("rules.txt"), "w", encoding="utf-8") as f:
            f.write(RULES_HELP + "".join(" ".join(r.split())[:120] + "\n" for r in seed["rules"][:10] if r.strip()))


def gen(n, alphabet=ALNUM):
    return "".join(secrets.choice(alphabet) for _ in range(n))


def path(*p):
    return os.path.join(STATE, *p)


def load():
    try:
        with open(path("host.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save(cfg):
    os.makedirs(STATE, exist_ok=True)
    tmp = path("host.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1, sort_keys=True)
    os.replace(tmp, path("host.json"))


def write_private(name, text):
    p = path(name)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def invite_link(cfg):
    base = f"{cfg.get('join_base') or cfg['site']}/join/{cfg['realm_id']}"
    return base + (f"#{cfg['invite_secret']}" if cfg["visibility"] == "private" else "")


def host_link(cfg):
    """The host's own join link: the invite plus the host key, so the host (only) can make the GM
    account from the join page. Never shared."""
    return f"{cfg.get('join_base') or cfg['site']}/join/{cfg['realm_id']}#{cfg['invite_secret']}~{cfg['host_secret']}"


def write_links(cfg):
    with open(path("invite.txt"), "w", encoding="utf-8") as f:
        f.write(invite_link(cfg) + "\n")
    if cfg.get("host_secret"):
        write_private("host-link.txt", host_link(cfg) + "\n")


def read_rules():
    """state/rules.txt: one rule per line; None when the file is not there."""
    try:
        with open(path("rules.txt"), encoding="utf-8-sig") as f:
            lines = [ln.strip() for ln in f]
    except OSError:
        return None
    return [ln[:120] for ln in lines if ln and not ln.startswith("#")][:10]


def read_beacon_edits():
    """The fields the host may edit in state/beacon.json (name and ruleset come from setup)."""
    try:
        with open(path("beacon.json"), encoding="utf-8-sig") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: doc[k] for k in EDITABLE if isinstance(doc, dict) and k in doc} if isinstance(doc, dict) else {}


def beacon_record(cfg):
    """What the listing will show (it rebuilds the rest itself); kept in state/beacon.json so the
    host can see and edit the text (tagline, summary, type, discord), and the rules in state/rules.txt."""
    rec = cfg.get("record") or {}
    rec.update(read_beacon_edits())
    rules = read_rules()
    if rules is not None:
        rec["rules"] = rules
    if not rec.get("tagline"):
        rec["tagline"] = DEFAULT_TAGLINE.get(cfg["profile"], "")
    rec.setdefault("tagline", "")
    rec.setdefault("summary", "")
    rec.setdefault("rules", [])
    rec.setdefault("discord", None)
    rec.update(name=cfg["name"], type=rec.get("type", "PvE"), ruleset=cfg["profile"],
               warden=cfg["warden"])
    return rec


def write_env(cfg, image, tag, tools_image):
    env = {"WU_IMAGE": image, "WU_TAG": tag, "DB_ROOT_PASSWORD": cfg["db_password"], "WU_PROFILE": cfg["profile"],
           "WU_WARDEN": "1" if cfg["warden"] else "0", "WU_BOTS": str(cfg["bots"]), "WU_TOOLS_IMAGE": tools_image,
           "COMPOSE_PROJECT_NAME": "wu-host"}
    for k in ("WU_UID", "WU_GID"):   # Linux/macOS: the agent writes state/ as the host's own user
        if os.environ.get(k, "").isdigit():
            env[k] = os.environ[k]
    keep = {}
    try:
        with open(os.path.join(KIT, ".env"), encoding="utf-8") as f:
            for ln in f:
                if "=" in ln and not ln.startswith("#"):
                    k, v = ln.rstrip("\r\n").split("=", 1)
                    keep[k] = v
    except OSError:
        pass
    for prof_env in PROFILE_ENV.values():   # another profile's settings go when the profile changes
        for k, v in prof_env.items():
            if keep.get(k) == v and k not in PROFILE_ENV.get(cfg["profile"], {}):
                del keep[k]
    keep.update(PROFILE_ENV.get(cfg["profile"], {}))
    keep.update(env)
    fd = os.open(os.path.join(KIT, ".env"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Written by Host a Wrath realm. Keep it private: it holds the database password.\n")
        for k in sorted(keep):
            f.write(f"{k}={keep[k]}\n")


def cmd_init(a):
    cfg = load() or {}
    seed = read_seed(a.seed) if getattr(a, "seed", None) else None
    if seed:
        if cfg.get("realm_id") and cfg["realm_id"] != seed["realm_id"]:
            sys.exit("This kit folder already hosts another realm (state/host.json). "
                     "Use a fresh copy of the host kit for this one.")
        apply_seed(seed, a, cfg)
    name = a.name if a.name is not None else cfg.get("name")
    if not name or not NAME_RE.match(name.strip()):
        sys.exit("Realm name: 1-32 letters, digits, spaces, _ ' or -")
    profile = a.profile or cfg.get("profile", "main")
    if profile not in PROFILES:
        sys.exit("Profile must be main, brawl, progression or dalaran")
    vis = a.visibility or cfg.get("visibility", "private")
    if vis not in ("public", "private"):
        sys.exit("Choose private or public")
    os.makedirs(STATE, exist_ok=True)
    secret = keys.load_or_create(path("realm.key"))
    rid = keys.realm_id(keys.public_key(secret))
    first = not cfg
    relay = a.relay or cfg.get("relay", domains.RELAY)
    cfg.update(
        realm_id=rid, name=name.strip(), profile=profile, visibility=vis,
        relay=relay, site=(a.site or cfg.get("site", domains.SITE)).rstrip("/"),
        # Join pages are served by the relay itself (https://<relay>/join/<id>): no website needed.
        join_base=(a.join_base or (f"https://{a.relay}" if a.relay else None) or cfg.get("join_base")
                   or (domains.JOIN if relay == domains.RELAY else f"https://{relay}")).rstrip("/"),
        relay_url=a.relay_url or f"wss://{relay}/agent",
        listing_url=a.listing_url or f"https://{relay}/api/listing/heartbeat",
        auth_service="ac-authserver:3724", world_service="ac-worldserver:8085",
        # Warden: stock clients on a public realm get the core's anti-cheat; a friends' realm leaves
        # it off so the WrathUnleashed browser/desktop client (no Warden module) can join too.
        warden=(vis == "public") if a.warden is None else a.warden == "on",
        bots=(a.bots if a.bots is not None
              else cfg["bots"] if cfg.get("profile") == profile and "bots" in cfg
              else PROFILE_BOTS.get(profile, 40)),
        # A listed realm is for strangers, so its join page makes accounts ("open"); a friends' realm
        # only from the invite link. An explicit --signup (or an earlier choice) wins.
        signup=a.signup or cfg.get("signup") or ("open" if vis == "public" else "invite"),
    )
    cfg.setdefault("invite_secret", gen(20, B32))
    cfg.setdefault("host_secret", gen(24, B32))   # only in the host's own link (state/host-link.txt)
    cfg.setdefault("db_password", gen(24))
    if a.gm_name is not None:
        if not GM_RE.match(a.gm_name):
            sys.exit("GM account name: 3-16 letters or digits")
        cfg["gm_name"] = a.gm_name.upper()
    if a.tagline is not None:
        cfg.setdefault("record", {})["tagline"] = " ".join(a.tagline.split())[:80]
        b = read_beacon_edits()
        if b:   # beacon.json is the host's copy of the text: keep it in step
            b_full = json.load(open(path("beacon.json"), encoding="utf-8-sig"))
            b_full["tagline"] = cfg["record"]["tagline"]
            with open(path("beacon.json"), "w", encoding="utf-8") as f:
                json.dump(b_full, f, indent=1)
    if "gm" not in cfg and not cfg.get("gm_name"):
        # Legacy kit flow (Host a Wrath realm.bat): a generated GM login. The leyline command never
        # does this: it asks for the operator's account name and they make the account themselves.
        user, pw = "HOST" + gen(4), gen(12)
        salt, ver = srp6.make_verifier(user, pw)
        cfg["gm"] = {"username": user, "salt": salt.hex(), "verifier": ver.hex()}
        write_private("host-login.txt", f"Your own game login on your realm (a GM account):\n"
                                        f"  account:  {user}\n  password: {pw}\n")
    if not os.path.exists(path("rules.txt")):
        with open(path("rules.txt"), "w", encoding="utf-8") as f:
            f.write(RULES_HELP + "".join(r + "\n" for r in DEFAULT_RULES.get(profile, [])))
    cfg["record"] = beacon_record(cfg)
    save(cfg)
    write_beacon(cfg)
    write_env(cfg, a.image, a.tag, a.tools_image)
    write_links(cfg)
    if seed:   # used: the key and links live in state/ now
        try:
            os.remove(seed["_path"])
        except OSError:
            pass
    print(json.dumps({"realm_id": rid, "first_run": first, "invite": invite_link(cfg)}))


def write_beacon(cfg):
    with open(path("beacon.json"), "w", encoding="utf-8") as f:
        json.dump(cfg["record"], f, indent=1)


def cmd_show(a):
    cfg = load()
    if not cfg:
        sys.exit("This PC is not hosting a realm yet: run Host a Wrath realm first.")
    rs = {}
    try:
        with open(path("relay-state.json"), encoding="utf-8") as f:
            rs = json.load(f)
    except (OSError, ValueError):
        pass
    print(f"Realm:      {cfg['name']}  ({cfg['profile']}, {cfg['visibility']})")
    print(f"Realm id:   {cfg['realm_id']}")
    print(f"Invite:     {invite_link(cfg)}")
    rules = (cfg.get("record") or {}).get("rules") or []
    print(f"Rules:      {len(rules)} line(s), from state/rules.txt" + (f" (first: {rules[0]})" if rules else ""))
    if cfg["visibility"] == "private":
        print("            Only people with this link can join. Keep the part after # private.")
    else:
        print("            Public: listed in Beacons (unclaimed until you claim it with your Hero Key).")
    if rs.get("connected"):
        print(f"Relay:      connected. Players' realmlist: {realmlist_line(cfg, rs)}")
    else:
        print(f"Relay:      not connected yet{(' (' + rs['last_error'] + ')') if rs.get('last_error') else ''}")
    if cfg.get("gm_name"):
        ok = rs.get("gm_ok") and rs.get("gm_account") == cfg["gm_name"]
        print(f"GM account: {cfg['gm_name']}  " + (
            "(has GM rights on this realm)" if ok else
            "(not made yet: open your own link below and make this account with your own password; "
            "it gets GM rights by itself)"))
        if cfg.get("host_secret"):
            print(f"Your link:  {host_link(cfg)}")
            print("            Yours only (it can make the GM account). Friends get the invite link above.")
        return
    try:
        with open(path("host-login.txt"), encoding="utf-8") as f:
            print(f.read().rstrip())
    except OSError:
        pass


def read_relay_state():
    try:
        with open(path("relay-state.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def realmlist_line(cfg, rs):
    """What players type. The shared port 3724 works only where the relay runs it (off on a box whose
    own authserver has 3724); otherwise the realm's own relay port."""
    if rs.get("shared_auth_port") == 3724:
        return f"set realmlist {cfg['relay']}   (or {cfg['relay']}:{rs.get('auth_port')})"
    if rs.get("auth_port"):
        return f"set realmlist {cfg['relay']}:{rs['auth_port']}"
    return "(shown once the realm is connected to the relay)"


def cmd_realmlist(a):
    cfg = load()
    if cfg:
        print(realmlist_line(cfg, read_relay_state()).split("   ")[0])


def cmd_gm(a):
    """Name the account that gets GM rights. The operator makes that account; nothing is created here."""
    if not GM_RE.match(a.name):
        sys.exit("GM account name: 3-16 letters or digits")
    _edit(lambda c: c.update(gm_name=a.name.upper()))


def cmd_get(a):
    """Earlier answers as KEY=VALUE lines (for the .bat's defaults); nothing when not set up yet."""
    cfg = load() or {}
    for k, var in (("name", "WU_OLD_NAME"), ("profile", "WU_OLD_PROFILE"), ("visibility", "WU_OLD_VIS")):
        if cfg.get(k):
            print(f"{var}={cfg[k]}")


def cmd_friend(a):
    """SQL that makes a friend's account; the .bat pipes it into the database container."""
    user = a.name.upper()
    if not re.match(r"^[A-Z0-9]{3,16}$", user):
        sys.exit("Account names: 3-16 letters or digits")
    pw = (a.password or gen(10)).upper()
    salt, ver = srp6.make_verifier(user, pw)
    sys.stderr.write(f"Account for your friend:  {user}  password: {pw}\n")
    print(f"INSERT INTO account (username, salt, verifier, expansion) VALUES ('{user}', 0x{salt.hex()}, 0x{ver.hex()}, 2);")


def _edit(fn):
    cfg = load()
    if not cfg:
        sys.exit("Run Host a Wrath realm first.")
    fn(cfg)
    cfg["record"] = beacon_record(cfg)
    save(cfg)
    write_beacon(cfg)
    write_links(cfg)
    print(invite_link(cfg))


def cmd_new_invite(a):
    _edit(lambda c: c.update(invite_secret=gen(20, B32)))


def cmd_visibility(a):
    _edit(lambda c: c.update(visibility=a.visibility))


def cmd_claim(a):
    if not re.match(r"^[A-Za-z0-9_-]{16,64}$", a.token):
        sys.exit("That doesn't look like a claim token (copy it from the website).")
    _edit(lambda c: c.update(claim=a.token))


def cmd_signup(a):
    _edit(lambda c: c.update(signup=a.mode))


def cmd_rules(a):
    """Re-read state/rules.txt and state/beacon.json; the agent sends the new text with its next heartbeat."""
    _edit(lambda c: None)
    rec = load()["record"]
    sys.stderr.write(f"Realm list text updated: {len(rec.get('rules') or [])} rule(s), tagline: {rec.get('tagline') or '(none)'}\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="WrathUnleashed host setup")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--name")
    p.add_argument("--profile", choices=sorted(PROFILES))
    p.add_argument("--visibility", choices=["public", "private"])
    p.add_argument("--image", default="ghcr.io/orionopenwow/wu-ac-wotlk")
    p.add_argument("--tag", default="stable")
    p.add_argument("--tools-image", default="wu-host-tools:1")
    p.add_argument("--relay")
    p.add_argument("--site")
    p.add_argument("--bots", type=int)
    p.add_argument("--relay-url", help="override wss://<relay>/agent (tests, self-hosted relays)")
    p.add_argument("--listing-url", help="override https://<relay>/api/listing/heartbeat")
    p.add_argument("--warden", choices=["on", "off"])
    p.add_argument("--join-base", help="where join pages live (default https://<relay>)")
    p.add_argument("--gm-name", help="the operator's own account name that gets GM rights (they make it)")
    p.add_argument("--tagline", help="one line for the realm list")
    p.add_argument("--signup", choices=["invite", "open", "off"])
    p.add_argument("--seed", help="the per-realm file from the website's host page (state/seed.b64)")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("gm")
    p.add_argument("name")
    p.set_defaults(fn=cmd_gm)
    sub.add_parser("realmlist").set_defaults(fn=cmd_realmlist)
    sub.add_parser("show").set_defaults(fn=cmd_show)
    sub.add_parser("get").set_defaults(fn=cmd_get)
    p = sub.add_parser("friend")
    p.add_argument("name")
    p.add_argument("password", nargs="?")
    p.set_defaults(fn=cmd_friend)
    sub.add_parser("new-invite").set_defaults(fn=cmd_new_invite)
    p = sub.add_parser("visibility")
    p.add_argument("visibility", choices=["public", "private"])
    p.set_defaults(fn=cmd_visibility)
    p = sub.add_parser("claim")
    p.add_argument("token")
    p.set_defaults(fn=cmd_claim)
    p = sub.add_parser("signup")
    p.add_argument("mode", choices=["invite", "open", "off"])
    p.set_defaults(fn=cmd_signup)
    sub.add_parser("rules").set_defaults(fn=cmd_rules)
    a = ap.parse_args(argv)
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
