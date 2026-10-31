//! Leyline addons: our own in-game addons (the Leyline window, game modes, golf, Edit mode and the Builder, the Den,
//! the Workshop tab, companions; plus the Armory and the quality-of-life addon) for a desktop 3.3.5a client. The
//! browser client gets the same addons from the stream; this puts them into the player's own game folder.
//!
//! * Where the pack comes from: `addonpack.json` on the public Leyline release `leyline-addons`
//!   (`DESCRIPTOR_URL`), made by `addons/pack/make-addonpack.py` (the owner's "Publish Leyline addons.bat",
//!   Autopilot step `addons`). It names a version, the zip's address and sha256, and the sha256 of every file
//!   inside. The listing is fetched over https from the release only; the last good one is kept for offline use.
//! * What is checked before the game folder is touched: the zip's sha256, then every unpacked file against the
//!   listing (nothing missing, nothing extra, every hash equal), only addon text, fonts and textures (`OUR_EXT`),
//!   then the mod manager's own addon checks (`mods::validate_ours`: no game data by name or by content, the
//!   client's `## Interface:` number, every file a .toc lists present). Anything wrong: nothing is installed.
//! * How it is installed: through the mod manager (`mods::install`) as one entry, `leyline:addons`, in the
//!   client's `Leyline/mods.json`. So the same rules hold: only `Interface/AddOns/<our folders>`, never an addon
//!   Leyline did not put there, an update steps the old files aside first (and puts them back if it fails), files
//!   the player changed are kept (`<name>.yours`), and Remove takes out exactly what was put in.
//! * An addon folder of the same name that Leyline did not install (a copy the player made by hand, say) is never
//!   replaced without the player's OK (`REPLACE_CONFIRM`). With it, that folder is moved whole into
//!   `<client>/Leyline/backup/` first, and Remove puts it back.
//! * Preferences (`PREFS_FILE` in the launcher's own folder): update on start (on by default) and "don't ask
//!   again" for the PLAY prompt on the official realm.
//!
//! Never game data: the pack holds our own Lua, TOC and XML files, our font (DejaVu Sans Mono, its licence beside
//! it) and our own textures. Forever UI is not ours and is never part of it.

use crate::clients::{find_ci, Build, ClientProfile};
use crate::mods::{self, Installed, Staged};
use crate::net;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

/// The mod manager key of the pack in each client's `Leyline/mods.json`.
pub const KEY: &str = "leyline:addons";
pub const NAME: &str = "Leyline addons";
/// The release's listing (versioned zip names, so an older listing never points at a file that changed).
pub const DESCRIPTOR_URL: &str = "https://github.com/orionopenwow/Leyline/releases/download/leyline-addons/addonpack.json";
/// Where a pack may be downloaded from (prefixes).
pub const ORIGINS: &[&str] = &["https://github.com/orionopenwow/Leyline/releases/download/leyline-addons/"];
pub const MAX_PACK: u64 = 20 * 1024 * 1024;
const MAX_FILES: usize = 1000;
/// Our addons are Lua, TOC and XML text, our font and our textures: nothing else is taken.
pub const OUR_EXT: &[&str] = &[".toc", ".lua", ".xml", ".ttf", ".tga", ".txt"];
/// The error an install returns when an addon folder of ours is already there and Leyline did not put it there.
pub const REPLACE_CONFIRM: &str = "ADDONS_REPLACE:";
pub const CACHE_FILE: &str = "addonpack-cache.json";
pub const PREFS_FILE: &str = "addons-prefs.json";
/// In `<client>/Leyline/`: the player's own folders moved aside for ours, put back by Remove.
const BACKUP_DIR: &str = "backup";
const BACKUP_LIST: &str = "addons-backup.json";

// ------------------------------------------------------------------------------------------------ the listing

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct PackAddon {
    pub name: String,
    pub title: String,
    pub version: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Descriptor {
    pub format: u32,
    pub name: String,
    pub version: String,
    /// The client build the pack is for (`3.3.5a`).
    pub build: String,
    pub download: String,
    pub sha256: String,
    pub size: Option<u64>,
    pub addons: Vec<PackAddon>,
    /// Every file in the zip (`<Addon>/<path>`) and its sha256.
    pub files: BTreeMap<String, String>,
}

fn origin_ok(u: &str) -> bool {
    let local_test = cfg!(test) && u.starts_with("http://127.0.0.1:");
    (local_test || (net::plain_https(u) && ORIGINS.iter().any(|o| u.starts_with(o)))) && u.len() <= 400
}

fn hex64(s: &str) -> bool {
    s.len() == 64 && s.chars().all(|c| c.is_ascii_hexdigit())
}

fn ext(p: &str) -> String {
    let name = p.rsplit('/').next().unwrap_or(p);
    name.rfind('.').map(|i| name[i..].to_ascii_lowercase()).unwrap_or_default()
}

/// A listing made safe, or None.
pub fn clean(d: Descriptor) -> Option<Descriptor> {
    let ok = d.format == 1
        && mods::version_tuple(&d.version).is_some()
        && d.version.len() <= 40
        && Build::from_tag(&d.build) == Some(Build::V335a)
        && origin_ok(&d.download)
        && hex64(&d.sha256)
        && !d.addons.is_empty()
        && d.addons.len() <= 16
        && d.addons.iter().all(|a| mods::addon_name_ok(&a.name))
        && !d.files.is_empty()
        && d.files.len() <= MAX_FILES;
    if !ok {
        return None;
    }
    let names: Vec<String> = d.addons.iter().map(|a| a.name.clone()).collect();
    let mut files = BTreeMap::new();
    for (rel, sha) in &d.files {
        let safe = mods::safe_rel(rel).ok().flatten()?;
        let top = safe.split('/').next().unwrap_or("");
        if safe != *rel || !safe.contains('/') || !names.iter().any(|n| n == top) || !OUR_EXT.contains(&ext(rel).as_str()) || !hex64(sha) {
            return None;
        }
        files.insert(rel.clone(), sha.to_ascii_lowercase());
    }
    let trim = |s: &str, n: usize| s.trim().chars().filter(|c| !c.is_control()).take(n).collect::<String>();
    Some(Descriptor {
        name: Some(trim(&d.name, 64)).filter(|n| !n.is_empty()).unwrap_or_else(|| NAME.into()),
        sha256: d.sha256.to_ascii_lowercase(),
        size: d.size.filter(|s| *s <= MAX_PACK),
        addons: d.addons.iter().map(|a| PackAddon { name: a.name.clone(), title: trim(&a.title, 64), version: trim(&a.version, 40) }).collect(),
        files,
        build: "3.3.5a".into(),
        ..d
    })
}

pub fn from_json(v: &Value) -> Option<Descriptor> {
    clean(serde_json::from_value(v.clone()).ok()?)
}

/// What the pack is now: the release's listing (saved as the offline copy), or the last good copy.
#[derive(Debug, Clone, Default, Serialize)]
pub struct Available {
    pub pack: Option<Descriptor>,
    pub from_cache: bool,
    pub error: Option<String>,
}

pub fn available(app_dir: &Path, url: &str) -> Available {
    let cache = app_dir.join(CACHE_FILE);
    let fresh = net::get_json(url, net::TIMEOUT).map_err(|e| format!("Could not reach the Leyline addons listing: {e}")).and_then(|v| {
        from_json(&v).ok_or_else(|| "The Leyline addons listing does not look right.".to_string())
    });
    match fresh {
        Ok(d) => {
            if let Ok(b) = serde_json::to_vec_pretty(&d) {
                let _ = crate::settings::write_atomic(&cache, &b);
            }
            Available { pack: Some(d), from_cache: false, error: None }
        }
        Err(e) => {
            let old = fs::read(&cache).ok().and_then(|b| serde_json::from_slice::<Descriptor>(&b).ok()).and_then(clean);
            Available { from_cache: old.is_some(), pack: old, error: Some(e) }
        }
    }
}

/// The last good listing, without the network.
pub fn cached(app_dir: &Path) -> Option<Descriptor> {
    fs::read(app_dir.join(CACHE_FILE)).ok().and_then(|b| serde_json::from_slice::<Descriptor>(&b).ok()).and_then(clean)
}

// ------------------------------------------------------------------------------------------------ preferences

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Prefs {
    /// Update the addons when Leyline starts (each 3.3.5a client that has them).
    pub auto_update: bool,
    /// PLAY on the official realm does not offer them again.
    pub dont_ask: bool,
}

impl Default for Prefs {
    fn default() -> Self {
        Prefs { auto_update: true, dont_ask: false }
    }
}

pub fn prefs(app_dir: &Path) -> Prefs {
    fs::read(app_dir.join(PREFS_FILE)).ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_default()
}

pub fn save_prefs(app_dir: &Path, p: &Prefs) -> Result<(), String> {
    let b = serde_json::to_vec_pretty(p).map_err(|e| e.to_string())?;
    crate::settings::write_atomic(&app_dir.join(PREFS_FILE), &b).map_err(|e| format!("Could not save the setting: {e}"))
}

// ------------------------------------------------------------------------------------------------ per client

/// One of the player's own folders that was moved aside for ours.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Backup {
    pub addon: String,
    /// Client-relative: where it was (`Interface/AddOns/OVQoL`) and where it is now (`Leyline/backup/...`).
    pub from: String,
    pub to: String,
    pub at: u64,
}

fn backup_list_path(client: &Path) -> PathBuf {
    client.join(mods::DIR).join(BACKUP_LIST)
}

pub fn backups(client: &Path) -> Vec<Backup> {
    fs::read(backup_list_path(client)).ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_default()
}

fn save_backups(client: &Path, list: &[Backup]) -> Result<(), String> {
    let p = backup_list_path(client);
    if list.is_empty() {
        let _ = fs::remove_file(&p);
        return Ok(());
    }
    let b = serde_json::to_vec_pretty(list).map_err(|e| e.to_string())?;
    crate::settings::write_atomic(&p, &b).map_err(|e| format!("could not save the list of your moved folders: {e}"))
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct ClientAddons {
    pub client: String,
    pub name: String,
    pub build: String,
    /// Only 3.3.5a clients take them.
    pub supported: bool,
    /// The installed version, when Leyline installed them in this client.
    pub installed: Option<String>,
    pub installed_at: Option<u64>,
    /// The listed version is newer than the installed one (or the same version with other files).
    pub update: bool,
    /// Installed, but one of our folders has gone (the player deleted it): Install puts it back.
    pub missing: Vec<String>,
    /// Folders named like ours that Leyline did not put there (Install asks before it moves them aside).
    pub foreign: Vec<String>,
    /// The player's own folders moved aside for ours (Remove puts them back).
    pub backups: Vec<String>,
}

fn addons_folder(client: &Path) -> Option<PathBuf> {
    find_ci(client, "Interface").and_then(|i| find_ci(&i, "AddOns"))
}

/// What this client has, against the listing (when there is one).
pub fn client_status(p: &ClientProfile, pack: Option<&Descriptor>) -> ClientAddons {
    let mut out = ClientAddons {
        client: p.id.clone(),
        name: p.name.clone(),
        build: p.build.version().into(),
        supported: p.build == Build::V335a,
        ..Default::default()
    };
    if !out.supported {
        return out;
    }
    let man = mods::load(&p.path);
    let mine = man.get(KEY);
    let addons = addons_folder(&p.path);
    let here = |n: &str| addons.as_ref().and_then(|a| find_ci(a, n)).is_some();
    if let Some(m) = mine {
        out.installed = Some(m.version.clone());
        out.installed_at = Some(m.installed_at);
        out.missing = m.addons.iter().filter(|n| m.enabled && !here(n)).cloned().collect();
        if let Some(d) = pack {
            out.update = mods::newer(&d.version, &m.version) || (d.version == m.version && d.sha256 != m.sha256);
        }
    }
    if let Some(d) = pack {
        let owned = |n: &str| man.mods.iter().any(|m| m.addons.iter().any(|x| x.eq_ignore_ascii_case(n)));
        out.foreign = d.addons.iter().map(|a| a.name.clone()).filter(|n| here(n) && !owned(n)).collect();
    }
    out.backups = backups(&p.path).into_iter().map(|b| b.addon).collect();
    out
}

// ------------------------------------------------------------------------------------------------ install

/// Every unpacked file against the listing: nothing missing, nothing extra, each hash equal, only our file types.
pub fn check_files(staged: &[Staged], d: &Descriptor) -> Result<(), String> {
    let bad = |what: String| Err(format!("The Leyline addons download did not check out ({what}), so nothing was installed. Try again later."));
    for f in staged {
        let Some(want) = d.files.get(&f.rel) else {
            return bad(format!("{} is not in the listing", f.rel));
        };
        if !OUR_EXT.contains(&ext(&f.rel).as_str()) {
            return bad(format!("{} is not an addon file", f.rel));
        }
        if net::sha256_file(&f.abs).unwrap_or_default() != *want {
            return bad(format!("{} is not the listed file", f.rel));
        }
    }
    if let Some(missing) = d.files.keys().find(|k| !staged.iter().any(|f| f.rel == **k)) {
        return bad(format!("{missing} is missing"));
    }
    Ok(())
}

/// What an install did.
#[derive(Debug, Clone, Default, Serialize)]
pub struct Done {
    pub version: String,
    pub addons: Vec<String>,
    /// The player's own folders moved into Leyline/backup/ first (client-relative).
    pub moved_aside: Vec<String>,
    /// Files the player changed that an update kept (`mods::Installed::kept`).
    pub kept: Vec<String>,
    /// Nothing to do: this version is already in.
    pub already: bool,
}

fn now() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn rel_of(client: &Path, p: &Path) -> String {
    p.strip_prefix(client).unwrap_or(p).components().map(|c| c.as_os_str().to_string_lossy().to_string()).collect::<Vec<_>>().join("/")
}

/// A folder inside the client and not through a symbolic link, or an error.
fn no_links(client: &Path, p: &Path) -> Result<(), String> {
    let rel = p.strip_prefix(client).map_err(|_| format!("{} is not inside the client folder", p.display()))?;
    let mut at = client.to_path_buf();
    for c in rel.components() {
        at.push(c);
        if fs::symlink_metadata(&at).is_ok_and(|m| m.file_type().is_symlink()) {
            return Err(format!("{} runs through a link to somewhere else: Leyline will not touch it", rel_of(client, &at)));
        }
    }
    Ok(())
}

fn replace_confirm(names: &[String]) -> String {
    format!("{REPLACE_CONFIRM}{}", serde_json::json!({ "folders": names }))
}

/// Download (from the release only), check and install `d` into `client`. `replace_ok`: the player said yes to
/// moving their own folders of the same names aside (else the error starts with `REPLACE_CONFIRM`).
pub fn install(client: &Path, build: Build, d: &Descriptor, scratch: &Path, replace_ok: bool) -> Result<Done, String> {
    if build != Build::V335a {
        return Err("The Leyline addons are for the Dalaran Hangout's client, not this one.".into());
    }
    let d = clean(d.clone()).ok_or("The Leyline addons listing does not look right.")?;
    let man = mods::load(client);
    if let Some(m) = man.get(KEY) {
        let addons = addons_folder(client);
        let all_here = m.enabled && m.addons.iter().all(|n| addons.as_ref().and_then(|a| find_ci(a, n)).is_some());
        if m.version == d.version && m.sha256 == d.sha256 && all_here {
            return Ok(Done { version: m.version.clone(), addons: m.addons.clone(), already: true, ..Default::default() });
        }
    }
    // Ours or someone else's: decided before anything is downloaded, so the question comes at once.
    let owned_by_other = |n: &str| man.mods.iter().find(|m| m.key != KEY && m.addons.iter().any(|x| x.eq_ignore_ascii_case(n)));
    if let Some((a, m)) = d.addons.iter().find_map(|a| owned_by_other(&a.name).map(|m| (a, m))) {
        return Err(format!("{} is already installed by \"{}\" on the Mods page: remove that one first.", a.name, m.name));
    }
    let ours = |n: &str| man.get(KEY).is_some_and(|m| m.enabled && m.addons.iter().any(|x| x.eq_ignore_ascii_case(n)));
    let addons = addons_folder(client);
    let foreign: Vec<(String, PathBuf)> = d
        .addons
        .iter()
        .filter(|a| !ours(&a.name))
        .filter_map(|a| addons.as_ref().and_then(|f| find_ci(f, &a.name)).map(|p| (a.name.clone(), p)))
        .collect();
    if !foreign.is_empty() && !replace_ok {
        return Err(replace_confirm(&foreign.iter().map(|(n, _)| n.clone()).collect::<Vec<_>>()));
    }

    // Download and check, all outside the game folder's AddOns.
    let dl = mods::Scratch::new(scratch).map_err(|e| format!("could not make a download folder: {e}"))?;
    let zip = dl.dir.join("leyline-addons.zip");
    if !cfg!(test) && !d.download.starts_with("https://") {
        return Err("Leyline only downloads over https.".into());
    }
    let (_, sha) = net::download(&d.download, &zip, MAX_PACK, net::TIMEOUT, Duration::from_secs(30)).map_err(|e| format!("Download failed: {e}"))?;
    if sha != d.sha256 {
        return Err("The Leyline addons download does not match its checksum, so nothing was installed. Try again later.".into());
    }
    let st = mods::Staging::new(client).map_err(|e| format!("could not make a staging folder in the client: {e}"))?;
    let files = st.files();
    fs::create_dir_all(&files).map_err(|e| e.to_string())?;
    mods::extract_zip(&zip, &files, MAX_PACK)?;
    let staged = mods::walk(&files).map_err(|e| e.to_string())?;
    check_files(&staged, &d)?;
    let plan = mods::validate_ours(&staged, build);
    if !plan.errors.is_empty() {
        return Err(format!("The Leyline addons did not pass Leyline's addon checks, so nothing was installed:\n{}", plan.errors.join("\n")));
    }
    if !plan.patches.is_empty() || !plan.natives.is_empty() {
        return Err("The Leyline addons may only hold addons.".into());
    }
    let mut names: Vec<String> = plan.addons.iter().map(|a| a.name.clone()).collect();
    names.sort();
    let mut want: Vec<String> = d.addons.iter().map(|a| a.name.clone()).collect();
    want.sort();
    if names != want {
        return Err("The Leyline addons download holds other addons than its listing says, so nothing was installed.".into());
    }

    // The player's own folders step aside (whole) into Leyline/backup/, and come back if the install fails.
    let mut list = backups(client);
    let mut moved: Vec<(PathBuf, PathBuf, Backup)> = Vec::new();
    let stamp = now();
    for (name, from) in &foreign {
        no_links(client, from)?;
        let mut to = client.join(mods::DIR).join(BACKUP_DIR).join(format!("{name}-{stamp}"));
        let mut i = 2;
        while to.exists() {
            to = client.join(mods::DIR).join(BACKUP_DIR).join(format!("{name}-{stamp}-{i}"));
            i += 1;
        }
        let r = fs::create_dir_all(to.parent().unwrap_or(client)).and_then(|_| fs::rename(from, &to));
        if let Err(e) = r {
            for (f, t, _) in moved.iter().rev() {
                let _ = fs::rename(t, f);
            }
            return Err(format!("Could not move your own {name} folder aside (is the game open?): {e}"));
        }
        let b = Backup { addon: name.clone(), from: rel_of(client, from), to: rel_of(client, &to), at: stamp };
        moved.push((from.clone(), to, b));
    }
    let meta = mods::InstallMeta {
        key: KEY.into(),
        name: NAME.into(),
        version: d.version.clone(),
        source: "leyline".into(),
        sha256: d.sha256.clone(),
        category: "leyline".into(),
        credits: "Leyline".into(),
    };
    let done: Result<Installed, String> = mods::install(client, build, meta, &plan, false);
    let inst = match done {
        Ok(i) => i,
        Err(e) => {
            for (f, t, _) in moved.iter().rev() {
                let _ = fs::rename(t, f);
            }
            prune_backup_dir(client);
            return Err(e);
        }
    };
    let moved_aside: Vec<String> = moved.iter().map(|(_, _, b)| b.to.clone()).collect();
    list.extend(moved.into_iter().map(|(_, _, b)| b));
    save_backups(client, &list)?;
    Ok(Done { version: inst.version.clone(), addons: inst.addons.clone(), moved_aside, kept: inst.kept.clone(), already: false })
}

fn prune_backup_dir(client: &Path) {
    let b = client.join(mods::DIR).join(BACKUP_DIR);
    let _ = fs::remove_dir(&b);
    let _ = fs::remove_dir(client.join(mods::DIR));
}

/// What Remove did.
#[derive(Debug, Clone, Default, Serialize)]
pub struct RemovedAddons {
    pub removed_files: usize,
    /// Files the player changed: left where they are.
    pub changed: Vec<String>,
    /// Files in our folders that Leyline did not put there: left where they are.
    pub kept: Vec<String>,
    /// The player's own folders put back where they were.
    pub restored: Vec<String>,
    /// Their own folders that could not go back (the place is taken): still in Leyline/backup/.
    pub still_backed_up: Vec<String>,
}

/// Take the pack out of `client`: exactly the files Leyline put there (`mods::uninstall`), then the player's own
/// folders that were moved aside go back where they were.
pub fn remove(client: &Path) -> Result<RemovedAddons, String> {
    let had = mods::load(client).get(KEY).is_some();
    let list = backups(client);
    if !had && list.is_empty() {
        return Err("The Leyline addons are not installed in this client.".into());
    }
    let mut out = RemovedAddons::default();
    if had {
        let r = mods::uninstall(client, KEY)?;
        out.removed_files = r.removed_files;
        out.changed = r.changed;
        out.kept = r.kept;
    }
    let mut left = Vec::new();
    for b in list {
        let from = client.join(&b.to);
        let back = client.join(&b.from);
        if !from.is_dir() {
            continue;
        }
        if back.exists() || no_links(client, &from).is_err() || back.parent().is_some_and(|p| no_links(client, p).is_err()) {
            out.still_backed_up.push(b.to.clone());
            left.push(b);
            continue;
        }
        let r = back.parent().map(fs::create_dir_all).unwrap_or(Ok(())).and_then(|_| fs::rename(&from, &back));
        match r {
            Ok(()) => out.restored.push(b.from.clone()),
            Err(_) => {
                out.still_backed_up.push(b.to.clone());
                left.push(b);
            }
        }
    }
    save_backups(client, &left)?;
    if left.is_empty() {
        prune_backup_dir(client);
    }
    Ok(out)
}

/// Update on start: each 3.3.5a client that has the pack and is behind the listing. Never moves the player's own
/// folders (that needs their OK). Returns (client id, what happened) per client it tried.
pub fn auto_update(clients: &[ClientProfile], d: &Descriptor, scratch: &Path) -> Vec<(String, Result<Done, String>)> {
    clients
        .iter()
        .filter(|c| c.build == Build::V335a)
        .filter(|c| {
            let s = client_status(c, Some(d));
            s.installed.is_some() && (s.update || !s.missing.is_empty())
        })
        .map(|c| (c.id.clone(), install(&c.path, c.build, d, scratch, false)))
        .collect()
}

/// Should PLAY on the official realm offer the addons for this client?
pub fn should_offer(p: &ClientProfile, prefs: &Prefs) -> bool {
    !prefs.dont_ask && p.build == Build::V335a && mods::load(&p.path).get(KEY).is_none()
}

// ------------------------------------------------------------------------------------------------ commands

#[cfg(feature = "app")]
pub(crate) mod commands {
    use super::*;
    use tauri::State;

    type Core<'a> = State<'a, crate::app::Core>;

    async fn blocking<T: Send + 'static>(f: impl FnOnce() -> Result<T, String> + Send + 'static) -> Result<T, String> {
        tauri::async_runtime::spawn_blocking(f).await.map_err(|e| e.to_string())?
    }

    #[derive(Serialize)]
    pub struct Overview {
        pub pack: Option<Descriptor>,
        pub from_cache: bool,
        pub error: Option<String>,
        pub prefs: Prefs,
        pub clients: Vec<ClientAddons>,
    }

    fn overview(dir: &Path, clients: &[ClientProfile], a: Available) -> Overview {
        let pack = a.pack;
        Overview {
            clients: clients.iter().map(|c| client_status(c, pack.as_ref())).collect(),
            pack,
            from_cache: a.from_cache,
            error: a.error,
            prefs: prefs(dir),
        }
    }

    /// The Leyline addons for every client. `refresh` asks the release again; otherwise the last good listing.
    #[tauri::command]
    pub async fn addons_status(core: Core<'_>, refresh: bool) -> Result<Overview, String> {
        let dir = core.dir.clone();
        let clients = core.snapshot().clients;
        blocking(move || {
            let a = match cached(&dir) {
                Some(d) if !refresh => Available { pack: Some(d), from_cache: true, error: None },
                _ => available(&dir, DESCRIPTOR_URL),
            };
            Ok(overview(&dir, &clients, a))
        })
        .await
    }

    /// Install or update the addons in one client (the listing is fetched again first).
    #[tauri::command]
    pub async fn addons_install(core: Core<'_>, client: String, replace: bool) -> Result<Done, String> {
        let p = core.client(&client)?;
        let dir = core.dir.clone();
        let lock = core.mods_lock.clone();
        blocking(move || {
            let a = available(&dir, DESCRIPTOR_URL);
            let d = a.pack.ok_or_else(|| a.error.unwrap_or_else(|| "The Leyline addons are not published yet.".into()))?;
            let _g = lock.lock().map_err(|_| "mod lock poisoned")?;
            install(&p.path, p.build, &d, &dir, replace)
        })
        .await
    }

    #[tauri::command]
    pub async fn addons_remove(core: Core<'_>, client: String) -> Result<RemovedAddons, String> {
        let p = core.client(&client)?;
        let lock = core.mods_lock.clone();
        blocking(move || {
            let _g = lock.lock().map_err(|_| "mod lock poisoned")?;
            remove(&p.path)
        })
        .await
    }

    #[derive(Serialize)]
    pub struct Updated {
        pub client: String,
        pub version: Option<String>,
        pub error: Option<String>,
    }

    /// Leyline started: update the addons where they are installed and behind (when that setting is on).
    #[tauri::command]
    pub async fn addons_auto_update(core: Core<'_>) -> Result<Vec<Updated>, String> {
        let dir = core.dir.clone();
        let clients = core.snapshot().clients;
        let lock = core.mods_lock.clone();
        blocking(move || {
            if !prefs(&dir).auto_update || !clients.iter().any(|c| mods::load(&c.path).get(KEY).is_some()) {
                return Ok(Vec::new());
            }
            let Some(d) = available(&dir, DESCRIPTOR_URL).pack else { return Ok(Vec::new()) };
            let _g = lock.lock().map_err(|_| "mod lock poisoned")?;
            Ok(auto_update(&clients, &d, &dir)
                .into_iter()
                .map(|(client, r)| match r {
                    Ok(done) => Updated { client, version: Some(done.version), error: None },
                    Err(e) => Updated { client, version: None, error: Some(e) },
                })
                .collect())
        })
        .await
    }

    /// Settings: update on start, and the PLAY prompt's "don't ask again".
    #[tauri::command]
    pub fn addons_set_prefs(core: Core<'_>, auto_update: Option<bool>, dont_ask: Option<bool>) -> Result<Prefs, String> {
        let mut p = prefs(&core.dir);
        if let Some(v) = auto_update {
            p.auto_update = v;
        }
        if let Some(v) = dont_ask {
            p.dont_ask = v;
        }
        save_prefs(&core.dir, &p)?;
        Ok(p)
    }

    /// PLAY on the official realm: offer the addons for this client? (3.3.5a, not installed, not "don't ask again").
    #[tauri::command]
    pub fn addons_should_offer(core: Core<'_>, client: String) -> Result<bool, String> {
        let p = core.client(&client)?;
        Ok(should_offer(&p, &prefs(&core.dir)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::clients::testutil::{fake_1121, fake_335a, touch};
    use crate::mods::tests::zip_of;
    use crate::net::testserver::serve_routes;
    use sha2::{Digest, Sha256};

    fn sha(b: &[u8]) -> String {
        net::hex(&Sha256::digest(b))
    }

    const TOC: &[u8] = b"## Interface: 30300\n## Title: Leyline UI\n## Version: 2\nWrathUnleashedUI.lua\n";
    const LUA: &[u8] = b"WrathUnleashedUI = {}\n";
    const QTOC: &[u8] = b"## Interface: 30300\n## Title: OVQoL\nOVQoL.lua\n";
    const QLUA: &[u8] = b"OVQoLDB = OVQoLDB or {}\n";

    fn entries(lua: &'static [u8]) -> Vec<(&'static str, &'static [u8])> {
        vec![
            ("WrathUnleashedUI/WrathUnleashedUI.toc", TOC),
            ("WrathUnleashedUI/WrathUnleashedUI.lua", lua),
            ("OVQoL/OVQoL.toc", QTOC),
            ("OVQoL/OVQoL.lua", QLUA),
        ]
    }

    /// (descriptor, zip) for these entries, served at `base`/pack.zip.
    fn pack(version: &str, files: &[(&str, &[u8])]) -> (Descriptor, Vec<u8>) {
        let zip = zip_of(files);
        let d = Descriptor {
            format: 1,
            name: NAME.into(),
            version: version.into(),
            build: "3.3.5a".into(),
            download: String::new(),
            sha256: sha(&zip),
            size: Some(zip.len() as u64),
            addons: vec![
                PackAddon { name: "OVQoL".into(), title: "OVQoL".into(), version: String::new() },
                PackAddon { name: "WrathUnleashedUI".into(), title: "Leyline UI".into(), version: "2".into() },
            ],
            files: files.iter().map(|(n, b)| (n.to_string(), sha(b))).collect(),
        };
        (d, zip)
    }

    fn served(d: &Descriptor, zip: Vec<u8>) -> Descriptor {
        let base = serve_routes(vec![("/pack.zip", "200 OK", zip)]);
        Descriptor { download: format!("{base}/pack.zip"), ..d.clone() }
    }

    fn profile(path: &Path, build: Build) -> ClientProfile {
        ClientProfile { id: "c1".into(), name: "Mine".into(), path: path.into(), build, realmlist: String::new(), locale: None, exe_version: None, exe: None }
    }

    fn setup() -> (tempfile::TempDir, PathBuf, PathBuf) {
        let t = tempfile::tempdir().unwrap();
        let client = t.path().join("game");
        let app = t.path().join("app");
        fake_335a(&client, false);
        fs::create_dir_all(&app).unwrap();
        (t, client, app)
    }

    #[test]
    fn install_update_remove() {
        let (_t, client, app) = setup();
        // Someone else's addon is there before and after, untouched.
        touch(&client, "Interface/AddOns/Questie/Questie.toc", b"## Interface: 30300\n");
        let (d1, z1) = pack("2026.1030.1200", &entries(LUA));
        let d1 = served(&d1, z1);
        let p = profile(&client, Build::V335a);
        assert!(should_offer(&p, &Prefs::default()));
        let done = install(&client, Build::V335a, &d1, &app, false).unwrap();
        assert_eq!(done.version, "2026.1030.1200");
        assert!(!done.already);
        assert_eq!(fs::read(client.join("Interface/AddOns/WrathUnleashedUI/WrathUnleashedUI.lua")).unwrap(), LUA);
        assert!(client.join("Interface/AddOns/OVQoL/OVQoL.toc").is_file());
        let s = client_status(&p, Some(&d1));
        assert_eq!((s.installed.as_deref(), s.update, s.supported), (Some("2026.1030.1200"), false, true));
        assert!(!should_offer(&p, &Prefs::default()));
        // Same again: nothing to do.
        assert!(install(&client, Build::V335a, &d1, &app, false).unwrap().already);
        // The Workshop list does not show it as a Workshop mod.
        assert!(mods::with_updates(&mods::load(&client), &[], Build::V335a).is_empty());

        // A newer version: an update, through auto_update.
        let (d2, z2) = pack("2026.1031.0900", &entries(b"WrathUnleashedUI = { v = 2 }\n"));
        let d2 = served(&d2, z2);
        assert!(client_status(&p, Some(&d2)).update);
        let r = auto_update(&[p.clone(), profile(&client.join("none"), Build::V1121)], &d2, &app);
        assert_eq!(r.len(), 1);
        assert_eq!(r[0].1.as_ref().unwrap().version, "2026.1031.0900");
        assert_eq!(fs::read(client.join("Interface/AddOns/WrathUnleashedUI/WrathUnleashedUI.lua")).unwrap(), b"WrathUnleashedUI = { v = 2 }\n");
        assert!(auto_update(&[p.clone()], &d2, &app).is_empty(), "up to date: nothing to do");

        // Remove: exactly ours, the other addon stays, nothing of Leyline's is left.
        let rm = remove(&client).unwrap();
        assert_eq!(rm.removed_files, 4);
        assert!(!client.join("Interface/AddOns/WrathUnleashedUI").exists());
        assert!(!client.join("Interface/AddOns/OVQoL").exists());
        assert!(client.join("Interface/AddOns/Questie/Questie.toc").is_file());
        assert!(!client.join("Leyline").exists());
        assert!(remove(&client).is_err());
        assert!(fs::read_dir(app.join("downloads")).map(|d| d.count() == 0).unwrap_or(true), "no download left behind");
    }

    #[test]
    fn a_bad_download_installs_nothing() {
        let (_t, client, app) = setup();
        let (d, zip) = pack("2026.1030.1200", &entries(LUA));
        // The zip's checksum does not match.
        let mut wrong = served(&d, zip.clone());
        wrong.sha256 = "0".repeat(64);
        let e = install(&client, Build::V335a, &wrong, &app, false).unwrap_err();
        assert!(e.contains("checksum"), "{e}");
        // The zip matches, but a file inside is not the listed one.
        let mut d2 = served(&d, zip.clone());
        d2.files.insert("WrathUnleashedUI/WrathUnleashedUI.lua".into(), "1".repeat(64));
        let e = install(&client, Build::V335a, &d2, &app, false).unwrap_err();
        assert!(e.contains("did not check out"), "{e}");
        // A file the listing does not name.
        let mut extra = entries(LUA);
        extra.push(("OVQoL/extra.lua", b"x = 1\n"));
        let (d3, z3) = pack("2026.1030.1200", &extra);
        let mut d3 = served(&d3, z3);
        d3.files.remove("OVQoL/extra.lua");
        let e = install(&client, Build::V335a, &d3, &app, false).unwrap_err();
        assert!(e.contains("not in the listing"), "{e}");
        // Game data, even when listed and hashed: refused by the listing check and by the addon checks.
        let mut gd = entries(LUA);
        gd.push(("OVQoL/icon.tga", b"BLP2xxxx"));
        let (d4, z4) = pack("2026.1030.1200", &gd);
        let d4 = served(&d4, z4);
        let e = install(&client, Build::V335a, &d4, &app, false).unwrap_err();
        assert!(e.contains("game data"), "{e}");
        assert!(clean(Descriptor { files: [("OVQoL/x.blp".to_string(), "a".repeat(64))].into(), ..d.clone() }).is_none());
        assert!(!client.join("Interface/AddOns/WrathUnleashedUI").exists());
        assert!(!client.join("Leyline").exists(), "nothing of Leyline's left in the client");
    }

    #[test]
    fn never_touches_other_addons_without_an_ok() {
        let (_t, client, app) = setup();
        touch(&client, "Interface/AddOns/OVQoL/OVQoL.toc", b"## Interface: 30300\n## Title: my own copy\n");
        touch(&client, "Interface/AddOns/OVQoL/notes.txt", b"mine");
        let (d, zip) = pack("2026.1030.1200", &entries(LUA));
        let d = served(&d, zip);
        let p = profile(&client, Build::V335a);
        assert_eq!(client_status(&p, Some(&d)).foreign, ["OVQoL"]);
        let e = install(&client, Build::V335a, &d, &app, false).unwrap_err();
        assert!(e.starts_with(REPLACE_CONFIRM), "{e}");
        assert!(e.contains("OVQoL"));
        assert_eq!(fs::read(client.join("Interface/AddOns/OVQoL/notes.txt")).unwrap(), b"mine");
        assert!(!client.join("Interface/AddOns/WrathUnleashedUI").exists(), "nothing installed without the OK");

        // With the OK: theirs moves aside whole, ours goes in; Remove puts theirs back.
        let done = install(&client, Build::V335a, &d, &app, true).unwrap();
        assert_eq!(done.moved_aside.len(), 1);
        assert!(done.moved_aside[0].starts_with("Leyline/backup/OVQoL-"));
        assert_eq!(fs::read(client.join(&done.moved_aside[0]).join("notes.txt")).unwrap(), b"mine");
        assert_eq!(fs::read(client.join("Interface/AddOns/OVQoL/OVQoL.toc")).unwrap(), QTOC);
        assert_eq!(client_status(&p, Some(&d)).backups, ["OVQoL"]);
        let rm = remove(&client).unwrap();
        assert_eq!(rm.restored, ["Interface/AddOns/OVQoL"]);
        assert_eq!(fs::read(client.join("Interface/AddOns/OVQoL/notes.txt")).unwrap(), b"mine");
        assert!(!client.join("Leyline").exists());

        // An addon of ours that a Workshop or dropped mod put in: refused, that one is the player's to remove.
        let src = client.parent().unwrap().join("drop/OVQoL");
        touch(&src, "OVQoL.toc", b"## Interface: 30300\n## Title: dropped\nOVQoL.lua\n");
        touch(&src, "OVQoL.lua", b"x = 1\n");
        fs::remove_dir_all(client.join("Interface/AddOns/OVQoL")).unwrap();
        mods::install_local(&client, Build::V335a, &src, &|_| false).unwrap();
        let e = install(&client, Build::V335a, &d, &app, true).unwrap_err();
        assert!(e.contains("already installed by"), "{e}");
    }

    #[test]
    fn player_changes_survive_an_update() {
        let (_t, client, app) = setup();
        let (d1, z1) = pack("2026.1030.1200", &entries(LUA));
        install(&client, Build::V335a, &served(&d1, z1), &app, false).unwrap();
        fs::write(client.join("Interface/AddOns/WrathUnleashedUI/WrathUnleashedUI.lua"), b"-- my edit\n").unwrap();
        let (d2, z2) = pack("2026.1031.0900", &entries(b"WrathUnleashedUI = { v = 2 }\n"));
        let done = install(&client, Build::V335a, &served(&d2, z2), &app, false).unwrap();
        assert_eq!(done.kept.len(), 1, "{:?}", done.kept);
        assert_eq!(fs::read(client.join("Interface/AddOns/WrathUnleashedUI/WrathUnleashedUI.lua.yours")).unwrap(), b"-- my edit\n");
    }

    #[test]
    fn only_335a_and_only_the_release() {
        let t = tempfile::tempdir().unwrap();
        fake_1121(t.path(), false);
        let (d, zip) = pack("2026.1030.1200", &entries(LUA));
        let d = served(&d, zip);
        let p = profile(t.path(), Build::V1121);
        assert!(!client_status(&p, Some(&d)).supported);
        assert!(!should_offer(&p, &Prefs::default()));
        assert!(install(t.path(), Build::V1121, &d, t.path(), false).is_err());
        let ok = |u: &str| clean(Descriptor { download: u.into(), ..d.clone() }).is_some();
        assert!(ok("https://github.com/orionopenwow/Leyline/releases/download/leyline-addons/leyline-addons-1.zip"));
        assert!(!ok("https://github.com/someone/else/releases/download/leyline-addons/x.zip"));
        assert!(!ok("https://example.com/leyline-addons.zip"));
        assert!(clean(Descriptor { build: "1.12".into(), ..d.clone() }).is_none());
        assert!(clean(Descriptor { files: [("../evil.lua".to_string(), "a".repeat(64))].into(), ..d.clone() }).is_none());
        assert!(clean(Descriptor { files: [("Other/x.lua".to_string(), "a".repeat(64))].into(), ..d.clone() }).is_none());
        assert!(!should_offer(&profile(t.path(), Build::V335a), &Prefs { dont_ask: true, ..Prefs::default() }));
    }

    /// Our real addons (as make-addonpack.py takes them) pass the launcher's addon checks for a 3.3.5a client.
    #[test]
    fn the_real_addons_pass_the_checks() {
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let t = tempfile::tempdir().unwrap();
        for (name, rel) in [
            ("WrathUnleashedUI", "stream/fui-web/Interface/AddOns/WrathUnleashedUI"),
            ("OVArmory", "addons/OVArmory"),
            ("OVQoL", "addons/OVQoL"),
        ] {
            for f in mods::walk(&repo.join(rel)).unwrap() {
                if f.rel.to_ascii_lowercase().starts_with("readme") {
                    continue;
                }
                assert!(OUR_EXT.contains(&ext(&f.rel).as_str()), "{name}/{}", f.rel);
                touch(t.path(), &format!("{name}/{}", f.rel), &fs::read(&f.abs).unwrap());
            }
        }
        let plan = mods::validate_ours(&mods::walk(t.path()).unwrap(), Build::V335a);
        assert!(plan.errors.is_empty(), "{:?}", plan.errors);
        assert_eq!(plan.addons.len(), 3);
        // The Workshop's own check still keeps the realm's names for the realm.
        assert!(!mods::validate(&mods::walk(t.path()).unwrap(), Build::V335a).errors.is_empty());
    }

    #[test]
    fn listing_falls_back_to_the_last_good_copy_and_prefs_default_on() {
        let t = tempfile::tempdir().unwrap();
        let (d, _) = pack("2026.1030.1200", &entries(LUA));
        let d = Descriptor { download: "http://127.0.0.1:9/pack.zip".into(), ..d };
        let body = serde_json::to_vec(&d).unwrap();
        let base = serve_routes(vec![("/addonpack.json", "200 OK", body)]);
        let a = available(t.path(), &format!("{base}/addonpack.json"));
        assert_eq!(a.pack.as_ref().map(|p| p.version.as_str()), Some("2026.1030.1200"));
        let b = available(t.path(), &crate::net::testserver::dead_url());
        assert!(b.from_cache && b.error.is_some());
        assert_eq!(b.pack, a.pack);
        assert_eq!(cached(t.path()), a.pack);
        let p = prefs(t.path());
        assert!(p.auto_update && !p.dont_ask);
        save_prefs(t.path(), &Prefs { auto_update: false, dont_ask: true }).unwrap();
        assert_eq!(prefs(t.path()), Prefs { auto_update: false, dont_ask: true });
    }
}
