//! Realms: the official realm and the community Beacons the relay lists (`/api/listing/realms.json`,
//! hosting/relay/wurelay/listing.py), cached for offline use; plus the two relay calls a desktop client needs.
//!
//! How a stock desktop client reaches a Beacon: the relay gives every realm its own pair of TCP ports
//! (auth, world = auth + 1). `set realmlist <relay>:<auth port>` reaches that realm's login server, and the
//! realm advertises `<relay>:<world port>` in its realm list, so the client comes back through the relay.
//! A listing record carries that address (`profile.address` + `profile.port`); `GET /api/realms/<id>`
//! gives it too. A private realm only lets in an internet address that opened its invite link, which is
//! what the invite knock (`POST /api/realms/<id>/knock {"invite"}`) does. Accounts are made on the realm's
//! join page in the browser (the password never leaves it), so the launcher only opens that page.

use crate::clients::{Build, ClientProfile};
use crate::net::{self, Listing};
use serde::Serialize;
use serde_json::Value;
use std::path::{Path, PathBuf};
use std::time::Duration;

pub const URL: &str = "https://relay.openvanilla.app/api/listing/realms.json";
pub const RELAY: &str = "relay.openvanilla.app";
pub const LOOKUP_TIMEOUT: Duration = Duration::from_secs(8);

/// One realm as the Realms page shows it.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Realm {
    /// `official` or `c-<realm id>`.
    pub slug: String,
    pub name: String,
    pub official: bool,
    pub tagline: String,
    pub summary: String,
    /// PvE, PvP, RP, RP-PvP, Fun.
    pub kind: String,
    pub ruleset: String,
    /// `live` or `offline`.
    pub state: String,
    pub version: String,
    /// What a desktop client's realmlist gets (`host` or `host:port`), when known.
    pub address: Option<String>,
    pub relay: Option<String>,
    pub realm_id: Option<String>,
    pub players: Option<u64>,
    pub bots: Option<u64>,
    pub status_url: Option<String>,
    /// The realm's join page (make an account there).
    pub join_url: Option<String>,
    pub discord: Option<String>,
    pub rules: Vec<String>,
    pub claimed: bool,
    /// The server software: `azerothcore`, `trinitycore`, `cmangos`, `vmangos`, `mangos` or `other`.
    pub core: String,
    /// The client build the realm takes, when known.
    pub build: Option<Build>,
}

/// The server cores Leyline names, as (tag, label).
pub const CORES: &[(&str, &str)] = &[
    ("azerothcore", "AzerothCore"),
    ("trinitycore", "TrinityCore"),
    ("cmangos", "CMaNGOS"),
    ("vmangos", "vMaNGOS"),
    ("mangos", "MaNGOS"),
    ("other", "Other"),
];

/// A core's tag from how a listing writes it (`AzerothCore`, `azeroth-core`, `TC`, ...): `other` when unknown.
pub fn core_tag(s: &str) -> &'static str {
    let k: String = s.chars().filter(|c| c.is_ascii_alphanumeric()).collect::<String>().to_ascii_lowercase();
    match k.as_str() {
        "azerothcore" | "ac" | "acore" => "azerothcore",
        "trinitycore" | "tc" | "trinity" => "trinitycore",
        "cmangos" | "continuedmangos" => "cmangos",
        "vmangos" => "vmangos",
        "mangos" | "mangoszero" | "mangosone" | "mangostwo" | "mangosthree" => "mangos",
        _ => "other",
    }
}

pub fn core_label(tag: &str) -> &'static str {
    CORES.iter().find(|(t, _)| *t == tag).map(|(_, l)| *l).unwrap_or("Other")
}

/// The client to play `realm` with: the picked one when its build fits, else the first of the player's clients
/// that fits. A realm whose build is not known takes the picked client. Otherwise it says what is missing:
/// Leyline never downloads a client, so the player adds their own.
pub fn pick_client<'a>(realm: &Realm, clients: &'a [ClientProfile], picked: Option<&str>) -> Result<&'a ClientProfile, String> {
    let chosen = picked.and_then(|id| clients.iter().find(|c| c.id == id));
    let Some(want) = realm.build else {
        return chosen.or(clients.first()).ok_or_else(|| "Add your game client first (Game clients).".into());
    };
    if let Some(c) = chosen.filter(|c| c.build == want) {
        return Ok(c);
    }
    clients.iter().find(|c| c.build == want).ok_or_else(|| {
        let have: Vec<&str> = clients.iter().map(|c| c.build.version()).collect();
        let have = if have.is_empty() { "no clients yet".to_string() } else { format!("you have {}", have.join(", ")) };
        format!(
            "{} needs a {} client ({have}). Add your own {} install under Game clients: Leyline never downloads a client.",
            realm.name,
            want.label(),
            want.version()
        )
    })
}

#[derive(Debug, Clone, Serialize)]
pub struct RealmList {
    pub realms: Vec<Realm>,
    pub from_cache: bool,
    pub saved_at: Option<u64>,
    pub error: Option<String>,
}

/// The official WrathUnleashed realm.
pub fn official() -> Realm {
    Realm {
        slug: "official".into(),
        name: "WrathUnleashed".into(),
        official: true,
        tagline: "The official realm: 3.3.5a, bots, the Workshop's mods.".into(),
        kind: "PvE".into(),
        ruleset: "main".into(),
        state: "live".into(),
        version: "3.3.5a".into(),
        address: Some(crate::OFFICIAL_REALM.into()),
        status_url: Some(crate::status::OFFICIAL_STATUS_URL.into()),
        core: "azerothcore".into(),
        build: Some(Build::V335a),
        ..Default::default()
    }
}

/// The official realms, first on the list. Wrath (3.3.5a, AzerothCore) is the one there is today.
/// TODO(owner): the sibling Open Vanilla 1.12 realm is not in the relay's listing and its desktop address is not
/// written down anywhere in this repo; when it is, add it here (build 1.12.1, its core and its address).
pub fn officials() -> Vec<Realm> {
    vec![official()]
}

/// A realm id: 16 base32 characters (lower case a-z, 2-7), as the relay makes them.
pub fn realm_id_ok(s: &str) -> bool {
    s.len() == 16 && s.chars().all(|c| c.is_ascii_lowercase() || ('2'..='7').contains(&c))
}

/// A relay's host name: a plain DNS name (no port, no path), so `https://<it>/...` is only ever that host.
pub fn relay_ok(h: &str) -> bool {
    let parts: Vec<&str> = h.split('.').collect();
    h.len() <= 253
        && parts.len() >= 2
        && parts.iter().all(|p| !p.is_empty() && p.len() <= 63 && p.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-'))
}

fn s(v: &Value, k: &str, n: usize) -> String {
    v.get(k).and_then(Value::as_str).map(|x| x.chars().filter(|c| !c.is_control()).take(n).collect()).unwrap_or_default()
}

/// The community records of a realms.json document (schema 1). Records that are not real Beacons are dropped.
pub fn parse_community(v: &Value) -> Vec<Realm> {
    let Some(items) = v.get("realms").and_then(Value::as_array) else { return vec![] };
    items
        .iter()
        .take(2000)
        .filter_map(|r| {
            let c = r.get("community")?;
            let rid = c.get("realmId").and_then(Value::as_str).filter(|x| realm_id_ok(x))?.to_string();
            let profile = r.get("profile").cloned().unwrap_or(Value::Null);
            let relay = c.get("relay").and_then(Value::as_str).or_else(|| profile.get("address").and_then(Value::as_str))
                .filter(|h| relay_ok(h))?
                .to_string();
            let port = profile.get("port").and_then(Value::as_u64).filter(|p| (1..=65535).contains(p));
            let hb = c.get("lastHeartbeat").cloned().unwrap_or(Value::Null);
            let num = |k: &str| hb.get(k).and_then(Value::as_u64);
            let status_url = r.get("status").and_then(|st| st.get("url")).and_then(Value::as_str).map(String::from)
                .filter(|u| status_url_ok(u));
            let join_url = r.get("connect").and_then(|st| st.get("url")).and_then(Value::as_str).map(String::from)
                .filter(|u| net::plain_https(u) && *u == format!("https://{relay}/join/{rid}"));
            let state = if s(r, "state", 16) == "live" { "live" } else { "offline" };
            Some(Realm {
                slug: format!("c-{rid}"),
                name: Some(s(r, "name", 32)).filter(|n| !n.is_empty()).unwrap_or_else(|| rid.clone()),
                official: false,
                tagline: s(r, "tagline", 80),
                summary: s(r, "summary", 400),
                kind: s(r, "type", 8),
                ruleset: s(r, "ruleset", 16),
                state: state.into(),
                version: s(&profile, "version", 12),
                address: port.map(|p| format!("{relay}:{p}")),
                relay: Some(relay),
                realm_id: Some(rid),
                players: num("players"),
                bots: num("bots"),
                status_url,
                join_url,
                discord: r.get("discord").and_then(Value::as_str).filter(|u| net::plain_https(u)).map(String::from),
                rules: r
                    .get("rules")
                    .and_then(Value::as_array)
                    .map(|a| a.iter().filter_map(Value::as_str).take(10).map(|x| x.chars().take(120).collect()).collect())
                    .unwrap_or_default(),
                claimed: c.get("claimed").and_then(Value::as_bool).unwrap_or(false),
                // Beacons run the host kit, which is AzerothCore, unless the record says otherwise.
                core: core_tag(&profile.get("core").or_else(|| r.get("core")).and_then(Value::as_str).map(String::from)
                    .unwrap_or_else(|| "azerothcore".into()))
                .into(),
                build: listing_build(&profile),
            })
        })
        .collect()
}

/// The client build a listing record's profile names: its `build` number, `version` or `game` (`wrath-3.3.5a`).
pub fn listing_build(profile: &Value) -> Option<Build> {
    let num = profile.get("build").and_then(Value::as_u64).map(|n| n.to_string());
    let text = |k: &str| profile.get(k).and_then(Value::as_str).map(String::from);
    [num, text("build"), text("version"), text("game")].into_iter().flatten().find_map(|t| Build::from_tag(&t))
}

/// A relay status file's address: `https://<relay>/r/<realm id>/status.json`.
pub fn status_url_ok(u: &str) -> bool {
    let Some(rest) = u.strip_prefix("https://") else { return false };
    let mut it = rest.splitn(2, '/');
    let (Some(host), Some(path)) = (it.next(), it.next()) else { return false };
    let parts: Vec<&str> = path.split('/').collect();
    relay_ok(host) && parts.len() == 3 && parts[0] == "r" && realm_id_ok(parts[1]) && parts[2] == "status.json"
}

pub fn cache_path(app_dir: &Path) -> PathBuf {
    app_dir.join("cache").join("realms.json")
}

/// The official realm first, then every Beacon the relay lists.
pub fn fetch_all(app_dir: &Path) -> RealmList {
    fetch_all_from(URL, app_dir)
}

pub fn fetch_all_from(url: &str, app_dir: &Path) -> RealmList {
    let f = net::fetch_json(url, &cache_path(app_dir), net::TIMEOUT, |v| {
        v.get("realms").and_then(Value::as_array).map(|_| ()).ok_or_else(|| "no \"realms\" list in the reply".into())
    });
    let mut realms = officials();
    match f {
        Ok(f) => {
            realms.extend(parse_community(&f.value));
            RealmList { realms, from_cache: f.from_cache, saved_at: f.saved_at, error: f.error }
        }
        Err(e) => RealmList { realms, from_cache: false, saved_at: None, error: Some(e) },
    }
}

/// The realms as last fetched, without the network.
pub fn cached(app_dir: &Path) -> Vec<Realm> {
    let mut v = officials();
    if let Some((doc, _)) = net::read_cache(&cache_path(app_dir)) {
        v.extend(parse_community(&doc));
    }
    v
}

/// L0's count-and-names listing (still used by the side bar search).
pub fn fetch(app_dir: &Path) -> Result<Listing, String> {
    net::fetch_listing(URL, "realms", &cache_path(app_dir), net::TIMEOUT)
}

/// What `GET /api/realms/<id>` says about a relay realm.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct RelayRealm {
    pub realm_id: String,
    pub online: bool,
    pub name: String,
    pub visibility: Option<String>,
    /// `<relay>:<auth port>`: what a desktop client's realmlist gets.
    pub address: Option<String>,
    pub status_url: Option<String>,
}

/// Look a realm up on its relay. `base` is `https://<relay>` (a local server in tests).
pub fn lookup(base: &str, rid: &str) -> Result<RelayRealm, String> {
    if !realm_id_ok(rid) {
        return Err("That is not a realm id.".into());
    }
    let v = net::get_json(&format!("{base}/api/realms/{rid}"), LOOKUP_TIMEOUT)?;
    let host = v.get("address").and_then(Value::as_str).filter(|h| relay_ok(h));
    let port = v.get("auth_port").and_then(Value::as_u64).filter(|p| (1..=65535).contains(p));
    Ok(RelayRealm {
        realm_id: rid.into(),
        online: v.get("online").and_then(Value::as_bool).unwrap_or(false),
        name: s(&v, "name", 32),
        visibility: v.get("visibility").and_then(Value::as_str).map(String::from),
        address: host.zip(port).map(|(h, p)| format!("{h}:{p}")),
        status_url: v.get("status_url").and_then(Value::as_str).filter(|u| status_url_ok(u)).map(String::from),
    })
}

/// The desktop address for a listed Beacon: from the listing, or else from its relay.
pub fn desktop_address(r: &Realm, base_for: impl Fn(&str) -> String) -> Result<String, String> {
    if let Some(a) = &r.address {
        return Ok(a.clone());
    }
    let (Some(relay), Some(rid)) = (&r.relay, &r.realm_id) else {
        return Err("This realm has no address yet.".into());
    };
    lookup(&base_for(relay), rid)?.address.ok_or_else(|| "The relay did not give this realm's address.".into())
}

/// An invite link (`https://<relay>/join/<id>#<secret>` or `...#<secret>~<host secret>`) as (relay, id, secret).
pub fn parse_invite(link: &str) -> Option<(String, String, String)> {
    let rest = link.trim().strip_prefix("https://")?;
    let (host, path) = rest.split_once('/')?;
    let (path, frag) = path.split_once('#')?;
    let rid = path.strip_prefix("join/")?.trim_end_matches('/');
    let secret = frag.split('~').next()?;
    let ok = (16..=40).contains(&secret.len()) && secret.chars().all(|c| c.is_ascii_uppercase() || ('2'..='9').contains(&c));
    (relay_ok(host) && realm_id_ok(rid) && ok).then(|| (host.to_string(), rid.to_string(), secret.to_string()))
}

/// Open the door of a private realm for this PC's internet address (what the invite link does in a browser).
/// Returns the realmlist address to use.
pub fn knock(base: &str, rid: &str, invite: &str) -> Result<(String, String), String> {
    let v = net::post_json(&format!("{base}/api/realms/{rid}/knock"), &serde_json::json!({ "invite": invite }), LOOKUP_TIMEOUT)?;
    let addr = v
        .get("realmlist_port")
        .and_then(Value::as_str)
        .or_else(|| v.get("realmlist").and_then(Value::as_str))
        .filter(|a| crate::clients::valid_realm_address(a))
        .ok_or("The relay did not give an address for this realm.")?;
    Ok((addr.to_string(), s(&v, "name", 32)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::net::testserver::*;

    const RID: &str = "abcdefghijk2345a";
    const LISTING: &str = r#"{"schema":1,"kind":"community","updated":"2026-10-25T12:00:00Z","realms":[
      {"schema":1,"slug":"c-abcdefghijk2345a","name":"Frost Haven","official":false,"state":"live","tagline":"Duels all day",
       "type":"PvP","profile":{"version":"3.3.5a","address":"relay.openvanilla.app","port":40002},
       "connect":{"kind":"web-signin","url":"https://relay.openvanilla.app/join/abcdefghijk2345a"},
       "rules":["Be kind"],"discord":"https://discord.gg/abcd","status":{"url":"https://relay.openvanilla.app/r/abcdefghijk2345a/status.json"},
       "community":{"realmId":"abcdefghijk2345a","relay":"relay.openvanilla.app","claimed":true,"lastHeartbeat":{"online":true,"players":3,"bots":40}}},
      {"name":"No port yet","state":"offline","profile":{"address":"relay.openvanilla.app","port":null},
       "connect":{"url":"https://evil.example.com/join/zzzzzzzzzzzzzzzz"},
       "community":{"realmId":"zzzzzzzzzzzzzzzz","relay":"relay.openvanilla.app"}},
      {"name":"Bad id","community":{"realmId":"../../x","relay":"relay.openvanilla.app"}},
      {"name":"Bad relay","community":{"realmId":"bbbbbbbbbbbbbbbb","relay":"evil.example.com:22/x"}}
    ]}"#;

    #[test]
    fn parses_beacons_with_their_desktop_address() {
        let v: Value = serde_json::from_str(LISTING).unwrap();
        let r = parse_community(&v);
        assert_eq!(r.len(), 2);
        assert_eq!(r[0].address.as_deref(), Some("relay.openvanilla.app:40002"));
        assert_eq!((r[0].players, r[0].bots, r[0].claimed), (Some(3), Some(40), true));
        assert_eq!(r[0].join_url.as_deref(), Some("https://relay.openvanilla.app/join/abcdefghijk2345a"));
        assert!(r[0].status_url.is_some());
        assert_eq!(r[1].address, None);
        assert_eq!(r[1].join_url, None, "a join page that is not the realm's own is dropped");
        assert_eq!(r[1].state, "offline");
        assert_eq!((r[0].core.as_str(), r[0].build), ("azerothcore", Some(Build::V335a)));
        assert_eq!(r[1].build, None, "no version in the record");
    }

    #[test]
    fn cores_builds_and_the_right_client() {
        for (s, t) in [("AzerothCore", "azerothcore"), ("TrinityCore", "trinitycore"), ("cMaNGOS", "cmangos"), ("vmangos", "vmangos"),
            ("MaNGOS Zero", "mangos"), ("ascent", "other")] {
            assert_eq!(core_tag(s), t);
        }
        assert_eq!(core_label("cmangos"), "CMaNGOS");
        let doc: Value = serde_json::from_str(r#"{"realms":[{"name":"Old Days","profile":{"version":"1.12.1","core":"vMaNGOS","address":"relay.openvanilla.app","port":40020},
            "community":{"realmId":"cccccccccccccccc","relay":"relay.openvanilla.app"}},
            {"name":"Cata","profile":{"build":15595,"core":"TrinityCore"},"community":{"realmId":"dddddddddddddddd","relay":"relay.openvanilla.app"}}]}"#).unwrap();
        let r = parse_community(&doc);
        assert_eq!((r[0].core.as_str(), r[0].build), ("vmangos", Some(Build::V1121)));
        assert_eq!((r[1].core.as_str(), r[1].build), ("trinitycore", Some(Build::V434)));
        let w = official();
        assert_eq!((w.core.as_str(), w.build), ("azerothcore", Some(Build::V335a)));

        let prof = |id: &str, b: Build| ClientProfile {
            id: id.into(), name: format!("my {}", b.version()), path: "/x".into(), build: b,
            realmlist: String::new(), locale: None, exe_version: None, exe: None,
        };
        let clients = vec![prof("c1121-1", Build::V1121), prof("c335a-1", Build::V335a), prof("c335a-2", Build::V335a)];
        assert_eq!(pick_client(&w, &clients, Some("c1121-1")).unwrap().id, "c335a-1", "the picked 1.12 client does not fit");
        assert_eq!(pick_client(&w, &clients, Some("c335a-2")).unwrap().id, "c335a-2", "the picked one when it fits");
        assert_eq!(pick_client(&r[0], &clients, Some("c335a-2")).unwrap().id, "c1121-1");
        let e = pick_client(&r[1], &clients, None).unwrap_err();
        assert!(e.contains("4.3.4 (15595)") && e.contains("you have 1.12.1, 3.3.5a, 3.3.5a") && e.contains("never downloads"), "{e}");
        assert!(pick_client(&w, &[], None).unwrap_err().contains("no clients yet"));
        let unknown = Realm { build: None, ..Default::default() };
        assert_eq!(pick_client(&unknown, &clients, Some("c1121-1")).unwrap().id, "c1121-1");
    }

    #[test]
    fn the_official_realm_comes_first_even_offline() {
        let d = tempfile::tempdir().unwrap();
        let base = serve_routes(vec![("/api/listing/realms.json", "200 OK", LISTING.as_bytes().to_vec())]);
        let l = fetch_all_from(&format!("{base}/api/listing/realms.json"), d.path());
        assert_eq!(l.realms.len(), 3);
        assert!(l.realms[0].official && !l.from_cache);
        let off = fetch_all_from(&dead_url(), d.path());
        assert!(off.from_cache && off.realms.len() == 3);
        let empty = tempfile::tempdir().unwrap();
        let none = fetch_all_from(&dead_url(), empty.path());
        assert_eq!(none.realms.len(), 1);
        assert!(none.error.is_some());
        assert_eq!(cached(d.path()).len(), 3);
    }

    #[test]
    fn lookup_and_knock_on_a_relay() {
        let info = format!(
            r#"{{"realm_id":"{RID}","online":true,"name":"Frost Haven","visibility":"private","address":"relay.openvanilla.app",
            "auth_port":40010,"world_port":40011,"status_url":"https://relay.openvanilla.app/r/{RID}/status.json"}}"#
        );
        let knocked = r#"{"ok":true,"name":"Frost Haven","visibility":"private","realmlist":"relay.openvanilla.app","realmlist_port":"relay.openvanilla.app:40010"}"#;
        let base = serve_routes(vec![
            (Box::leak(format!("/api/realms/{RID}").into_boxed_str()), "200 OK", info.into_bytes()),
            (Box::leak(format!("/api/realms/{RID}/knock").into_boxed_str()), "200 OK", knocked.as_bytes().to_vec()),
        ]);
        let r = lookup(&base, RID).unwrap();
        assert!(r.online);
        assert_eq!(r.address.as_deref(), Some("relay.openvanilla.app:40010"));
        assert!(lookup(&base, "nope").is_err());
        let (addr, name) = knock(&base, RID, "ABCDEFGHJKMNPQRS").unwrap();
        assert_eq!((addr.as_str(), name.as_str()), ("relay.openvanilla.app:40010", "Frost Haven"));
        // A realm with no port in the listing gets it from the relay.
        let mut realm = Realm { relay: Some("relay.openvanilla.app".into()), realm_id: Some(RID.into()), ..Default::default() };
        assert_eq!(desktop_address(&realm, |_| base.clone()).unwrap(), "relay.openvanilla.app:40010");
        realm.address = Some("x.example.org:1".into());
        assert_eq!(desktop_address(&realm, |_| unreachable!()).unwrap(), "x.example.org:1");
        // The relay's own error text comes through.
        let gone = serve_routes(vec![(Box::leak(format!("/api/realms/{RID}/knock").into_boxed_str()), "404 Not Found", br#"{"error":"realm offline"}"#.to_vec())]);
        assert_eq!(knock(&gone, RID, "ABCDEFGHJKMNPQRS").unwrap_err(), "realm offline");
    }

    #[test]
    fn invite_links() {
        let l = format!("https://relay.openvanilla.app/join/{RID}#ABCDEFGHJKMNPQRSTVWX");
        assert_eq!(parse_invite(&l), Some(("relay.openvanilla.app".into(), RID.into(), "ABCDEFGHJKMNPQRSTVWX".into())));
        let host = format!("{l}~HOSTSECRETHOSTSECRET");
        assert_eq!(parse_invite(&host).unwrap().2, "ABCDEFGHJKMNPQRSTVWX");
        assert_eq!(parse_invite(&format!("https://relay.openvanilla.app/join/{RID}")), None);
        assert_eq!(parse_invite(&format!("http://relay.openvanilla.app/join/{RID}#ABCDEFGHJKMNPQRS")), None);
        assert_eq!(parse_invite(&format!("https://evil.com:99/join/{RID}#ABCDEFGHJKMNPQRS")), None);
        assert!(status_url_ok(&format!("https://relay.openvanilla.app/r/{RID}/status.json")));
        assert!(!status_url_ok("https://relay.openvanilla.app/r/x/status.json"));
        assert!(!status_url_ok(&format!("http://relay.openvanilla.app/r/{RID}/status.json")));
    }
}
