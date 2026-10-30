//! The desktop app: Tauri commands over the core modules. The web UI in `launcher/ui/` calls these.
//!
//! The UI never hands the core a URL to fetch or a path to write: installs name a catalog project (looked up in
//! the cached catalog) or a file the player picked or dropped; links open only from the fixed list in `LINKS`
//! or from the set of addresses the core itself handed the UI (catalog credits, realm pages, the release page).

use crate::catalog::{self, Catalog};
use crate::clients::{self, ClientProfile, Detection};
use crate::host::{self, HostOs, HostStatus, KitInfo};
use crate::mods::{self, Installed, InstalledView, Removed};
use crate::net::{self, Listing};
use crate::realms::{self, RealmList};
use crate::settings::{self, Settings, Wine};
use crate::update::{self, Channel, UpdateInfo};
use crate::{launch, status, BROWSER_PLAY_URL, OFFICIAL_REALM};
use serde::Serialize;
use std::collections::HashSet;
use std::path::PathBuf;
use std::process::Child;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_updater::UpdaterExt;

struct Core {
    dir: PathBuf,
    settings: Mutex<Settings>,
    /// Addresses the core gave the UI, which `open_url` may open.
    known_urls: Mutex<HashSet<String>>,
    /// One mod operation at a time.
    mods_lock: Arc<Mutex<()>>,
    /// Games Leyline started: a launcher update never restarts while one of them runs.
    games: Mutex<Vec<Child>>,
    /// The launcher's own update: what the last check said, and a downloaded update waiting for "Restart".
    upd: Mutex<UpdState>,
}

impl Core {
    fn update<T>(&self, f: impl FnOnce(&mut Settings) -> Result<T, String>) -> Result<T, String> {
        let mut s = self.settings.lock().map_err(|_| "settings lock poisoned")?;
        let out = f(&mut s)?;
        settings::save(&self.dir, &s).map_err(|e| format!("Could not save settings: {e}"))?;
        Ok(out)
    }
    fn snapshot(&self) -> Settings {
        self.settings.lock().map(|s| s.clone()).unwrap_or_default()
    }
    fn client(&self, id: &str) -> Result<ClientProfile, String> {
        self.snapshot().client(id).cloned().ok_or_else(|| "Pick a game client first.".into())
    }
    fn allow(&self, urls: impl IntoIterator<Item = String>) {
        if let Ok(mut k) = self.known_urls.lock() {
            for u in urls {
                if net::plain_https(&u) && k.len() < 20_000 {
                    k.insert(u);
                }
            }
        }
    }
    fn kit(&self) -> Option<PathBuf> {
        Some(self.snapshot().host_kit).filter(|k| !k.is_empty()).map(PathBuf::from)
    }
    /// A game Leyline started is still running.
    fn game_running(&self) -> bool {
        let Ok(mut g) = self.games.lock() else { return true };
        g.retain_mut(|c| matches!(c.try_wait(), Ok(None)));
        !g.is_empty()
    }
}

fn blocking<T: Send + 'static>(f: impl FnOnce() -> Result<T, String> + Send + 'static) -> impl std::future::Future<Output = Result<T, String>> {
    async move { tauri::async_runtime::spawn_blocking(f).await.map_err(|e| e.to_string())? }
}

#[derive(Serialize)]
struct AppState {
    version: &'static str,
    settings: Settings,
    official_realm: &'static str,
    browser_url: &'static str,
    windows: bool,
    data_dir: String,
}

#[tauri::command]
fn get_state(core: State<Core>) -> AppState {
    AppState {
        version: env!("CARGO_PKG_VERSION"),
        settings: core.snapshot(),
        official_realm: OFFICIAL_REALM,
        browser_url: BROWSER_PLAY_URL,
        windows: cfg!(windows),
        data_dir: core.dir.display().to_string(),
    }
}

#[tauri::command]
async fn pick_folder(app: AppHandle) -> Option<String> {
    pick(app, "Choose your game client folder", false, false).await
}

async fn pick(app: AppHandle, title: &'static str, file: bool, mods_filter: bool) -> Option<String> {
    tauri::async_runtime::spawn_blocking(move || {
        let d = app.dialog().file().set_title(title);
        if file {
            let d = if mods_filter { d.add_filter("Mods (.zip, .MPQ, .dll, .asi)", &["zip", "mpq", "MPQ", "dll", "DLL", "asi"]) } else { d };
            d.blocking_pick_file()
        } else {
            d.blocking_pick_folder()
        }
    })
    .await
    .ok()
    .flatten()
    .and_then(|p| p.into_path().ok())
    .map(|p| p.display().to_string())
}

#[tauri::command]
fn detect_client(path: String) -> Result<Detection, String> {
    clients::detect(&PathBuf::from(path)).map_err(|e| e.to_string())
}

#[derive(Serialize)]
struct Added {
    profile: ClientProfile,
    detection: Detection,
}

#[tauri::command]
fn add_client(core: State<Core>, path: String) -> Result<Added, String> {
    let path = PathBuf::from(path.trim());
    let detection = clients::detect(&path).map_err(|e| e.to_string())?;
    core.update(|s| {
        if s.clients.iter().any(|c| c.path == path) {
            return Err("That folder is already in your clients.".into());
        }
        let profile = clients::new_profile(&path, &detection, &s.clients);
        s.clients.push(profile.clone());
        if s.selected_client.is_none() {
            s.selected_client = Some(profile.id.clone());
        }
        Ok(Added { profile, detection })
    })
}

#[tauri::command]
fn check_client(core: State<Core>, id: String) -> Result<Detection, String> {
    let p = core.client(&id)?;
    clients::detect(&p.path).map_err(|e| e.to_string())
}

#[tauri::command]
fn rename_client(core: State<Core>, id: String, name: String) -> Result<(), String> {
    let name = name.trim().chars().take(60).collect::<String>();
    if name.is_empty() {
        return Err("A name is needed.".into());
    }
    core.update(|s| {
        s.client_mut(&id).ok_or("No such client.")?.name = name;
        Ok(())
    })
}

#[tauri::command]
fn remove_client(core: State<Core>, id: String) -> Result<(), String> {
    core.update(|s| s.remove_client(&id).then_some(()).ok_or_else(|| "No such client.".into()))
}

#[tauri::command]
fn select(core: State<Core>, client: Option<String>, realm: String) -> Result<(), String> {
    core.update(|s| {
        s.selected_client = client;
        s.selected_realm = realm.trim().to_string();
        Ok(())
    })
}

#[tauri::command]
fn set_wine(core: State<Core>, wine: Wine) -> Result<(), String> {
    core.update(|s| {
        s.wine = wine;
        Ok(())
    })
}

/// Point the client at `realm` (its realm file: realmlist.wtf or Config.wtf, by build), remember it,
/// optionally start it.
fn point_and_play(core: &Core, client: &str, realm: &str, start: bool) -> Result<String, String> {
    let realm = realm.trim().to_string();
    if !clients::valid_realm_address(&realm) {
        return Err("That realm address does not look right (a host name, optionally :port).".into());
    }
    // A listed realm with a known build takes only clients of that build.
    if let Some(r) = realms::cached(&core.dir).into_iter().find(|r| r.address.as_deref() == Some(realm.as_str())) {
        let p = core.client(client)?;
        if r.build.is_some_and(|b| b != p.build) {
            let s = core.snapshot();
            return Err(realms::pick_client(&r, &s.clients, Some(client))
                .map(|c| format!("{} runs {}: pick {} for it.", r.name, c.build.version(), c.name))
                .unwrap_or_else(|e| e));
        }
    }
    let (profile, wine) = core.update(|s| {
        s.selected_client = Some(client.to_string());
        s.selected_realm = realm.clone();
        let c = s.client_mut(client).ok_or("Pick a game client first.")?;
        c.realmlist = realm.clone();
        Ok((c.clone(), s.wine.clone()))
    })?;
    clients::write_realmlist(&profile, &realm).map_err(|e| format!("Could not write realmlist.wtf: {e}"))?;
    if !start {
        return Ok(format!("{} now points at {realm}.", profile.name));
    }
    let plan = launch::plan(&profile, &wine, launch::Os::current())?;
    let child = launch::run(&plan)?;
    if let Ok(mut g) = core.games.lock() {
        g.push(child);
    }
    Ok(format!("Started {} on {realm}.", profile.name))
}

/// Point the client at the realm, then start it.
#[tauri::command]
fn play(core: State<Core>, client: String, realm: String) -> Result<String, String> {
    point_and_play(&core, &client, &realm, true)
}

/// Play on a realm from the Realms page: the official realm or a listed Beacon (its relay address). `client` is
/// the player's pick; when its build does not fit the realm, one of their clients that fits is used, or the
/// reply says which build is missing.
#[tauri::command]
async fn play_realm(core: State<'_, Core>, client: String, slug: String) -> Result<String, String> {
    let dir = core.dir.clone();
    let realm = realms::cached(&dir).into_iter().find(|r| r.slug == slug).ok_or("That realm is not on the list any more.")?;
    let client = {
        let s = core.snapshot();
        realms::pick_client(&realm, &s.clients, Some(&client))?.id.clone()
    };
    let r2 = realm.clone();
    let addr = blocking(move || realms::desktop_address(&r2, |relay| format!("https://{relay}"))).await?;
    let mut msg = point_and_play(&core, &client, &addr, true)?;
    if !realm.official && realm.state != "live" {
        msg.push_str(" The list says this realm is offline right now, so it may not answer.");
    }
    Ok(msg)
}

#[derive(Serialize)]
struct Joined {
    address: String,
    name: String,
}

/// A private realm's invite link: open its door for this PC (the relay's knock), then point the client at it.
#[tauri::command]
async fn join_invite(core: State<'_, Core>, client: String, link: String) -> Result<Joined, String> {
    core.client(&client)?;
    let (relay, rid, secret) = realms::parse_invite(&link).ok_or("That is not an invite link (https://<relay>/join/<realm>#<code>).")?;
    let (address, name) = blocking(move || realms::knock(&format!("https://{relay}"), &rid, &secret)).await?;
    point_and_play(&core, &client, &address, false)?;
    Ok(Joined { address, name })
}

/// "Back to Wrath": point the client at the official realm again.
#[tauri::command]
fn back_to_official(core: State<Core>, client: String) -> Result<String, String> {
    point_and_play(&core, &client, OFFICIAL_REALM, false)
}

/// Put back the realmlist the player had before Leyline.
#[tauri::command]
fn restore_realmlist(core: State<Core>, client: String) -> Result<String, String> {
    let p = core.client(&client)?;
    if !clients::restore_realmlist(&p).map_err(|e| e.to_string())? {
        return Ok("Leyline never changed this client's realmlist, so there is nothing to put back.".into());
    }
    let now = clients::read_realmlist(&p).unwrap_or_default();
    core.update(|s| {
        if let Some(c) = s.client_mut(&client) {
            c.realmlist = now.clone();
        }
        Ok(())
    })?;
    Ok(format!("Put back your own realmlist ({}).", if now.is_empty() { "empty" } else { &now }))
}

#[tauri::command]
async fn realm_listing(core: State<'_, Core>) -> Result<Listing, String> {
    let dir = core.dir.clone();
    blocking(move || realms::fetch(&dir)).await
}

#[tauri::command]
async fn realms_list(core: State<'_, Core>) -> Result<RealmList, String> {
    let dir = core.dir.clone();
    let l = blocking(move || Ok(realms::fetch_all(&dir))).await?;
    core.allow(l.realms.iter().flat_map(|r| [r.join_url.clone(), r.discord.clone()]).flatten());
    Ok(l)
}

/// Open the browser client. Only that one address: the UI cannot open arbitrary URLs through this.
#[tauri::command]
fn open_browser_play(app: AppHandle) -> Result<(), String> {
    app.opener().open_url(BROWSER_PLAY_URL, None::<&str>).map_err(|e| e.to_string())
}

/// Ping the realm's login port and read its status file: the official one, or a relay realm's own.
#[tauri::command]
async fn realm_status(realm: String, status_url: Option<String>) -> Result<status::RealmStatus, String> {
    let realm = realm.trim().to_string();
    if !clients::valid_realm_address(&realm) {
        return Err("That realm address does not look right.".into());
    }
    let url = match status_url {
        Some(u) if realms::status_url_ok(&u) => Some(u),
        Some(_) => return Err("Not a realm status address.".into()),
        None => (status::host_port(&realm).0 == OFFICIAL_REALM).then(|| status::OFFICIAL_STATUS_URL.to_string()),
    };
    blocking(move || Ok(status::check(&realm, url.as_deref()))).await
}

/// Open one of the launcher's fixed pages (`crate::LINKS`) by name: Discord, support, news, docs, the site.
#[tauri::command]
fn open_link(app: AppHandle, name: String) -> Result<(), String> {
    let url = crate::link(&name).ok_or("Unknown link.")?;
    app.opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
}

/// Open an address the core handed the UI (a mod's repo or page, an author, a realm's join page or Discord,
/// the release page). Anything else is refused.
#[tauri::command]
fn open_url(app: AppHandle, core: State<Core>, url: String) -> Result<(), String> {
    let ok = core.known_urls.lock().map(|k| k.contains(&url)).unwrap_or(false);
    if !ok || !net::plain_https(&url) {
        return Err("Leyline only opens the pages it listed itself.".into());
    }
    app.opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
}

// ------------------------------------------------------------------------------------------------ mods

#[tauri::command]
async fn mods_catalog(core: State<'_, Core>) -> Result<Catalog, String> {
    let dir = core.dir.clone();
    let c = blocking(move || catalog::fetch(&dir)).await?;
    core.allow(c.projects.iter().flat_map(|p| [p.repo.clone(), p.page.clone(), p.author_url.clone()]).filter(|u| !u.is_empty()));
    Ok(c)
}

/// The catalog count (L0's read-only listing shape), for the side bar.
#[tauri::command]
async fn catalog_listing(core: State<'_, Core>) -> Result<Listing, String> {
    let c = mods_catalog(core).await?;
    Ok(Listing {
        count: c.projects.len(),
        names: c.projects.iter().take(100).map(|p| p.name.clone()).collect(),
        from_cache: c.from_cache,
        saved_at: c.saved_at,
        error: c.error,
    })
}

#[derive(Serialize)]
struct ClientMods {
    client: String,
    build: clients::Build,
    mods: Vec<InstalledView>,
}

#[tauri::command]
fn mods_installed(core: State<Core>, client: String) -> Result<ClientMods, String> {
    let p = core.client(&client)?;
    let man = mods::load(&p.path);
    let cat = catalog::cached(&core.dir, catalog::URL).unwrap_or_default();
    Ok(ClientMods { client, build: p.build, mods: mods::with_updates(&man, &cat, p.build) })
}

fn with_lock<T>(core: &Core, f: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
    let _g = core.mods_lock.lock().map_err(|_| "mod lock poisoned")?;
    f()
}

/// Install (or update) a catalog mod into a client. The project is looked up in the cached catalog by id.
#[tauri::command]
async fn mod_install(core: State<'_, Core>, client: String, project: String) -> Result<Installed, String> {
    let p = core.client(&client)?;
    let cat = catalog::cached(&core.dir, catalog::URL).ok_or("Open Discover first so Leyline has the catalog.")?;
    let proj = cat.into_iter().find(|x| x.id == project).ok_or("That mod is not in the catalog any more.")?;
    let origin = net::origin(catalog::URL).unwrap_or_default();
    let lock = core.mods_lock.clone();
    let scratch = core.dir.clone();
    let ok_keys = core.snapshot().native_ok;
    blocking(move || {
        let _g = lock.lock().map_err(|_| "mod lock poisoned")?;
        mods::install_project(&p.path, p.build, &proj, &origin, &scratch, &|k: &str| ok_keys.iter().any(|x| x == k))
    })
    .await
}

/// Install a dropped or picked .zip, .MPQ, native file or folder.
#[tauri::command]
fn mod_install_local(core: State<Core>, client: String, path: String) -> Result<Installed, String> {
    let p = core.client(&client)?;
    let src = PathBuf::from(path.trim());
    if src.starts_with(&p.path) {
        return Err("That is already inside this client's folder: drop the zip or folder from somewhere else.".into());
    }
    let ok_keys = core.snapshot().native_ok;
    with_lock(&core, || mods::install_local(&p.path, p.build, &src, &|k: &str| ok_keys.iter().any(|x| x == k)))
}

/// The player read the native-code notice for this mod and said yes: remembered, so it is asked only once.
/// Nothing is installed or run here; the UI installs again afterwards.
#[tauri::command]
fn mod_native_confirm(core: State<Core>, key: String) -> Result<(), String> {
    let ok = !key.is_empty() && key.len() <= 80 && key.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, ':' | '.' | '_' | '-'));
    if !ok {
        return Err("That is not a mod.".into());
    }
    core.update(|s| {
        if !s.native_allowed(&key) {
            s.native_ok.push(key);
        }
        Ok(())
    })
}

#[derive(Serialize)]
struct ModUpdate {
    client: String,
    client_name: String,
    key: String,
    name: String,
    version: String,
    update: String,
}

/// Every installed Workshop mod, in every client, that the cached catalog has a newer version of (the title
/// bar's update pill and UPDATE ALL).
#[tauri::command]
fn mods_updates(core: State<Core>) -> Vec<ModUpdate> {
    let cat = catalog::cached(&core.dir, catalog::URL).unwrap_or_default();
    let mut out = Vec::new();
    for c in core.snapshot().clients {
        let man = mods::load(&c.path);
        for v in mods::with_updates(&man, &cat, c.build) {
            if let Some(update) = v.update {
                out.push(ModUpdate {
                    client: c.id.clone(),
                    client_name: c.name.clone(),
                    key: v.mod_.key,
                    name: v.mod_.name,
                    version: v.mod_.version,
                    update,
                });
            }
        }
    }
    out
}

#[tauri::command]
fn mod_set_enabled(core: State<Core>, client: String, key: String, on: bool) -> Result<(), String> {
    let p = core.client(&client)?;
    with_lock(&core, || mods::set_enabled(&p.path, &key, on))
}

#[tauri::command]
fn mod_uninstall(core: State<Core>, client: String, key: String) -> Result<Removed, String> {
    let p = core.client(&client)?;
    with_lock(&core, || mods::uninstall(&p.path, &key))
}

#[tauri::command]
async fn pick_mod_file(app: AppHandle) -> Option<String> {
    pick(app, "Choose a mod (.zip), a client patch (.MPQ) or a native mod (.dll, .asi)", true, true).await
}

#[tauri::command]
async fn pick_mod_folder(app: AppHandle) -> Option<String> {
    pick(app, "Choose an addon folder", false, false).await
}

// ------------------------------------------------------------------------------------------------ hosting

fn kit_info(core: &Core) -> KitInfo {
    let kit = core.kit();
    host::inspect(kit.as_deref(), dirs::download_dir().as_deref())
}

#[tauri::command]
fn host_info(core: State<Core>) -> KitInfo {
    kit_info(&core)
}

#[tauri::command]
fn set_host_kit(core: State<Core>, path: String) -> Result<KitInfo, String> {
    let p = PathBuf::from(path.trim());
    if !p.is_dir() {
        return Err("That is not a folder.".into());
    }
    core.update(|s| {
        s.host_kit = p.display().to_string();
        Ok(())
    })?;
    Ok(kit_info(&core))
}

#[tauri::command]
async fn pick_host_kit(app: AppHandle) -> Option<String> {
    pick(app, "Choose your host kit folder", false, false).await
}

/// Copy a realm file found in Downloads into the kit.
#[tauri::command]
fn host_copy_seed(core: State<Core>, file_name: String) -> Result<KitInfo, String> {
    let kit = core.kit().ok_or("Choose your host kit folder first.")?;
    let info = kit_info(&core);
    let seed = info.seeds.iter().find(|s| s.file_name == file_name && !s.in_kit).ok_or("That realm file is not in Downloads any more.")?;
    host::copy_seed_into_kit(&seed.path, &kit)?;
    Ok(kit_info(&core))
}

/// Start the kit (a seed's first run, or the kit's own host script) in a window of its own.
#[tauri::command]
fn host_start(core: State<Core>, seed: Option<String>) -> Result<String, String> {
    let kit = core.kit().ok_or("Choose your host kit folder first.")?;
    let plan = host::plan(&kit, seed.as_deref(), HostOs::current(), host::on_path)?;
    host::run(&plan)?;
    Ok(plan.note)
}

/// The kit's realm as the relay sees it.
#[tauri::command]
async fn host_status(core: State<'_, Core>, realm_id: String) -> Result<HostStatus, String> {
    if !realms::realm_id_ok(&realm_id) {
        return Err("That is not a realm id.".into());
    }
    let info = kit_info(&core);
    let relay = info.realm.as_ref().filter(|r| r.realm_id == realm_id).map(|r| r.relay.clone()).unwrap_or_else(|| realms::RELAY.into());
    let listed = realms::cached(&core.dir).iter().any(|r| r.realm_id.as_deref() == Some(realm_id.as_str()));
    blocking(move || host::status(&format!("https://{relay}"), &realm_id, listed)).await
}

// ------------------------------------------------------------------------------------------------ updates

/// What the title bar and Settings show about Leyline's own updates.
#[derive(Debug, Clone, Default, Serialize)]
struct UpdView {
    /// `auto`: downloads in the background, installs on "Restart". `link`: only a link to the release page.
    mode: &'static str,
    /// Why it is `link`, in plain words.
    note: String,
    channel: Channel,
    info: Option<UpdateInfo>,
    checking: bool,
    downloading: bool,
    /// A downloaded, signature-checked version waiting for "Restart".
    ready: Option<String>,
    error: Option<String>,
    game_running: bool,
    /// Seconds since 1970 of the last check.
    checked_at: Option<u64>,
}

#[derive(Default)]
struct UpdState {
    view: UpdView,
    pending: Option<(tauri_plugin_updater::Update, Vec<u8>)>,
}

/// Whether this build can update itself, and if not, why.
fn updater_mode(app: &AppHandle) -> (&'static str, String) {
    if cfg!(debug_assertions) {
        return ("link", "This is a development build: it does not update itself.".into());
    }
    let pk = app.config().plugins.0.get("updater").and_then(|u| u.get("pubkey")).and_then(|v| v.as_str()).unwrap_or("");
    if !update::pubkey_ok(pk) {
        return ("link", "Automatic updates are not turned on for this build yet: new versions are on the release page.".into());
    }
    ("auto", String::new())
}

fn now_secs() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn upd_view(core: &Core) -> UpdView {
    let mut v = core.upd.lock().map(|u| u.view.clone()).unwrap_or_default();
    v.game_running = core.game_running();
    v.channel = core.snapshot().update_channel;
    v
}

/// Look for a newer Leyline on the player's channel; in `auto` mode, download it in the background so it is
/// ready for "Restart". Never installs and never restarts by itself.
async fn run_update_check(app: AppHandle) -> UpdView {
    let core = app.state::<Core>();
    let (mode, note) = updater_mode(&app);
    let channel = core.snapshot().update_channel;
    if let Ok(mut u) = core.upd.lock() {
        if u.view.checking || u.view.downloading {
            drop(u);
            return upd_view(&core);
        }
        u.view.checking = true;
        u.view.mode = mode;
        u.view.note = note;
    }
    let dir = core.dir.clone();
    let info = blocking(move || Ok(update::check(&dir, env!("CARGO_PKG_VERSION"), channel))).await.unwrap_or_else(|e| UpdateInfo {
        current: env!("CARGO_PKG_VERSION").into(),
        channel,
        error: Some(e),
        ..Default::default()
    });
    core.allow(info.url.clone());
    let want = info.newer.then(|| info.manifest_url.clone()).flatten().filter(|_| mode == "auto");
    let already = core.upd.lock().ok().and_then(|u| u.pending.as_ref().map(|(p, _)| p.version.clone()));
    if let Ok(mut u) = core.upd.lock() {
        u.view.checking = false;
        u.view.checked_at = Some(now_secs());
        u.view.error = info.error.clone();
        u.view.downloading = want.is_some() && already.as_deref() != info.latest.as_deref();
        u.view.info = Some(info.clone());
    }
    if let (Some(url), true) = (want, already.as_deref() != info.latest.as_deref()) {
        let res: Result<Option<(tauri_plugin_updater::Update, Vec<u8>)>, String> = async {
            // Leyline's own check of the manifest first: this repo's release downloads only, signed.
            let mtext = blocking({
                let url = url.clone();
                move || net::get(&url, net::TIMEOUT)
            })
            .await?;
            let m = update::parse_manifest(&mtext)?;
            if update::cmp_versions(&m.version, info.latest.as_deref().unwrap_or("")) != Some(std::cmp::Ordering::Equal) {
                return Err("The update manifest names another version than its release.".into());
            }
            let endpoint: tauri::Url = url.parse().map_err(|e| format!("{e}"))?;
            let updater = app.updater_builder().endpoints(vec![endpoint]).map_err(|e| e.to_string())?.build().map_err(|e| e.to_string())?;
            let Some(up) = updater.check().await.map_err(|e| e.to_string())? else { return Ok(None) };
            let bytes = up.download(|_, _| {}, || {}).await.map_err(|e| e.to_string())?;
            Ok(Some((up, bytes)))
        }
        .await;
        if let Ok(mut u) = core.upd.lock() {
            u.view.downloading = false;
            match res {
                Ok(Some((up, bytes))) => {
                    u.view.ready = Some(up.version.clone());
                    u.pending = Some((up, bytes));
                }
                Ok(None) => {}
                Err(e) => u.view.error = Some(format!("Could not get the update: {e}")),
            }
        }
    }
    upd_view(&core)
}

#[tauri::command]
fn launcher_update_state(core: State<Core>) -> UpdView {
    upd_view(&core)
}

#[tauri::command]
async fn launcher_update_check(app: AppHandle) -> Result<UpdView, String> {
    Ok(run_update_check(app).await)
}

#[tauri::command]
async fn set_update_channel(app: AppHandle, channel: Channel) -> Result<UpdView, String> {
    {
        let core = app.state::<Core>();
        core.update(|s| {
            s.update_channel = channel;
            Ok(())
        })?;
        // A download from the other channel is not wanted any more.
        if let Ok(mut u) = core.upd.lock() {
            u.pending = None;
            u.view.ready = None;
        };
    }
    Ok(run_update_check(app).await)
}

/// "Update ready, restart": install the downloaded update and start the new Leyline. Refused while a game
/// Leyline started is running, so a game is never cut off.
#[tauri::command]
fn launcher_update_restart(app: AppHandle, core: State<Core>) -> Result<(), String> {
    if core.game_running() {
        return Err("Your game is still running. Close it first: Leyline restarts only when no game is open.".into());
    }
    let pending = core.upd.lock().map_err(|_| "update lock poisoned")?.pending.take();
    let Some((up, bytes)) = pending else {
        return Err("No update is ready yet.".into());
    };
    // On Windows the installer takes over and closes Leyline itself; elsewhere Leyline restarts into the new one.
    up.install(&bytes).map_err(|e| format!("The update could not be installed: {e}"))?;
    app.restart()
}

/// Check at start, then every 6 hours, for as long as Leyline runs.
fn start_update_timer(app: AppHandle) {
    std::thread::spawn(move || loop {
        tauri::async_runtime::block_on(run_update_check(app.clone()));
        std::thread::sleep(Duration::from_secs(update::CHECK_EVERY_SECS));
    });
}

pub fn run() {
    let dir = settings::app_dir();
    let s = settings::load(&dir);
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Core {
            dir,
            settings: Mutex::new(s),
            known_urls: Mutex::new(HashSet::new()),
            mods_lock: Arc::new(Mutex::new(())),
            games: Mutex::new(Vec::new()),
            upd: Mutex::new(UpdState::default()),
        })
        .setup(|app| {
            start_update_timer(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_state,
            pick_folder,
            detect_client,
            add_client,
            check_client,
            rename_client,
            remove_client,
            select,
            set_wine,
            play,
            play_realm,
            join_invite,
            back_to_official,
            restore_realmlist,
            catalog_listing,
            realm_listing,
            realms_list,
            open_browser_play,
            realm_status,
            open_link,
            open_url,
            mods_catalog,
            mods_installed,
            mod_install,
            mod_install_local,
            mod_set_enabled,
            mod_uninstall,
            mod_native_confirm,
            mods_updates,
            pick_mod_file,
            pick_mod_folder,
            host_info,
            set_host_kit,
            pick_host_kit,
            host_copy_seed,
            host_start,
            host_status,
            launcher_update_state,
            launcher_update_check,
            launcher_update_restart,
            set_update_channel,
            crate::themes::commands::themes_list, crate::themes::commands::theme_apply, crate::themes::commands::theme_css, crate::themes::commands::theme_install, crate::themes::commands::theme_install_local, crate::themes::commands::theme_remove, crate::themes::commands::pick_theme, // themes.rs
            // Host pack, Docker, realm stop/logs/invite, P2P and torrent flags (src/p2p/cmds.rs)
            crate::p2p::cmds::hostpack_info,
            crate::p2p::cmds::hostpack_install,
            crate::p2p::cmds::docker_info,
            crate::p2p::cmds::host_stop,
            crate::p2p::cmds::host_logs,
            crate::p2p::cmds::host_invite,
            crate::p2p::cmds::host_new_invite,
            crate::p2p::cmds::p2p_flags,
            crate::p2p::cmds::p2p_set_flag,
            crate::p2p::cmds::p2p_set_limits,
            crate::p2p::cmds::p2p_nat_check,
            // Leyline friends and messages (social.rs)
            crate::social::commands::social_status,
            crate::social::commands::social_signin_start,
            crate::social::commands::social_signin_reopen,
            crate::social::commands::social_signin_poll,
            crate::social::commands::social_signin_cancel,
            crate::social::commands::social_call,
            crate::social::commands::social_signout
        ])
        .run(tauri::generate_context!())
        .expect("error while running Leyline");
}
