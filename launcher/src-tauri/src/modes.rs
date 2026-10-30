//! The Modes page (`ui/modes.js`): every game mode one click away.
//!
//! The list is the site's `https://play.openvanilla.app/wrath/modes.json` (the catalog `stream/playmodes.json`, checked
//! by `stream/playmodes.py`). It is cached like the other listings; with no network and no cache yet, the copy built
//! into Leyline (the same file) is used, so the page is never empty. Entries that fail the checks here are left out.
//!
//! PLAY follows the Home page's play setting:
//! * **Browser**: a realm mode opens `https://play.openvanilla.app/wrath?go=mode:<id>`. The site signs the player in
//!   and records the mode for their game account (`ovplay go`); the realm starts it after login
//!   (`realm/custom/lua_scripts/ov_playmode.lua`). An offline mode opens its page on the site.
//! * **Desktop**: [`prepare_desktop`] writes a small addon, `Interface/AddOns/LeylinePlay/`, into the player's own
//!   3.3.5a client: `Pending.lua` names the mode with a fresh nonce and the time. The UI then starts the game on the
//!   official realm with the existing `play` command. After login the addon asks the realm once (OVMOD `wuplay go`,
//!   the same as typing `.playmode <id>`); the realm checks the id. A pick older than 15 minutes, or one already asked
//!   for (the addon's saved variables), is never asked again. See docs/leyline-modes-play.md.
//! * A realm type (its own server type) has no PLAY: the page offers the Host page instead.
//! * A mode marked `coming` has no PLAY: "Coming soon", and its credit and source link.
//!
//! The UI never names a URL: it names a mode id, and the address is built here from the checked catalog.

use crate::clients::{find_ci, Build, ClientProfile};
use crate::net;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};

/// The site's catalog.
pub const URL: &str = "https://play.openvanilla.app/wrath/modes.json";
/// The copy built into this Leyline (the repo's catalog), used when there is no network and no cache.
pub const BUILTIN: &str = include_str!("../../../stream/playmodes.json");
pub const CACHE_FILE: &str = "modes-cache.json";
/// The addon folder written into the player's client for desktop PLAY.
pub const ADDON: &str = "LeylinePlay";
const ADDON_LUA: &str = include_str!("modes/LeylinePlay.lua");
const KINDS: &[&str] = &["realm", "offline", "realm-type"];
const MAX_PLAYERS: u32 = 40;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Players {
    pub min: u32,
    pub max: Option<u32>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Credit {
    pub by: String,
    pub license: String,
    pub source: String,
    #[serde(default)]
    pub note: Option<String>,
    #[serde(default)]
    pub more: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct Start {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub go: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub host: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Mode {
    pub id: String,
    pub title: String,
    pub line: String,
    /// realm | offline | realm-type
    pub kind: String,
    pub players: Players,
    /// live | coming
    pub status: String,
    pub start: Start,
    #[serde(default)]
    pub credit: Option<Credit>,
}

impl Mode {
    pub fn live(&self) -> bool {
        self.status == "live"
    }
    /// A live mode that runs on our realm (ov_playmode.lua starts it).
    pub fn realm_live(&self) -> bool {
        self.live() && self.kind == "realm"
    }
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct ModeList {
    pub modes: Vec<Mode>,
    /// The network failed: this is the cached copy.
    pub from_cache: bool,
    /// The network failed and nothing was cached: this is the copy built into Leyline.
    pub builtin: bool,
    pub saved_at: Option<u64>,
    pub error: Option<String>,
}

fn id_ok(s: &str) -> bool {
    (2..=24).contains(&s.len())
        && s.starts_with(|c: char| c.is_ascii_lowercase())
        && s.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
        && !s.ends_with('-')
        && !s.contains("--")
}

fn text_ok(s: &str, lo: usize, hi: usize) -> bool {
    let n = s.chars().count();
    (lo..=hi).contains(&n) && s.trim() == s && !s.chars().any(|c| c.is_control() || c == '<' || c == '>')
}

/// A path on the site for an offline mode: `/wrath...`, plain characters only.
fn path_ok(p: &str) -> bool {
    p.len() <= 120
        && (p == "/wrath" || p.starts_with("/wrath/") || p.starts_with("/wrath?"))
        && p.chars().all(|c| c.is_ascii_alphanumeric() || "/._-?=&".contains(c))
        && !p.contains("..")
        && p.matches('?').count() <= 1
}

/// One entry's checks (the same rules as `stream/playmodes.py`, so a bad entry from anywhere is left out).
pub fn valid(m: &Mode) -> bool {
    let start_ok = match m.kind.as_str() {
        "realm" => m.start.go.as_deref() == Some(&format!("mode:{}", m.id)) && m.start.path.is_none() && m.start.host.is_none(),
        "offline" => m.start.path.as_deref().is_some_and(path_ok) && m.start.go.is_none() && m.start.host.is_none(),
        "realm-type" => m.start.host.as_deref().is_some_and(id_ok) && m.start.go.is_none() && m.start.path.is_none(),
        _ => false,
    };
    let players_ok = (1..=MAX_PLAYERS).contains(&m.players.min) && m.players.max.map_or(true, |x| (m.players.min..=MAX_PLAYERS).contains(&x));
    let credit_ok = m.credit.as_ref().map_or(true, |c| {
        text_ok(&c.by, 2, 80)
            && text_ok(&c.license, 2, 80)
            && c.note.as_deref().map_or(true, |n| text_ok(n, 2, 80))
            && c.more.len() <= 4
            && std::iter::once(&c.source).chain(c.more.iter()).all(|u| net::plain_https(u))
    });
    id_ok(&m.id)
        && text_ok(&m.title, 2, 40)
        && text_ok(&m.line, 10, 140)
        && KINDS.contains(&m.kind.as_str())
        && (m.status == "live" || m.status == "coming")
        && start_ok
        && players_ok
        && credit_ok
}

/// The modes of a catalog document: `{"schema": 1, "modes": [...]}`. Entries that fail the checks, and repeats of
/// an id, are left out. An error only when it is not that document at all.
pub fn parse(v: &Value) -> Result<Vec<Mode>, String> {
    if v.get("schema").and_then(Value::as_u64) != Some(1) {
        return Err("not the modes catalog (schema 1)".into());
    }
    let list = v.get("modes").and_then(Value::as_array).ok_or("the catalog has no modes list")?;
    let mut out: Vec<Mode> = Vec::new();
    for e in list.iter().take(200) {
        if let Ok(m) = serde_json::from_value::<Mode>(e.clone()) {
            if valid(&m) && !out.iter().any(|x| x.id == m.id) {
                out.push(m);
            }
        }
    }
    Ok(out)
}

pub fn builtin() -> Vec<Mode> {
    serde_json::from_str::<Value>(BUILTIN).ok().and_then(|v| parse(&v).ok()).unwrap_or_default()
}

pub fn cache_path(app_dir: &Path) -> PathBuf {
    app_dir.join(CACHE_FILE)
}

pub fn fetch(app_dir: &Path) -> ModeList {
    fetch_from(URL, app_dir)
}

/// The site's list, else the cached one, else the built-in one.
pub fn fetch_from(url: &str, app_dir: &Path) -> ModeList {
    match net::fetch_json(url, &cache_path(app_dir), net::TIMEOUT, |v| parse(v).map(|_| ())) {
        Ok(f) => ModeList { modes: parse(&f.value).unwrap_or_default(), from_cache: f.from_cache, builtin: false, saved_at: f.saved_at, error: f.error },
        Err(e) => ModeList { modes: builtin(), from_cache: false, builtin: true, saved_at: None, error: Some(e) },
    }
}

/// The list as last seen, without the network (the cache, else the built-in copy): what PLAY looks ids up in.
pub fn known(app_dir: &Path) -> Vec<Mode> {
    net::read_cache(&cache_path(app_dir)).and_then(|(v, _)| parse(&v).ok()).unwrap_or_else(builtin)
}

pub fn find(app_dir: &Path, id: &str) -> Result<Mode, String> {
    known(app_dir).into_iter().find(|m| m.id == id).ok_or_else(|| "That mode is not on the list any more.".into())
}

/// Where PLAY in the browser goes, for a live realm or offline mode.
pub fn browser_url(m: &Mode) -> Option<String> {
    if !m.live() || !valid(m) {
        return None;
    }
    match m.kind.as_str() {
        "realm" => Some(format!("{}?go=mode:{}", crate::BROWSER_PLAY_URL, m.id)),
        "offline" => m.start.path.as_ref().map(|p| format!("https://{}{p}", crate::OFFICIAL_REALM)),
        _ => None,
    }
}

/// The credit links a mode may open: its source, then the others.
pub fn credit_urls(m: &Mode) -> Vec<String> {
    m.credit.as_ref().map(|c| std::iter::once(c.source.clone()).chain(c.more.iter().cloned()).filter(|u| net::plain_https(u)).collect()).unwrap_or_default()
}

fn nonce(id: &str, now: u64) -> String {
    let mut h = Sha256::new();
    h.update(id.as_bytes());
    h.update(now.to_le_bytes());
    h.update(std::process::id().to_le_bytes());
    let t = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
    h.update(t.to_le_bytes());
    net::hex(&h.finalize())[..16].to_string()
}

/// The three files of the LeylinePlay addon for this pick: (file name, contents).
pub fn addon_files(id: &str, nonce: &str, made: u64, interface: &str) -> Vec<(&'static str, String)> {
    vec![
        (
            "LeylinePlay.toc",
            format!(
                "## Interface: {interface}\r\n## Title: Leyline Play\r\n## Notes: Starts the game mode you picked in the Leyline launcher, once, after you log in.\r\n## Author: Leyline\r\n## SavedVariables: LeylinePlayDB\r\nPending.lua\r\nLeylinePlay.lua\r\n"
            ),
        ),
        ("Pending.lua", format!("-- Written by the Leyline launcher's Modes page. Safe to delete.\nLEYLINE_PENDING = {{ mode = \"{id}\", nonce = \"{nonce}\", made = {made} }}\n")),
        ("LeylinePlay.lua", ADDON_LUA.to_string()),
    ]
}

/// Desktop PLAY, before the game starts: write the LeylinePlay addon naming `mode` into the client. Only a live realm
/// mode, only a 3.3.5a client (the modes run on the 3.3.5a realm). Returns where it went.
pub fn prepare_desktop(client: &ClientProfile, m: &Mode, made: u64) -> Result<PathBuf, String> {
    if !m.realm_live() || !valid(m) {
        return Err(format!("{} can't be started from the desktop client.", m.title));
    }
    if client.build != Build::V335a {
        return Err(format!("{} runs on the 3.3.5a realm: pick a 3.3.5a client for it.", m.title));
    }
    let iface = find_ci(&client.path, "Interface").unwrap_or_else(|| client.path.join("Interface"));
    let addons = find_ci(&iface, "AddOns").unwrap_or_else(|| iface.join("AddOns"));
    let dir = find_ci(&addons, ADDON).unwrap_or_else(|| addons.join(ADDON));
    std::fs::create_dir_all(&dir).map_err(|e| format!("Could not write the Leyline Play addon: {e}"))?;
    let n = nonce(&m.id, made);
    for (name, body) in addon_files(&m.id, &n, made, Build::V335a.interface()) {
        crate::settings::write_atomic(&dir.join(name), body.as_bytes()).map_err(|e| format!("Could not write the Leyline Play addon: {e}"))?;
    }
    Ok(dir)
}

#[cfg(feature = "app")]
fn now_secs() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

#[cfg(feature = "app")]
pub mod commands {
    use super::*;
    use tauri::AppHandle;
    use tauri_plugin_opener::OpenerExt;

    fn dir() -> PathBuf {
        crate::settings::app_dir()
    }

    async fn blocking<T: Send + 'static>(f: impl FnOnce() -> Result<T, String> + Send + 'static) -> Result<T, String> {
        tauri::async_runtime::spawn_blocking(f).await.map_err(|e| e.to_string())?
    }

    /// The Modes page's list.
    #[tauri::command]
    pub async fn modes_list() -> Result<ModeList, String> {
        blocking(|| Ok(fetch(&dir()))).await
    }

    /// PLAY in the browser: the mode's address, built here from its id.
    #[tauri::command]
    pub fn mode_open_browser(app: AppHandle, id: String) -> Result<String, String> {
        let m = find(&dir(), &id)?;
        let url = browser_url(&m).ok_or_else(|| format!("{} can't be played in the browser.", m.title))?;
        app.opener().open_url(url, None::<&str>).map_err(|e| e.to_string())?;
        Ok(format!("Opened {} in your browser: sign in and it starts when your character is in the world.", m.title))
    }

    /// A mode's credit link: 0 its source, 1.. the others.
    #[tauri::command]
    pub fn mode_open_credit(app: AppHandle, id: String, n: usize) -> Result<(), String> {
        let m = find(&dir(), &id)?;
        let url = credit_urls(&m).into_iter().nth(n).ok_or("That mode has no such link.")?;
        app.opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
    }

    /// PLAY on the desktop, step one: write the pick into the client (the UI then calls `play` on the official realm).
    #[tauri::command]
    pub fn mode_prepare_desktop(client: String, id: String) -> Result<String, String> {
        let s = crate::settings::load(&dir());
        let c = s.client(&client).ok_or("Pick a game client first.")?;
        let m = find(&dir(), &id)?;
        prepare_desktop(c, &m, now_secs())?;
        Ok(format!("{} starts after you log in.", m.title))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::clients::testutil::fake_335a;
    use crate::net::testserver::*;
    use serde_json::json;

    fn m(v: Value) -> Mode {
        serde_json::from_value(v).unwrap()
    }
    fn golf() -> Mode {
        builtin().into_iter().find(|x| x.id == "minigolf").unwrap()
    }
    fn profile(path: &Path, build: Build) -> ClientProfile {
        ClientProfile { id: "c1".into(), name: "Mine".into(), path: path.into(), build, realmlist: String::new(), locale: None, exe_version: None, exe: None }
    }

    #[test]
    fn builtin_catalog_parses_whole() {
        let ids: Vec<String> = builtin().into_iter().map(|x| x.id).collect();
        assert_eq!(ids, ["minigolf", "bumper-balls", "coin-dash", "community", "brawl", "azeroth-survivors", "hordes-of-azeroth"]);
        let all = builtin();
        let s = all.iter().find(|x| x.id == "azeroth-survivors").unwrap();
        assert_eq!((s.kind.as_str(), s.status.as_str()), ("offline", "coming"));
        assert_eq!(s.credit.as_ref().unwrap().by, "Aethus");
        let h = all.iter().find(|x| x.id == "hordes-of-azeroth").unwrap();
        assert_eq!(credit_urls(h), ["https://github.com/jonhaldors/hordes-of-azeroth", "https://github.com/jonhaldors/hordes-of-azeroth-server"]);
        assert_eq!(all.iter().find(|x| x.id == "brawl").unwrap().players.max, None);
    }

    #[test]
    fn bad_entries_are_left_out() {
        let good = serde_json::to_value(golf()).unwrap();
        let mut list = vec![good.clone()];
        let bad = |f: &dyn Fn(&mut Value)| {
            let mut v = good.clone();
            f(&mut v);
            v
        };
        list.push(bad(&|v| v["id"] = json!("Bad Id")));
        list.push(bad(&|v| v["kind"] = json!("arcade")));
        list.push(bad(&|v| v["status"] = json!("beta")));
        list.push(bad(&|v| v["title"] = json!("<b>x</b>")));
        list.push(bad(&|v| {
            v["id"] = json!("other");
            v["start"] = json!({"go": "mode:minigolf"})
        }));
        list.push(bad(&|v| {
            v["id"] = json!("site");
            v["kind"] = json!("offline");
            v["start"] = json!({"path": "https://evil.example/x"})
        }));
        list.push(bad(&|v| {
            v["id"] = json!("credited");
            v["credit"] = json!({"by": "Someone", "license": "MIT", "source": "javascript:alert(1)"})
        }));
        list.push(bad(&|v| v["players"] = json!({"min": 5, "max": 2})));
        list.push(good.clone()); // a repeat
        let got = parse(&json!({"schema": 1, "modes": list})).unwrap();
        assert_eq!(got.len(), 1);
        assert!(parse(&json!({"schema": 2, "modes": []})).is_err());
        assert!(parse(&json!({"schema": 1})).is_err());
    }

    #[test]
    fn served_then_cached_then_builtin() {
        let dir = tempfile::tempdir().unwrap();
        let doc = r#"{"schema":1,"modes":[{"id":"minigolf","title":"Minigolf","line":"Putt through courses players built.","kind":"realm","players":{"min":1,"max":8},"status":"live","start":{"go":"mode:minigolf"}}]}"#;
        let l = fetch_from(&serve_once("200 OK", doc), dir.path());
        assert_eq!((l.modes.len(), l.from_cache, l.builtin), (1, false, false));
        assert!(cache_path(dir.path()).is_file());
        let l = fetch_from(&dead_url(), dir.path());
        assert_eq!((l.modes.len(), l.from_cache, l.builtin), (1, true, false));
        assert!(l.error.is_some());
        assert_eq!(known(dir.path()).len(), 1);
        // a reply that is not the catalog never replaces the cache
        let l = fetch_from(&serve_once("200 OK", r#"{"realms":[]}"#), dir.path());
        assert!(l.from_cache && l.modes.len() == 1);
        let empty = tempfile::tempdir().unwrap();
        let l = fetch_from(&dead_url(), empty.path());
        assert!(l.builtin && !l.from_cache && l.modes.len() == 7 && l.error.is_some());
        assert_eq!(known(empty.path()).len(), 7);
        assert!(find(empty.path(), "nope").is_err());
    }

    #[test]
    fn links_are_built_from_the_catalog() {
        let all = builtin();
        let get = |id: &str| all.iter().find(|x| x.id == id).unwrap().clone();
        assert_eq!(browser_url(&get("minigolf")).as_deref(), Some("https://play.openvanilla.app/wrath?go=mode:minigolf"));
        assert_eq!(browser_url(&get("coin-dash")).as_deref(), Some("https://play.openvanilla.app/wrath?go=mode:coin-dash"));
        assert_eq!(browser_url(&get("brawl")), None, "a realm type: the Host page instead");
        assert_eq!(browser_url(&get("azeroth-survivors")), None, "coming soon: no Play");
        let mut s = get("azeroth-survivors");
        s.status = "live".into();
        assert_eq!(browser_url(&s).as_deref(), Some("https://play.openvanilla.app/wrath/play?mode=own&survivors=1"));
        let mut odd = get("minigolf");
        odd.start.go = Some("mode:other".into());
        assert_eq!(browser_url(&odd), None);
        assert!(credit_urls(&get("minigolf")).is_empty());
        assert!(path_ok("/wrath/play?mode=own&survivors=1") && !path_ok("/wrath/../x") && !path_ok("/other") && !path_ok("/wrath?a=1?b"));
    }

    #[test]
    fn desktop_pick_writes_the_addon() {
        let d = tempfile::tempdir().unwrap();
        fake_335a(d.path(), false);
        let c = profile(d.path(), Build::V335a);
        let dir = prepare_desktop(&c, &golf(), 1_800_000_000).unwrap();
        assert_eq!(dir, d.path().join("Interface/AddOns/LeylinePlay"));
        let toc = std::fs::read_to_string(dir.join("LeylinePlay.toc")).unwrap();
        assert!(toc.starts_with("## Interface: 30300\r\n") && toc.contains("## SavedVariables: LeylinePlayDB") && toc.contains("Pending.lua\r\nLeylinePlay.lua"));
        let p = std::fs::read_to_string(dir.join("Pending.lua")).unwrap();
        assert!(p.contains(r#"LEYLINE_PENDING = { mode = "minigolf", nonce = ""#) && p.contains("made = 1800000000 }"));
        let lua = std::fs::read_to_string(dir.join("LeylinePlay.lua")).unwrap();
        assert!(lua.contains("wuplay\\tgo\\t1/1\\t") && lua.contains("MAX_AGE = 900"));
        // a second pick: a new nonce, same place (and an existing folder in odd casing is reused)
        let first = p.clone();
        prepare_desktop(&c, &golf(), 1_800_000_001).unwrap();
        assert_ne!(std::fs::read_to_string(dir.join("Pending.lua")).unwrap(), first);
        let e = tempfile::tempdir().unwrap();
        fake_335a(e.path(), false);
        std::fs::create_dir_all(e.path().join("interface/addons/leylineplay")).unwrap();
        let got = prepare_desktop(&profile(e.path(), Build::V335a), &golf(), 1).unwrap();
        assert!(got.ends_with("interface/addons/leylineplay"));
        assert!(!e.path().join("Interface").exists(), "no second Interface folder");
    }

    #[test]
    fn desktop_pick_refuses() {
        let d = tempfile::tempdir().unwrap();
        let all = builtin();
        let c = profile(d.path(), Build::V335a);
        for id in ["brawl", "azeroth-survivors", "hordes-of-azeroth"] {
            assert!(prepare_desktop(&c, all.iter().find(|x| x.id == id).unwrap(), 1).is_err(), "{id}");
        }
        let old = profile(d.path(), Build::V1121);
        assert!(prepare_desktop(&old, &golf(), 1).unwrap_err().contains("3.3.5a"));
        let mut odd = golf();
        odd.id = "x\"; os.exit()".into();
        assert!(prepare_desktop(&c, &odd, 1).is_err());
        assert!(!d.path().join("Interface").exists(), "nothing written");
    }

    #[test]
    fn no_brand_names() {
        let low = BUILTIN.to_lowercase();
        for w in ["warcraft", "blizzard", "lich king"] {
            assert!(!low.contains(w), "{w}");
        }
        assert!(!ADDON_LUA.to_lowercase().contains("warcraft"));
        let _ = m(json!({"id":"ab","title":"Ab","line":"A line of text.","kind":"realm","players":{"min":1,"max":null},"status":"live","start":{"go":"mode:ab"}}));
    }
}
