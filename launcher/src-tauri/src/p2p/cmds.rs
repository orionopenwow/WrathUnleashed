//! The desktop app's commands for the Host pack, Docker, the realm's stop/logs/invite, and the P2P/torrent
//! flags (Settings > Advanced). Registered in `app.rs`'s handler list; the UI is `launcher/ui/host.js`.
//!
//! None of them takes a URL or a path from the UI: the pack comes from the catalog or our release, the kit
//! folder from the saved settings, the flag names from `flags::KNOWN`.

use crate::host::docker::{self, DockerInfo};
use crate::host::pack::{self, Installed, PackInfo};
use crate::host::{self, HostOs};
use crate::p2p::flags::{self, Limits, Local, View};
use crate::p2p::nat::{self, NatReport};
use crate::p2p::transfer::NoSwarm;
use crate::settings;
use std::path::PathBuf;
use std::time::Duration;

fn blocking<T: Send + 'static>(f: impl FnOnce() -> Result<T, String> + Send + 'static) -> impl std::future::Future<Output = Result<T, String>> {
    async move { tauri::async_runtime::spawn_blocking(f).await.map_err(|e| e.to_string())? }
}

fn kit() -> Result<PathBuf, String> {
    let k = settings::load(&settings::app_dir()).host_kit;
    if k.is_empty() {
        return Err("Get the Host pack, or choose your host kit folder, first.".into());
    }
    Ok(PathBuf::from(k))
}

#[tauri::command]
pub async fn hostpack_info() -> Result<PackInfo, String> {
    blocking(|| Ok(pack::info(&settings::app_dir(), pack::FALLBACK_URL))).await
}

/// Download, check and install (or update) the Host pack. Returns what is installed and the kit folder, which
/// the UI then makes the host kit (`set_host_kit`).
#[tauri::command]
pub async fn hostpack_install() -> Result<(Installed, String), String> {
    blocking(|| {
        let dir = settings::app_dir();
        let d = pack::available(&dir, pack::FALLBACK_URL)?;
        let i = pack::install(&dir, &d, &flags::current(&dir), &NoSwarm)?;
        Ok((i, pack::kit_dir(&dir).display().to_string()))
    })
    .await
}

#[tauri::command]
pub async fn docker_info() -> Result<DockerInfo, String> {
    blocking(|| Ok(docker::detect(HostOs::current(), &|a| docker::run_docker(a, None, Duration::from_secs(15))))).await
}

/// Host any client: the realm profiles the kit can run for the clients Leyline found on this PC, and the saved
/// choice (host/profiles.rs). Nothing here takes a path from the UI: clients by their id, profiles by their name.
#[tauri::command]
pub async fn host_profiles() -> Result<(Vec<host::profiles::Offer>, Option<host::profiles::Choice>), String> {
    blocking(|| {
        let s = settings::load(&settings::app_dir());
        let k = (!s.host_kit.is_empty()).then(|| PathBuf::from(&s.host_kit));
        let choice = k.as_deref().and_then(host::profiles::read_choice);
        Ok((host::profiles::offers(k.as_deref(), &s.clients), choice))
    })
    .await
}

#[tauri::command]
pub async fn host_choose(profile: String, client_id: Option<String>) -> Result<host::profiles::Choice, String> {
    blocking(move || {
        let s = settings::load(&settings::app_dir());
        let client = match client_id.as_deref() {
            Some(id) => Some(s.clients.iter().find(|c| c.id == id).ok_or("That client is not in your clients any more.")?),
            None => None,
        };
        host::profiles::choose(&kit()?, &profile, client)
    })
    .await
}

#[tauri::command]
pub async fn host_stop() -> Result<String, String> {
    blocking(|| host::stop(&kit()?)).await
}

#[tauri::command]
pub async fn host_logs(lines: Option<u32>) -> Result<String, String> {
    blocking(move || host::logs(&kit()?, lines.unwrap_or(200))).await
}

/// The invite link the kit wrote (None before the first start).
#[tauri::command]
pub fn host_invite() -> Result<Option<String>, String> {
    Ok(host::invite(&kit()?))
}

#[tauri::command]
pub async fn host_new_invite() -> Result<String, String> {
    blocking(|| host::new_invite(&kit()?)).await
}

/// The realm list details (tags, region, language, player limit, direct connections) from the kit's beacon.json.
#[tauri::command]
pub fn host_listing() -> Result<host::ListingDetails, String> {
    Ok(host::listing_details(&kit()?))
}

#[tauri::command]
pub async fn host_listing_set(details: host::ListingDetails) -> Result<String, String> {
    blocking(move || host::set_listing_details(&kit()?, &details)).await
}

#[tauri::command]
pub async fn p2p_flags() -> Result<View, String> {
    blocking(|| Ok(flags::load(&settings::app_dir(), flags::URL))).await
}

/// Set one flag on this PC (`value` true/false), or follow the site again (`value` null).
#[tauri::command]
pub fn p2p_set_flag(name: String, value: Option<bool>) -> Result<Local, String> {
    flags::set_local(&settings::app_dir(), &name, value)
}

#[tauri::command]
pub fn p2p_set_limits(limits: Option<Limits>) -> Result<Local, String> {
    flags::set_local_limits(&settings::app_dir(), limits)
}

/// "Help the network: relay for others": start (`on`) or stop the Host pack's community relay. Needs the site's
/// `relay_volunteer` offer and this PC's own "On" (`flags::volunteer_allowed`).
#[tauri::command]
pub async fn host_volunteer_relay(on: bool, public_host: Option<String>, region: Option<String>) -> Result<String, String> {
    blocking(move || {
        let dir = settings::app_dir();
        let site = flags::load(&dir, flags::URL).site;
        host::volunteer_relay(&kit()?, &site, &flags::load_local(&dir), on, public_host.as_deref(), region.as_deref())
    })
    .await
}

/// The NAT check, only when direct connections are on.
#[tauri::command]
pub async fn p2p_nat_check() -> Result<NatReport, String> {
    blocking(|| {
        let f = flags::current(&settings::app_dir());
        if !f.p2p_hosting {
            return Err("Direct connections are off (Settings > Advanced).".into());
        }
        let servers = if f.stun.is_empty() { vec!["stun.cloudflare.com:3478".to_string()] } else { f.stun.clone() };
        Ok(nat::check(&servers, Duration::from_secs(2)))
    })
    .await
}

// Shared magnet: links (p2p/magnet.rs), behind the `magnet_links` flag. With the flag off every command answers "off"
// and does nothing. Only info-hashes of Leyline's own checked packages (the cached catalog) are accepted.

fn inbox() -> &'static std::sync::Mutex<crate::p2p::magnet::Inbox> {
    static INBOX: std::sync::OnceLock<std::sync::Mutex<crate::p2p::magnet::Inbox>> = std::sync::OnceLock::new();
    INBOX.get_or_init(Default::default)
}

/// A `magnet:` link Leyline was started with (its arguments). Queued for `magnet_pending`; nothing is fetched.
pub fn magnet_from_args() {
    if let Some(uri) = crate::p2p::magnet::from_args(std::env::args()) {
        let dir = settings::app_dir();
        let flags = flags::current(&dir);
        if flags.magnet_links {
            if let Ok(mut i) = inbox().lock() {
                crate::p2p::magnet::open(&uri, &flags, &crate::p2p::magnet::known(&dir), &mut i);
            }
        }
    }
}

/// Open a shared magnet link: `{"status":"off"}`, `{"status":"accepted","package":{..},"open":<leyline link>}` or
/// `{"status":"refused","reason":".."}`. Nothing is downloaded here.
#[tauri::command]
pub async fn magnet_open(uri: String) -> Result<crate::p2p::magnet::Opened, String> {
    blocking(move || {
        let dir = settings::app_dir();
        let flags = flags::current(&dir);
        let mut i = inbox().lock().map_err(|_| "magnet lock poisoned")?;
        Ok(crate::p2p::magnet::open(&uri, &flags, &crate::p2p::magnet::known(&dir), &mut i))
    })
    .await
}

/// The shared links this session received (newest last). Empty when the flag is off.
#[tauri::command]
pub fn magnet_pending() -> Result<Vec<crate::p2p::magnet::Pending>, String> {
    if !flags::current(&settings::app_dir()).magnet_links {
        return Ok(vec![]);
    }
    Ok(inbox().lock().map_err(|_| "magnet lock poisoned")?.list())
}

/// Forget one shared link (by info-hash) or all of them.
#[tauri::command]
pub fn magnet_dismiss(info_hash: Option<String>) -> Result<(), String> {
    inbox().lock().map_err(|_| "magnet lock poisoned")?.dismiss(info_hash.as_deref());
    Ok(())
}

/// Download an accepted shared package through the one download path (refusal list + the catalog's sha256), into
/// `<app data>/downloads/magnet/`. Only an info-hash that `magnet_open` accepted and the catalog still lists.
#[tauri::command]
pub async fn magnet_fetch(info_hash: String) -> Result<(String, crate::p2p::transfer::Outcome), String> {
    blocking(move || {
        let dir = settings::app_dir();
        let flags = flags::current(&dir);
        if !flags.magnet_links {
            return Err(crate::p2p::magnet::OFF.into());
        }
        if inbox().lock().map_err(|_| "magnet lock poisoned")?.accepted(&info_hash).is_none() {
            return Err(crate::p2p::magnet::UNKNOWN.into());
        }
        let k = crate::p2p::magnet::known(&dir).into_iter().find(|k| k.info_hash == info_hash).ok_or(crate::p2p::magnet::UNKNOWN)?;
        let (path, out) = crate::p2p::magnet::fetch(&dir, &k, &flags, &NoSwarm)?;
        Ok((path.display().to_string(), out))
    })
    .await
}
