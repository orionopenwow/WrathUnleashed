"""Host any client: the host kit's realm profiles on server cores other than AzerothCore.

One table, read by setup.py (profile names, listing core/build, the agent's services), the agent and the
self-check (which database class, coredb.py), the generic host steps (profiles/host-profile.sh reads the
same facts from profiles/<id>/profile.lock) and checked against the launcher's own table by the hosting tests
(launcher/src-tauri/src/host/profiles.rs).

Every profile here is built on the host's PC from its authors' public source at a pinned commit; its server
data is extracted from the host's OWN client of that build (read-only), its database is the core's own
community SQL. Nothing of the game is downloaded. The 3.3.5a profiles (main, brawl, progression, dalaran)
stay in setup.py: they run on the kit's default compose file.
"""

# Service names inside every profile's compose file (profiles/<id>/docker-compose.<id>.yml).
LOGON, WORLD = "realm-logon:3724", "realm-world:8085"

PROFILES = {
    "cmangos-1.12.1": {
        "core": "cmangos", "build": 5875, "version": "1.12.1",
        "label": "1.12.1 realm (CMaNGOS Classic): for the 1.12 client",
        "databases": {"auth": "classicrealmd", "chars": "classiccharacters", "world": "classicmangos",
                      "logs": "classiclogs"},
        "expansion": 0,
        "tags": ["blizzlike"],
        "tagline": "A 1.12 realm: play it with your own 1.12 client.",
    },
    "cmangos-2.4.3": {
        "core": "cmangos", "build": 8606, "version": "2.4.3",
        "label": "2.4.3 realm (CMaNGOS TBC): for the 2.4.3 client",
        "databases": {"auth": "tbcrealmd", "chars": "tbccharacters", "world": "tbcmangos", "logs": "tbclogs"},
        "expansion": 1,
        "tags": ["blizzlike"],
        "tagline": "A 2.4.3 realm: play it with your own 2.4.3 client.",
    },
    "tcpp-4.3.4": {
        "core": "trinitycore", "build": 15595, "version": "4.3.4",
        "label": "4.3.4 realm (TrinityCore, the 4.3.4 preservation fork): for the 4.3.4 client",
        "databases": {"auth": "auth", "chars": "characters", "world": "world", "hotfixes": "hotfixes"},
        "expansion": 3,
        "tags": ["blizzlike"],
        "tagline": "A 4.3.4 realm: play it with your own 4.3.4 client.",
    },
}

# The client builds the kit's login probe knows (wunet/wire335.VERSIONS has the version bytes).
BUILDS = {5875: "1.12.1", 8606: "2.4.3", 12340: "3.3.5a", 15595: "4.3.4", 18414: "5.4.8"}


def get(profile):
    """The profile's facts, or None for the kit's own 3.3.5a profiles."""
    return PROFILES.get(profile)


def services(profile, default=("ac-authserver:3724", "ac-worldserver:8085")):
    return (LOGON, WORLD) if profile in PROFILES else default


def core_build(profile, default):
    p = PROFILES.get(profile)
    return (p["core"], p["build"]) if p else default


def version(build):
    return BUILDS.get(build, "3.3.5a")
