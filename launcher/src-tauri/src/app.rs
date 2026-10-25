//! The desktop app: Tauri commands over the core modules. The web UI in `launcher/ui/` calls these.

use crate::clients::{self, ClientProfile, Detection};
use crate::net::Listing;
use crate::settings::{self, Settings, Wine};
use crate::{catalog, launch, realms, status, BROWSER_PLAY_URL, OFFICIAL_REALM};
use serde::Serialize;
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::{AppHandle, State};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;

struct Core {
    dir: PathBuf,
    settings: Mutex<Settings>,
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
    tauri::async_runtime::spawn_blocking(move || {
        app.dialog().file().set_title("Choose your game client folder").blocking_pick_folder()
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
    let p = core.snapshot().client(&id).cloned().ok_or("No such client.")?;
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

/// Point the client at the realm, then start it.
#[tauri::command]
fn play(core: State<Core>, client: String, realm: String) -> Result<String, String> {
    let realm = realm.trim().to_string();
    if !clients::valid_realm_address(&realm) {
        return Err("That realm address does not look right (a host name, optionally :port).".into());
    }
    let (profile, wine) = core.update(|s| {
        s.selected_client = Some(client.clone());
        s.selected_realm = realm.clone();
        let c = s.client_mut(&client).ok_or("Pick a client first.")?;
        c.realmlist = realm.clone();
        Ok((c.clone(), s.wine.clone()))
    })?;
    clients::write_realmlist(&profile, &realm).map_err(|e| format!("Could not write realmlist.wtf: {e}"))?;
    let plan = launch::plan(&profile, &wine, launch::Os::current())?;
    launch::run(&plan)?;
    Ok(format!("Started {} on {realm}.", profile.name))
}

#[tauri::command]
async fn catalog_listing(core: State<'_, Core>) -> Result<Listing, String> {
    let dir = core.dir.clone();
    tauri::async_runtime::spawn_blocking(move || catalog::fetch(&dir)).await.map_err(|e| e.to_string())?
}

#[tauri::command]
async fn realm_listing(core: State<'_, Core>) -> Result<Listing, String> {
    let dir = core.dir.clone();
    tauri::async_runtime::spawn_blocking(move || realms::fetch(&dir)).await.map_err(|e| e.to_string())?
}

/// Open the browser client. Only that one address: the UI cannot open arbitrary URLs through this.
#[tauri::command]
fn open_browser_play(app: AppHandle) -> Result<(), String> {
    app.opener().open_url(BROWSER_PLAY_URL, None::<&str>).map_err(|e| e.to_string())
}

/// Ping the realm's login port and, for the official realm, read its status file (players, bots).
#[tauri::command]
async fn realm_status(realm: String) -> Result<status::RealmStatus, String> {
    let realm = realm.trim().to_string();
    if !clients::valid_realm_address(&realm) {
        return Err("That realm address does not look right.".into());
    }
    let url = (status::host_port(&realm).0 == OFFICIAL_REALM).then_some(status::OFFICIAL_STATUS_URL);
    tauri::async_runtime::spawn_blocking(move || status::check(&realm, url)).await.map_err(|e| e.to_string())
}

/// Open one of the launcher's fixed pages (`crate::LINKS`) by name: Discord, support, news, docs, the site.
#[tauri::command]
fn open_link(app: AppHandle, name: String) -> Result<(), String> {
    let url = crate::link(&name).ok_or("Unknown link.")?;
    app.opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
}

pub fn run() {
    let dir = settings::app_dir();
    let s = settings::load(&dir);
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .manage(Core { dir, settings: Mutex::new(s) })
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
            catalog_listing,
            realm_listing,
            open_browser_play,
            realm_status,
            open_link
        ])
        .run(tauri::generate_context!())
        .expect("error while running Leyline");
}
