//! `leyline://` links: a hub page's "Install with Leyline" button opens `leyline://install/<catalog id>`.
//!
//! The scheme is registered by the installer (tauri.conf.json `plugins.deep-link.desktop.schemes`). On Windows and
//! Linux the OS starts Leyline with the link as an argument; `from_args` finds it. A link never installs anything
//! by itself: the UI shows the project and the player clicks INSTALL (a web page can open a link, so the click is
//! the consent). Only `install/<catalog id>`, `realm/<realm id or official>` and `host?<choices>` are understood;
//! anything else is ignored.
//!
//! `leyline://host?<choices>` comes from the in-game Host window (WrathUnleashedUI/Host.lua, "Start hosting" in the
//! desktop client): it opens the Host page with the host's choices (core, ruleset, name, type, rates, start, bots,
//! public or private, sign-up, Hero Key sign-in, region, language, tags, max players), and its "Make your realm on
//! the website" button opens the website's form filled in (`open_host_form`). `leyline://host?manage=<what>` (bots,
//! rates, signup, list, invite) comes from the game's "Your realm" tab: the Host page at that control. Every name and
//! value is checked here (`host_query`) with the same rules as Host.lua, stream/www-files/wrath-page.js hostQuery and
//! stream/hostflow.py prefill(); the link carries no secret and starts nothing.

/// What a link asks for.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(tag = "action", content = "id", rename_all = "lowercase")]
pub enum Link {
    /// Show this catalog project with its INSTALL button.
    Install(String),
    /// Show this realm on the Realms page with its PLAY button (a website's "Open in launcher"). Nothing starts
    /// until the player clicks PLAY.
    Realm(String),
    /// Open the Host page with these choices: the checked, canonical query string (`host_query`).
    Host(String),
}

pub const SCHEME: &str = "leyline";

/// A catalog id the link may name: `mod:<id>`, `link:<12 hex>` (catalog.rs id_ok) or `theme:<id>`.
fn id_ok(id: &str) -> bool {
    if let Some(t) = id.strip_prefix("theme:") {
        return (2..=32).contains(&t.len())
            && t.starts_with(|c: char| c.is_ascii_lowercase())
            && t.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-');
    }
    crate::catalog::id_ok(id)
}

/// Parse `leyline://install/<id>` (the id's `:` may come percent-encoded as `%3A`; a trailing `/` is fine).
pub fn parse(url: &str) -> Option<Link> {
    let url = url.trim();
    if url.len() > 700 || url.chars().any(|c| c.is_control() || c.is_whitespace()) {
        return None;
    }
    let (scheme, rest) = url.split_once("://")?;
    if !scheme.eq_ignore_ascii_case(SCHEME) {
        return None;
    }
    if let Some(q) = rest.strip_prefix("host?").or_else(|| rest.strip_prefix("host/?")) {
        let q = q.split('#').next()?;
        return host_query(q).map(Link::Host);
    }
    if url.len() > 200 {
        return None;
    }
    let rest = rest.split(['?', '#']).next()?.trim_end_matches('/');
    let (action, id) = rest.split_once('/')?;
    let id = id.replace("%3A", ":").replace("%3a", ":");
    match action {
        "install" if id_ok(&id) => Some(Link::Install(id)),
        "realm" if id == "official" || crate::realms::realm_id_ok(&id) => Some(Link::Realm(id)),
        _ => None,
    }
}

const HOST_KEYS: [&str; 16] = ["core", "preset", "name", "type", "xp", "loot", "rep", "start", "bots", "vis", "signup",
    "herokey", "region", "lang", "tags", "max"];
const REGIONS: [&str; 8] = ["na-east", "na-west", "sa", "eu", "africa", "me", "asia", "oce"];
const TAGS: [&str; 6] = ["blizzlike", "boosted", "custom", "pvp", "rp", "hangout"];
pub const MANAGE: [&str; 5] = ["bots", "rates", "signup", "list", "invite"];

fn unescape(v: &str) -> Option<String> {
    let b = v.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        match b[i] {
            b'%' => {
                let h = std::str::from_utf8(b.get(i + 1..i + 3)?).ok()?;
                out.push(u8::from_str_radix(h, 16).ok()?);
                i += 3;
            }
            b'+' => { out.push(b' '); i += 1; }
            c => { out.push(c); i += 1; }
        }
    }
    String::from_utf8(out).ok()
}

fn escape(v: &str) -> String {
    v.bytes().map(|c| if c.is_ascii_alphanumeric() || b"-_.~".contains(&c) { (c as char).to_string() }
        else { format!("%{c:02X}") }).collect()
}

fn small_int(v: &str, lo: u32, hi: u32) -> bool {
    !v.is_empty() && v.len() <= 5 && v.bytes().all(|c| c.is_ascii_digit()) && v.parse::<u32>().map_or(false, |n| (lo..=hi).contains(&n))
}

fn banned(name: &str) -> bool {
    let l = name.to_ascii_lowercase();
    let squash: String = l.split_whitespace().collect::<Vec<_>>().join(" ");
    let words: Vec<&str> = l.split(|c: char| !c.is_ascii_alphanumeric()).collect();
    squash.contains("warcraft") || squash.replace(' ', "").contains("lichking") || squash.contains("blizzard")
        || squash.replace(' ', "").contains("worldofwarcraft") || words.contains(&"wow")
}

/// The Host page's choices from a `leyline://host?` link, checked: a canonical query string (fixed order, each value
/// escaped), or None. Either a full set of choices (core, preset, name, type, vis, signup, herokey required; the rest
/// optional and only where the ruleset takes them) or `manage=<what>` alone.
pub fn host_query(q: &str) -> Option<String> {
    if q.len() > 600 {
        return None;
    }
    let mut got: Vec<(String, String)> = Vec::new();
    for pair in q.split('&').filter(|p| !p.is_empty()) {
        let (k, v) = pair.split_once('=')?;
        let (k, v) = (unescape(k)?, unescape(v)?);
        if got.iter().any(|(x, _)| *x == k) || got.len() >= 16 {
            return None;
        }
        got.push((k, v));
    }
    let get = |k: &str| got.iter().find(|(x, _)| x == k).map(|(_, v)| v.as_str());
    if let Some(m) = get("manage") {
        return (got.len() == 1 && MANAGE.contains(&m)).then(|| format!("manage={m}"));
    }
    if got.iter().any(|(k, _)| !HOST_KEYS.contains(&k.as_str())) {
        return None;
    }
    let core = get("core")?;
    let preset = get("preset")?;
    let presets: &[&str] = match core {
        "azerothcore" => &["dalaran", "main", "brawl", "progression"],
        "cmangos" => &["cmangos-1.12.1", "cmangos-2.4.3"],
        _ => return None,
    };
    if !presets.contains(&preset) {
        return None;
    }
    let ac = core == "azerothcore";
    let name = get("name")?.trim();
    if name.is_empty() || name.len() > 32 || !name.chars().all(|c| c.is_ascii_alphanumeric() || " _'-".contains(c)) || banned(name) {
        return None;
    }
    let ok = |k: &str, f: &dyn Fn(&str) -> bool| get(k).map_or(true, f);
    let required = ["normal", "pvp", "rp", "rppvp"].contains(&get("type")?)
        && ["public", "private"].contains(&get("vis")?)
        && ["open", "invite", "off"].contains(&get("signup")?)
        && ["on", "off"].contains(&get("herokey")?);
    let optional = ["xp", "loot", "rep"].iter().all(|k| ok(k, &|v| ac && small_int(v, 1, 10)))
        && ok("start", &|v| preset == "main" && (v == "level1" || v == "boost"))
        && ok("bots", &|v| ac && preset != "dalaran" && small_int(v, 0, 200))
        && ok("region", &|v| REGIONS.contains(&v))
        && ok("lang", &|v| {
            let (a, b) = v.split_once('-').unwrap_or((v, ""));
            (2..=3).contains(&a.len()) && a.bytes().all(|c| c.is_ascii_lowercase())
                && (b.is_empty() && !v.contains('-') || (b.len() == 2 && b.bytes().all(|c| c.is_ascii_uppercase())))
        })
        && ok("tags", &|v| v.split(',').all(|t| TAGS.contains(&t)))
        && ok("max", &|v| small_int(v, 0, 10000));
    if !(required && optional) {
        return None;
    }
    Some(HOST_KEYS.iter().filter_map(|k| get(k).map(|v| {
        let v = if *k == "name" { v.trim() } else { v };
        format!("{k}={}", escape(v))
    })).collect::<Vec<_>>().join("&"))
}

/// The first `leyline://` link among the program's arguments (how Windows and Linux hand it over).
pub fn from_args<I: IntoIterator<Item = String>>(args: I) -> Option<Link> {
    args.into_iter().skip(1).take(8).find_map(|a| parse(&a))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_install_links() {
        assert_eq!(parse("leyline://install/mod:pings"), Some(Link::Install("mod:pings".into())));
        assert_eq!(parse("LEYLINE://install/mod%3Apings/"), Some(Link::Install("mod:pings".into())));
        assert_eq!(parse("leyline://install/link:0123456789ab?from=hub"), Some(Link::Install("link:0123456789ab".into())));
        assert_eq!(parse("leyline://install/theme:night-sky"), Some(Link::Install("theme:night-sky".into())));
    }

    #[test]
    fn parses_realm_links() {
        assert_eq!(parse("leyline://realm/abcdefgh234567ab"), Some(Link::Realm("abcdefgh234567ab".into())));
        assert_eq!(parse("leyline://realm/official/?from=hub"), Some(Link::Realm("official".into())));
        for bad in ["leyline://realm/", "leyline://realm/xyz", "leyline://realm/../x", "leyline://realm/ABCDEFGH234567AB"] {
            assert_eq!(parse(bad), None, "{bad}");
        }
        let json = serde_json::to_value(Link::Realm("official".into())).unwrap();
        assert_eq!(json, serde_json::json!({"action": "realm", "id": "official"}));
    }

    const GAME: &str = "core=azerothcore&preset=main&name=Frost%20Haven%27s&type=rppvp&xp=5&loot=2&start=level1&bots=40\
        &vis=private&signup=invite&herokey=on&region=eu&lang=pt-BR&tags=pvp%2Crp&max=100";

    #[test]
    fn parses_host_links() {
        let want = "core=azerothcore&preset=main&name=Frost%20Haven%27s&type=rppvp&xp=5&loot=2&start=level1&bots=40\
            &vis=private&signup=invite&herokey=on&region=eu&lang=pt-BR&tags=pvp%2Crp&max=100";
        assert_eq!(parse(&format!("leyline://host?{GAME}")), Some(Link::Host(want.into())));
        assert_eq!(parse(&format!("LEYLINE://host/?{GAME}#x")), Some(Link::Host(want.into())));
        let short = "core=cmangos&preset=cmangos-1.12.1&name=Old+One&type=normal&vis=public&signup=open&herokey=off";
        assert_eq!(host_query(short).as_deref(),
            Some("core=cmangos&preset=cmangos-1.12.1&name=Old%20One&type=normal&vis=public&signup=open&herokey=off"));
        assert_eq!(parse("leyline://host?manage=bots"), Some(Link::Host("manage=bots".into())));
        let json = serde_json::to_value(Link::Host("manage=list".into())).unwrap();
        assert_eq!(json, serde_json::json!({"action": "host", "id": "manage=list"}));
    }

    #[test]
    fn refuses_bad_host_links() {
        let bad = [
            "".to_string(), "core=azerothcore".into(), format!("{GAME}&evil=1"), format!("{GAME}&name=x"),
            GAME.replace("preset=main", "preset=cmangos-1.12.1"), GAME.replace("Frost%20Haven%27s", "My%20WoW%20realm"),
            GAME.replace("Frost%20Haven%27s", "Warcraft%20fans"), GAME.replace("Frost%20Haven%27s", "a%3Cb%3E"),
            GAME.replace("Frost%20Haven%27s", &"x".repeat(33)), GAME.replace("xp=5", "xp=11"), GAME.replace("xp=5", "xp=2.5"),
            GAME.replace("bots=40", "bots=999"), GAME.replace("type=rppvp", "type=evil"), GAME.replace("vis=private", "vis=x"),
            GAME.replace("region=eu", "region=mars"), GAME.replace("lang=pt-BR", "lang=klingon"), GAME.replace("lang=pt-BR", "lang=pt-"),
            GAME.replace("tags=pvp%2Crp", "tags=bots"), GAME.replace("max=100", "max=-1"), GAME.replace("name=Frost", "name=%ZZ"),
            "core=azerothcore&preset=dalaran&name=Den&type=normal&bots=10&vis=public&signup=open&herokey=off".into(),
            "core=azerothcore&preset=brawl&name=Den&type=normal&start=level1&vis=public&signup=open&herokey=off".into(),
            "core=cmangos&preset=cmangos-2.4.3&name=Den&type=normal&xp=3&vis=public&signup=open&herokey=off".into(),
            "manage=evil".into(), "manage=bots&core=azerothcore".into(), "x".repeat(700),
        ];
        for b in bad.iter() {
            assert_eq!(host_query(b), None, "{b}");
        }
        assert_eq!(parse("leyline://host"), None);
        assert_eq!(parse("leyline://hostile?manage=bots"), None);
    }

    #[test]
    fn refuses_everything_else() {
        for bad in [
            "https://install/mod:pings",
            "leyline://install/",
            "leyline://install/mod:../../x",
            "leyline://install/mod:Pings",
            "leyline://install/link:xyz",
            "leyline://run/mod:pings",
            "leyline://install/mod:pings evil",
            "leyline:install/mod:pings",
            "leyline://install/theme:../x",
            &format!("leyline://install/mod:{}", "a".repeat(300)),
        ] {
            assert_eq!(parse(bad), None, "{bad}");
        }
    }

    #[test]
    fn finds_the_link_in_the_arguments() {
        let args = |v: &[&str]| v.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        assert_eq!(from_args(args(&["leyline.exe", "leyline://install/mod:pings"])), Some(Link::Install("mod:pings".into())));
        assert_eq!(from_args(args(&["leyline.exe", "--flag", "leyline://install/mod:pings"])), Some(Link::Install("mod:pings".into())));
        assert_eq!(from_args(args(&["leyline://install/mod:pings"])), None, "the program name is not an argument");
        assert_eq!(from_args(args(&["leyline.exe"])), None);
        let json = serde_json::to_value(Link::Install("mod:pings".into())).unwrap();
        assert_eq!(json, serde_json::json!({"action": "install", "id": "mod:pings"}));
    }
}
