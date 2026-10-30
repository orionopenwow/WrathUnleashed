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
//!
//! The network (2026-10-29): community realms are the front of Leyline. The list comes from the website's network
//! listing (`NETWORK_URL`: the relay's records with the staff overrides, hidden realms left out, featured and
//! verified marked) and, when that does not answer, from the relay itself. `order` puts it the same way as every
//! other surface: featured live realms, the official realm (the "Leyline Sample Hangout", temporary), the other live
//! realms by the listing's fair score (players, uptime, new; bots worth little; never money or votes), then offline.

use crate::clients::{Build, ClientProfile};
use crate::net::{self, Listing};
use serde::Serialize;
use serde_json::Value;
use std::path::{Path, PathBuf};
use std::time::Duration;

pub const URL: &str = "https://relay.openvanilla.app/api/listing/realms.json";
/// The website's network listing (stream/network.py), tried first.
pub const NETWORK_URL: &str = "https://play.openvanilla.app/wrath/realms.json";
/// Where a player reports a realm (signed in on the website).
pub const REPORT_BASE: &str = "https://play.openvanilla.app/wrath/realms/report?realm=";
pub const SAMPLE_NAME: &str = "Leyline Sample Hangout";
/// The rules tags a listing may carry, in order.
pub const TAGS: &[&str] = &["blizzlike", "boosted", "custom", "pvp", "rp", "hangout", "bots"];
pub const REGIONS: &[&str] = &["na-east", "na-west", "sa", "eu", "africa", "me", "asia", "oce"];
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
    /// Rules tags (`TAGS`), the host's region (or the relay's estimate, then `region_estimated`), language, limit.
    pub tags: Vec<String>,
    pub region: Option<String>,
    pub region_estimated: bool,
    pub language: Option<String>,
    pub max_players: Option<u64>,
    /// Percent of the last 24 h / 7 d the listing saw it online (None: watched for under an hour).
    pub uptime_24h: Option<u8>,
    pub uptime_7d: Option<u8>,
    pub is_new: bool,
    /// The listing's fair score (higher first).
    pub score: f64,
    pub featured: bool,
    pub verified: bool,
    /// The host allows direct connections and the network advertises it (ready but off: only used with `p2p_hosting`).
    pub direct: bool,
    /// featured, official, community or offline (see `order`).
    pub group: String,
    /// The website's report page for this realm.
    pub report_url: Option<String>,
    /// The official realm is the temporary Leyline Sample Hangout (the network listing's `sample` block says).
    pub temporary: bool,
}

/// The network line: realms online, players online, bots (counted apart).
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Totals {
    pub realms: u64,
    pub players: u64,
    pub bots: u64,
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
    pub network: Totals,
    pub from_cache: bool,
    pub saved_at: Option<u64>,
    pub error: Option<String>,
}

/// The official realm: for now the Leyline Sample Hangout, ours, temporary (owner, 2026-10-29). Community realms
/// are the network; this one is pinned below the featured ones.
pub fn official() -> Realm {
    Realm {
        slug: "official".into(),
        name: SAMPLE_NAME.into(),
        official: true,
        // TODO(owner): the sample hangout's one line
        tagline: "Temporary: our own realm to sample the game and meet people. The realms around it are run by players.".into(),
        tags: vec!["hangout".into()],
        group: "official".into(),
        temporary: true,
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
/// TODO(owner): the sibling 1.12 realm is not in the relay's listing and its desktop address is not
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

fn pct(v: Option<&Value>) -> Option<u8> {
    v.and_then(Value::as_u64).filter(|p| *p <= 100).map(|p| p as u8)
}

fn one_of(v: Option<&Value>, set: &[&str]) -> Option<String> {
    v.and_then(Value::as_str).filter(|x| set.contains(x)).map(String::from)
}

/// A language code as the listing writes it: `en`, `deu`, `pt-BR`.
pub fn lang_ok(s: &str) -> bool {
    let (a, b) = s.split_once('-').map(|(a, b)| (a, Some(b))).unwrap_or((s, None));
    (2..=3).contains(&a.len()) && a.chars().all(|c| c.is_ascii_lowercase())
        && b.map_or(true, |b| b.len() == 2 && b.chars().all(|c| c.is_ascii_uppercase()))
}

/// The network's order (the same as the website, the hub and the in-game window): featured live realms, the official
/// realm, every other live realm by score (higher first), offline realms by name. Sets `group`.
pub fn order(realms: &mut Vec<Realm>) {
    for r in realms.iter_mut() {
        r.group = if r.official {
            "official"
        } else if r.state != "live" {
            "offline"
        } else if r.featured {
            "featured"
        } else {
            "community"
        }
        .into();
    }
    let rank = |g: &str| match g {
        "featured" => 0,
        "official" => 1,
        "community" => 2,
        _ => 3,
    };
    realms.sort_by(|a, b| {
        rank(&a.group)
            .cmp(&rank(&b.group))
            .then(if a.group == "offline" { std::cmp::Ordering::Equal } else { b.score.total_cmp(&a.score) })
            .then(a.name.to_lowercase().cmp(&b.name.to_lowercase()))
            .then(a.slug.cmp(&b.slug))
    });
}

/// Realms and players online now (live realms only; bots apart).
pub fn totals(realms: &[Realm]) -> Totals {
    let live: Vec<&Realm> = realms.iter().filter(|r| r.state == "live").collect();
    Totals {
        realms: live.len() as u64,
        players: live.iter().filter_map(|r| r.players).sum(),
        bots: live.iter().filter_map(|r| r.bots).sum(),
    }
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
            // the network listing's own sample hangout is the official realm, which `officials` already lists
            if c.get("sample").and_then(Value::as_bool) == Some(true) {
                return None;
            }
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
            let up = c.get("uptime").cloned().unwrap_or(Value::Null);
            let tags_in: Vec<&str> = r.get("tags").and_then(Value::as_array).map(|a| a.iter().take(20).filter_map(Value::as_str).collect()).unwrap_or_default();
            let (region, region_estimated) = match one_of(r.get("region"), REGIONS) {
                Some(g) => (Some(g), false),
                None => match one_of(c.get("regionEstimate"), REGIONS) {
                    Some(g) => (Some(g), true),
                    None => (None, false),
                },
            };
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
                tags: TAGS.iter().filter(|t| tags_in.contains(t)).map(|t| t.to_string()).collect(),
                region,
                region_estimated,
                language: r.get("language").and_then(Value::as_str).filter(|l| lang_ok(l)).map(String::from),
                max_players: r.get("maxPlayers").and_then(Value::as_u64).filter(|n| (1..=10000).contains(n)),
                uptime_24h: pct(up.get("h24")),
                uptime_7d: pct(up.get("d7")),
                is_new: c.get("new").and_then(Value::as_bool).unwrap_or(false),
                score: c.get("score").and_then(Value::as_f64).filter(|x| x.is_finite() && (0.0..=1000.0).contains(x)).unwrap_or(0.0),
                featured: c.get("featured").and_then(Value::as_bool).unwrap_or(false),
                verified: c.get("verified").and_then(Value::as_bool).unwrap_or(false),
                direct: c.get("directConnect").and_then(Value::as_bool).unwrap_or(false),
                group: String::new(),
                report_url: Some(format!("{REPORT_BASE}{rid}")),
                temporary: false,
                realm_id: Some(rid),
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

/// Every realm on the network in its order: the website's network listing, else the relay's own.
pub fn fetch_all(app_dir: &Path) -> RealmList {
    // The Leyline mesh (p2p/mesh.rs), only with the mesh_realms flag on; when it finds nothing, today's listings.
    if let Some(doc) = crate::p2p::mesh::fetch_doc(app_dir, &crate::p2p::flags::current(app_dir)) {
        let _ = crate::settings::write_atomic(&cache_path(app_dir), doc.to_string().as_bytes());
        return list_of(&doc, false, Some(crate::p2p::mesh::now_secs()), None);
    }
    fetch_network(&[NETWORK_URL, URL], app_dir)
}

fn has_realms(v: &Value) -> Result<(), String> {
    v.get("realms").and_then(Value::as_array).map(|_| ()).ok_or_else(|| "no \"realms\" list in the reply".into())
}

/// The first of `urls` that answers with a listing (the last one falls back to the cache).
pub fn fetch_network(urls: &[&str], app_dir: &Path) -> RealmList {
    let cache = cache_path(app_dir);
    for u in &urls[..urls.len().saturating_sub(1)] {
        let got = net::get(u, net::TIMEOUT).and_then(|body| {
            let v: Value = serde_json::from_str(&body).map_err(|e| format!("not JSON: {e}"))?;
            has_realms(&v)?;
            Ok((body, v))
        });
        if let Ok((body, v)) = got {
            let _ = crate::settings::write_atomic(&cache, body.as_bytes());
            let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).ok();
            return list_of(&v, false, now, None);
        }
    }
    match urls.last() {
        Some(u) => fetch_all_from(u, app_dir),
        None => list_of(&Value::Null, false, None, Some("no listing".into())),
    }
}

/// The network listing's `sample` block names the official realm: the Leyline Sample Hangout (temporary) while it
/// runs, the realm's own name before that.
pub fn apply_sample(official: &mut Realm, doc: &Value) {
    let Some(sm) = doc.get("sample").filter(|_| doc.get("kind").and_then(Value::as_str) == Some("network")) else { return };
    if let Some(n) = sm.get("name").and_then(Value::as_str).map(|n| n.chars().filter(|c| !c.is_control()).take(32).collect::<String>())
        .filter(|n| !n.trim().is_empty())
    {
        official.name = n;
    }
    if let Some(t) = sm.get("temporary").and_then(Value::as_bool) {
        official.temporary = t;
        if !t {
            official.tagline = "The official realm: 3.3.5a, bots, the Workshop's mods.".into();
        }
    }
}

fn list_of(doc: &Value, from_cache: bool, saved_at: Option<u64>, error: Option<String>) -> RealmList {
    let mut realms = officials();
    for o in realms.iter_mut() {
        apply_sample(o, doc);
    }
    realms.extend(parse_community(doc));
    order(&mut realms);
    let mut network = totals(&realms);
    // the network listing counts every realm online (the sample hangout's own numbers included); a relay's listing
    // only its community realms, so the count from the list itself is used then
    if let Some(n) = doc.get("network").filter(|_| doc.get("kind").and_then(Value::as_str) == Some("network")) {
        let g = |k: &str| n.get(k).and_then(Value::as_u64).filter(|x| *x < 10_000_000);
        if let (Some(r), Some(p), Some(b)) = (g("realms"), g("players"), g("bots")) {
            network = Totals { realms: r, players: p, bots: b };
        }
    }
    RealmList { realms, network, from_cache, saved_at, error }
}

pub fn fetch_all_from(url: &str, app_dir: &Path) -> RealmList {
    match net::fetch_json(url, &cache_path(app_dir), net::TIMEOUT, has_realms) {
        Ok(f) => list_of(&f.value, f.from_cache, f.saved_at, f.error),
        Err(e) => list_of(&Value::Null, false, None, Some(e)),
    }
}

/// The realms as last fetched, without the network.
pub fn cached(app_dir: &Path) -> Vec<Realm> {
    let mut v = officials();
    if let Some((doc, _)) = net::read_cache(&cache_path(app_dir)) {
        for o in v.iter_mut() {
            apply_sample(o, &doc);
        }
        v.extend(parse_community(&doc));
    }
    order(&mut v);
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

    const NETWORK: &str = r#"{"schema":1,"kind":"network","network":{"realms":4,"players":40,"bots":70},"realms":[
      {"name":"Picked","state":"live","tags":["pvp","rp","evil"],"region":"eu","language":"de","maxPlayers":100,
       "profile":{"build":5875,"core":"vMaNGOS","address":"relay.openvanilla.app","port":40020},
       "community":{"realmId":"dddddddddddddddd","relay":"relay.openvanilla.app","score":12.5,"featured":true,"verified":true,
         "uptime":{"h24":95,"d7":96},"directConnect":false,"lastHeartbeat":{"online":true,"players":2,"bots":0}}},
      {"name":"Dalaran Hangout","state":"live","community":{"realmId":"eeeeeeeeeeeeeeee","relay":"relay.openvanilla.app","sample":true,
         "score":60,"lastHeartbeat":{"players":1,"bots":30}}},
      {"name":"Busy Den","state":"live","tags":["bots"],"community":{"realmId":"bbbbbbbbbbbbbbbb","relay":"relay.openvanilla.app",
         "score":80.5,"new":true,"regionEstimate":"na-east","uptime":{"h24":101,"d7":null},"lastHeartbeat":{"players":30,"bots":40}}},
      {"name":"Asleep","state":"offline","community":{"realmId":"cccccccccccccccc","relay":"relay.openvanilla.app","score":0,
         "featured":true}},
      {"name":"Plain","state":"live","language":"Klingon!","region":"mars","community":{"realmId":"aaaaaaaaaaaaaaaa",
         "relay":"relay.openvanilla.app","score":"lots","lastHeartbeat":{"players":0}}}
    ]}"#;

    #[test]
    fn network_fields_and_order() {
        let v: Value = serde_json::from_str(NETWORK).unwrap();
        let mut r = officials();
        r.extend(parse_community(&v));
        order(&mut r);
        let names: Vec<&str> = r.iter().map(|x| x.name.as_str()).collect();
        assert_eq!(names, ["Picked", SAMPLE_NAME, "Busy Den", "Plain", "Asleep"], "featured, the sample, by score, offline");
        assert_eq!(r.iter().map(|x| x.group.as_str()).collect::<Vec<_>>(), ["featured", "official", "community", "community", "offline"]);
        assert!(!r.iter().any(|x| x.name == "Dalaran Hangout"), "the listing's sample record is the official realm");
        let p = &r[0];
        assert_eq!((p.tags.clone(), p.region.as_deref(), p.region_estimated, p.language.as_deref(), p.max_players),
                   (vec!["pvp".to_string(), "rp".to_string()], Some("eu"), false, Some("de"), Some(100)));
        assert_eq!((p.uptime_24h, p.uptime_7d, p.featured, p.verified, p.direct, p.build), (Some(95), Some(96), true, true, false, Some(Build::V1121)));
        assert_eq!(p.report_url.as_deref(), Some("https://play.openvanilla.app/wrath/realms/report?realm=dddddddddddddddd"));
        let b = &r[2];
        assert_eq!((b.region.as_deref(), b.region_estimated, b.is_new, b.uptime_24h, b.score), (Some("na-east"), true, true, None, 80.5));
        let junk = &r[3];
        assert_eq!((junk.language.clone(), junk.region.clone(), junk.score), (None, None, 0.0));
        assert!(r[1].official && r[1].tagline.starts_with("Temporary"));
        assert_eq!(totals(&r), Totals { realms: 4, players: 32, bots: 40 });
        for (l, ok) in [("en", true), ("pt-BR", true), ("deu", true), ("EN", false), ("pt-br", false), ("english", false), ("", false)] {
            assert_eq!(lang_ok(l), ok, "{l}");
        }
    }

    #[test]
    fn the_network_listing_first_then_the_relay() {
        let d = tempfile::tempdir().unwrap();
        let net_base = serve_routes(vec![("/wrath/realms.json", "200 OK", NETWORK.as_bytes().to_vec())]);
        let relay = serve_routes(vec![("/api/listing/realms.json", "200 OK", LISTING.as_bytes().to_vec())]);
        let (nu, ru) = (format!("{net_base}/wrath/realms.json"), format!("{relay}/api/listing/realms.json"));
        let l = fetch_network(&[&nu, &ru], d.path());
        assert!(!l.from_cache && l.error.is_none());
        assert_eq!(l.realms[0].name, "Picked");
        assert_eq!(l.network, Totals { realms: 4, players: 40, bots: 70 }, "the network listing's own line");
        assert_eq!((l.realms[1].name.as_str(), l.realms[1].temporary), (SAMPLE_NAME, true), "no sample block: the default");
        let before: Value = serde_json::from_str(r#"{"kind":"network","sample":{"name":"WrathUnleashed","temporary":false},"realms":[]}"#).unwrap();
        let mut o = official();
        apply_sample(&mut o, &before);
        assert_eq!((o.name.as_str(), o.temporary), ("WrathUnleashed", false), "before the Sample Hangout runs");
        let relay_doc: Value = serde_json::from_str(r#"{"kind":"community","sample":{"name":"Spoof"},"realms":[]}"#).unwrap();
        let mut o = official();
        apply_sample(&mut o, &relay_doc);
        assert_eq!(o.name, SAMPLE_NAME, "only the network listing names it");
        // the website down: the relay's listing, ordered the same way, counted from the list
        let l = fetch_network(&[&dead_url(), &ru], d.path());
        assert!(!l.from_cache && l.realms[0].official && l.realms.len() == 3);
        assert_eq!(l.network, Totals { realms: 2, players: 3, bots: 40 });
        // both down: the cache, still in order
        let l = fetch_network(&[&dead_url(), &dead_url()], d.path());
        assert!(l.from_cache && l.realms[0].official);
        assert_eq!(cached(d.path())[0].group, "official");
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
