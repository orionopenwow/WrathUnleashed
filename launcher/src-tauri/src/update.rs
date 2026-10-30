//! Leyline's own updates: the GitHub releases of the PUBLIC repo orionopenwow/Leyline, tags `launcher-v*`.
//!
//! Two parts:
//! * The check (plain Rust, tested here): the newest release of the player's channel (stable: releases only;
//!   beta: pre-releases too), cached for offline use, and that release's updater manifest address
//!   (`.../releases/download/launcher-v<version>/latest.json`, made by CI).
//! * The install (the desktop app, `app.rs`): Tauri's updater plugin fetches that one manifest, checks the
//!   download's signature against the public key in tauri.conf.json, downloads it in the background and installs
//!   it only when the player presses "Restart" in the title bar, never while a game Leyline started is running.
//!   Until the owner has run "setup\Turn on launcher updates.bat" (no public key yet), or on a .deb install, Leyline
//!   only links to the release page.
//!
//! `parse_manifest` re-checks the manifest Leyline is about to hand the plugin: a semver version, a signature
//! per platform, and download addresses only under this repo's release downloads.

use crate::net;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::path::Path;

pub const REPO: &str = "orionopenwow/Leyline";
pub const URL: &str = "https://api.github.com/repos/orionopenwow/Leyline/releases?per_page=30";
pub const RELEASES_PAGE: &str = "https://github.com/orionopenwow/Leyline/releases";
pub const DOWNLOAD_PREFIX: &str = "https://github.com/orionopenwow/Leyline/releases/download/";
pub const TAG_PREFIX: &str = "launcher-v";
pub const MANIFEST_NAME: &str = "latest.json";
/// How often the app looks for a new version while it runs (and once at start).
pub const CHECK_EVERY_SECS: u64 = 6 * 60 * 60;

/// Which releases the player wants.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Channel {
    /// Releases only.
    #[default]
    Stable,
    /// Pre-releases too.
    Beta,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct UpdateInfo {
    pub current: String,
    pub channel: Channel,
    /// The newest launcher release of the channel, when one was found.
    pub latest: Option<String>,
    pub newer: bool,
    /// Its release page (only ever a page under RELEASES_PAGE).
    pub url: Option<String>,
    /// Its updater manifest (only ever under DOWNLOAD_PREFIX), when the release lists one.
    pub manifest_url: Option<String>,
    pub prerelease: bool,
    pub from_cache: bool,
    pub error: Option<String>,
}

/// One release of the channel: (version, page, manifest address if attached, prerelease).
#[derive(Debug, Clone, PartialEq)]
pub struct Release {
    pub version: String,
    pub page: String,
    pub manifest_url: Option<String>,
    pub prerelease: bool,
}

/// A semver-ish version: (major, minor, patch) and the pre-release part (`beta.1`), empty for a release.
pub fn parse_version(v: &str) -> Option<((u64, u64, u64), String)> {
    let v = v.trim().trim_start_matches(['v', 'V']);
    let (core, pre) = match v.split_once('-') {
        Some((c, p)) => (c, p.split('+').next().unwrap_or("").to_string()),
        None => (v.split('+').next().unwrap_or(v), String::new()),
    };
    let mut it = core.split('.');
    let n = |x: Option<&str>| -> Option<u64> { x.map_or(Some(0), |s| s.parse().ok()) };
    let a = it.next()?.parse().ok()?;
    let t = (a, n(it.next())?, n(it.next())?);
    if it.next().is_some() || pre.len() > 40 || !pre.chars().all(|c| c.is_ascii_alphanumeric() || c == '.') {
        return None;
    }
    Some((t, pre))
}

/// Semver order: numbers first, then a release above its pre-releases, pre-release parts compared numerically
/// when both are numbers.
pub fn cmp_versions(a: &str, b: &str) -> Option<Ordering> {
    let (ta, pa) = parse_version(a)?;
    let (tb, pb) = parse_version(b)?;
    Some(ta.cmp(&tb).then_with(|| match (pa.is_empty(), pb.is_empty()) {
        (true, true) => Ordering::Equal,
        (true, false) => Ordering::Greater,
        (false, true) => Ordering::Less,
        (false, false) => {
            let (xa, xb): (Vec<&str>, Vec<&str>) = (pa.split('.').collect(), pb.split('.').collect());
            for (x, y) in xa.iter().zip(&xb) {
                let o = match (x.parse::<u64>(), y.parse::<u64>()) {
                    (Ok(i), Ok(j)) => i.cmp(&j),
                    (Ok(_), Err(_)) => Ordering::Less,
                    (Err(_), Ok(_)) => Ordering::Greater,
                    _ => x.cmp(y),
                };
                if o != Ordering::Equal {
                    return o;
                }
            }
            xa.len().cmp(&xb.len())
        }
    }))
}

/// `latest` is newer than `have`.
pub fn is_newer(latest: &str, have: &str) -> bool {
    cmp_versions(latest, have) == Some(Ordering::Greater)
}

/// The newest `launcher-v*` release of the channel in a GitHub releases list.
pub fn latest(v: &Value, channel: Channel) -> Option<Release> {
    v.as_array()?
        .iter()
        .filter(|r| !r.get("draft").and_then(Value::as_bool).unwrap_or(false))
        .filter_map(|r| {
            let tag = r.get("tag_name")?.as_str()?;
            let ver = tag.strip_prefix(TAG_PREFIX)?;
            parse_version(ver)?;
            let prerelease = r.get("prerelease").and_then(Value::as_bool).unwrap_or(false);
            if prerelease && channel == Channel::Stable {
                return None;
            }
            let page = r.get("html_url").and_then(Value::as_str).filter(|u| u.starts_with(&format!("{RELEASES_PAGE}/")) && net::plain_https(u))?;
            let want = format!("{DOWNLOAD_PREFIX}{tag}/{MANIFEST_NAME}");
            let manifest_url = r
                .get("assets")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(|a| a.get("browser_download_url").and_then(Value::as_str))
                .find(|u| *u == want)
                .map(String::from);
            Some(Release { version: ver.chars().take(48).collect(), page: page.to_string(), manifest_url, prerelease })
        })
        .max_by(|a, b| cmp_versions(&a.version, &b.version).unwrap_or(Ordering::Equal))
}

pub fn check(app_dir: &Path, current: &str, channel: Channel) -> UpdateInfo {
    check_from(URL, app_dir, current, channel)
}

pub fn check_from(url: &str, app_dir: &Path, current: &str, channel: Channel) -> UpdateInfo {
    let cache = app_dir.join("cache").join("releases.json");
    let mut out = UpdateInfo { current: current.into(), channel, ..Default::default() };
    match net::fetch_json(url, &cache, net::TIMEOUT, |v| v.as_array().map(|_| ()).ok_or_else(|| "not a release list".into())) {
        Ok(f) => {
            out.from_cache = f.from_cache;
            out.error = f.error;
            if let Some(r) = latest(&f.value, channel) {
                out.newer = is_newer(&r.version, current);
                out.latest = Some(r.version);
                out.url = Some(r.page);
                out.manifest_url = r.manifest_url;
                out.prerelease = r.prerelease;
            }
        }
        Err(e) => out.error = Some(e),
    }
    out
}

// ------------------------------------------------------------------------------------------------ the manifest

/// One platform's download in latest.json.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PlatformAsset {
    pub signature: String,
    pub url: String,
}

/// The updater manifest (Tauri's static JSON format) as CI writes it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Manifest {
    pub version: String,
    #[serde(default)]
    pub notes: String,
    #[serde(default)]
    pub pub_date: String,
    pub platforms: BTreeMap<String, PlatformAsset>,
}

/// The platform keys Leyline ships: Windows, macOS (one universal app, listed for both CPUs) and Linux (AppImage).
pub const PLATFORM_KEYS: &[&str] = &["windows-x86_64", "darwin-x86_64", "darwin-aarch64", "linux-x86_64"];

/// This build's key in `platforms` (`<os>-<arch>`, as the updater plugin looks it up).
pub fn platform_key(os: &str, arch: &str) -> String {
    let os = match os {
        "macos" => "darwin",
        o => o,
    };
    format!("{os}-{arch}")
}

pub fn this_platform() -> String {
    platform_key(std::env::consts::OS, std::env::consts::ARCH)
}

/// A minisign signature as the updater writes it: base64 text (of a two-line minisign file).
fn signature_ok(s: &str) -> bool {
    (80..=2000).contains(&s.len()) && s.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '+' | '/' | '='))
}

/// The updater's public key as tauri.conf.json carries it (base64 of a minisign public key file). The repo
/// ships a placeholder until the owner runs "setup\Turn on launcher updates.bat".
pub fn pubkey_ok(s: &str) -> bool {
    signature_ok(s.trim()) && s.trim().len() < 400
}

/// Parse and check latest.json. Platforms with a download outside this repo's releases, or without a
/// signature, are refused (the whole manifest, so a half-bad one is never used).
pub fn parse_manifest(text: &str) -> Result<Manifest, String> {
    let m: Manifest = serde_json::from_str(text).map_err(|e| format!("not an update manifest: {e}"))?;
    if parse_version(&m.version).is_none() {
        return Err(format!("the manifest's version {:?} is not a version", m.version));
    }
    if m.platforms.is_empty() {
        return Err("the manifest lists no downloads".into());
    }
    for (k, a) in &m.platforms {
        if !k.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, '-' | '_')) {
            return Err(format!("odd platform name {k:?}"));
        }
        let tag = format!("{DOWNLOAD_PREFIX}{TAG_PREFIX}{}/", m.version.trim_start_matches('v'));
        if !a.url.starts_with(&tag) || !net::plain_https(&a.url) || a.url.contains("..") {
            return Err(format!("{k}: the download is not in this release ({})", a.url));
        }
        if !signature_ok(&a.signature) {
            return Err(format!("{k}: no usable signature"));
        }
    }
    Ok(m)
}

/// The manifest's download for this platform, if it has one.
pub fn asset_for<'a>(m: &'a Manifest, key: &str) -> Option<&'a PlatformAsset> {
    m.platforms.get(key)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::net::testserver::*;

    const LIST: &str = r#"[
      {"tag_name":"launcher-v0.4.0","draft":true,"html_url":"https://github.com/orionopenwow/Leyline/releases/tag/launcher-v0.4.0"},
      {"tag_name":"launcher-v0.3.1-beta.2","draft":false,"prerelease":true,"html_url":"https://github.com/orionopenwow/Leyline/releases/tag/launcher-v0.3.1-beta.2",
       "assets":[{"browser_download_url":"https://github.com/orionopenwow/Leyline/releases/download/launcher-v0.3.1-beta.2/latest.json"}]},
      {"tag_name":"launcher-v0.3.0","draft":false,"prerelease":false,"html_url":"https://github.com/orionopenwow/Leyline/releases/tag/launcher-v0.3.0",
       "assets":[{"browser_download_url":"https://github.com/orionopenwow/Leyline/releases/download/launcher-v0.3.0/Leyline_0.3.0_x64-setup.exe"},
                 {"browser_download_url":"https://github.com/orionopenwow/Leyline/releases/download/launcher-v0.3.0/latest.json"}]},
      {"tag_name":"v9.0.0","draft":false,"html_url":"https://github.com/orionopenwow/Leyline/releases/tag/v9.0.0"},
      {"tag_name":"launcher-v0.2.0","draft":false,"prerelease":true,"html_url":"https://github.com/orionopenwow/Leyline/releases/tag/launcher-v0.2.0"},
      {"tag_name":"launcher-v5.0.0","draft":false,"html_url":"https://evil.example.com/x"}
    ]"#;

    #[test]
    fn finds_the_newest_release_of_each_channel() {
        let v: Value = serde_json::from_str(LIST).unwrap();
        let s = latest(&v, Channel::Stable).unwrap();
        assert_eq!(s.version, "0.3.0", "drafts, pre-releases, other tags and other sites are left out");
        assert!(s.page.ends_with("/tag/launcher-v0.3.0") && !s.prerelease);
        assert_eq!(s.manifest_url.as_deref(), Some("https://github.com/orionopenwow/Leyline/releases/download/launcher-v0.3.0/latest.json"));
        let b = latest(&v, Channel::Beta).unwrap();
        assert_eq!(b.version, "0.3.1-beta.2");
        assert!(b.prerelease && b.manifest_url.unwrap().ends_with("/launcher-v0.3.1-beta.2/latest.json"));
    }

    #[test]
    fn versions_in_semver_order() {
        assert!(is_newer("0.3.0", "0.2.9"));
        assert!(is_newer("0.3.0", "0.3.0-beta.9"));
        assert!(is_newer("0.3.0-beta.10", "0.3.0-beta.9"));
        assert!(is_newer("0.3.0-rc.1", "0.3.0-beta.1"));
        assert!(!is_newer("0.3.0-beta.1", "0.3.0"));
        assert!(!is_newer("0.3.0", "0.3.0"));
        assert!(!is_newer("x", "0.1.0"));
        assert_eq!(parse_version("v1.2"), Some(((1, 2, 0), String::new())));
        assert_eq!(parse_version("1.2.3.4"), None);
        assert_eq!(parse_version("1.2.3-be ta"), None);
    }

    #[test]
    fn says_newer_or_not_per_channel_and_works_offline() {
        let d = tempfile::tempdir().unwrap();
        let base = serve_routes(vec![("/releases", "200 OK", LIST.as_bytes().to_vec())]);
        let u = check_from(&format!("{base}/releases"), d.path(), "0.2.0", Channel::Stable);
        assert!(u.newer && u.latest.as_deref() == Some("0.3.0") && !u.from_cache && u.manifest_url.is_some());
        assert!(!check_from(&format!("{base}/releases"), d.path(), "0.3.0", Channel::Stable).newer);
        let b = check_from(&format!("{base}/releases"), d.path(), "0.3.0", Channel::Beta);
        assert!(b.newer && b.prerelease && b.channel == Channel::Beta);
        let off = check_from(&dead_url(), d.path(), "0.2.0", Channel::Stable);
        assert!(off.newer && off.from_cache);
        let none = check_from(&dead_url(), tempfile::tempdir().unwrap().path(), "0.1.0", Channel::Stable);
        assert!(!none.newer && none.error.is_some());
    }

    fn sig() -> String {
        "dW50cnVzdGVkIGNvbW1lbnQ6IHNpZ25hdHVyZSBmcm9tIHRhdXJpIHNlY3JldCBrZXkKUlVSVEVTVA".repeat(3)
    }

    fn manifest(url_win: &str) -> String {
        let s = sig();
        format!(
            r#"{{"version":"0.3.0","notes":"Leyline 0.3.0","pub_date":"2026-10-30T12:00:00Z","platforms":{{
            "windows-x86_64":{{"signature":"{s}","url":"{url_win}"}},
            "darwin-x86_64":{{"signature":"{s}","url":"https://github.com/orionopenwow/Leyline/releases/download/launcher-v0.3.0/Leyline_universal.app.tar.gz"}},
            "darwin-aarch64":{{"signature":"{s}","url":"https://github.com/orionopenwow/Leyline/releases/download/launcher-v0.3.0/Leyline_universal.app.tar.gz"}},
            "linux-x86_64":{{"signature":"{s}","url":"https://github.com/orionopenwow/Leyline/releases/download/launcher-v0.3.0/Leyline_0.3.0_amd64.AppImage"}}}}}}"#
        )
    }

    #[test]
    fn parses_and_checks_the_updater_manifest() {
        let good = manifest("https://github.com/orionopenwow/Leyline/releases/download/launcher-v0.3.0/Leyline_0.3.0_x64-setup.exe");
        let m = parse_manifest(&good).unwrap();
        assert_eq!(m.version, "0.3.0");
        for k in PLATFORM_KEYS {
            assert!(asset_for(&m, k).is_some(), "{k}");
        }
        assert!(asset_for(&m, "linux-aarch64").is_none());
        // Downloads only from this release of this repo.
        for bad in [
            "https://evil.example.com/Leyline.exe",
            "https://github.com/someone/Leyline/releases/download/launcher-v0.3.0/x.exe",
            "https://github.com/orionopenwow/Leyline/releases/download/launcher-v0.2.0/old.exe",
            "http://github.com/orionopenwow/Leyline/releases/download/launcher-v0.3.0/x.exe",
            "https://github.com/orionopenwow/Leyline/releases/download/launcher-v0.3.0/../launcher-v0.1.0/x.exe",
        ] {
            assert!(parse_manifest(&manifest(bad)).unwrap_err().contains("not in this release"), "{bad}");
        }
        assert!(parse_manifest(&good.replace(&sig(), "short")).unwrap_err().contains("signature"));
        assert!(parse_manifest(&good.replace("\"0.3.0\"", "\"three\"")).is_err());
        assert!(parse_manifest(r#"{"version":"0.3.0","platforms":{}}"#).unwrap_err().contains("no downloads"));
        assert!(parse_manifest("<html>").is_err());
    }

    #[test]
    fn platform_keys_and_the_public_key() {
        assert_eq!(platform_key("windows", "x86_64"), "windows-x86_64");
        assert_eq!(platform_key("macos", "aarch64"), "darwin-aarch64");
        assert_eq!(platform_key("linux", "x86_64"), "linux-x86_64");
        assert!(PLATFORM_KEYS.contains(&this_platform().as_str()) || cfg!(not(target_arch = "x86_64")));
        let conf: Value = serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        let pk = conf["plugins"]["updater"]["pubkey"].as_str().unwrap();
        // The repo ships the placeholder until "setup\Turn on launcher updates.bat" writes the real key.
        assert!(pk.starts_with("TODO") || pubkey_ok(pk), "{pk}");
        assert!(!pubkey_ok("TODO(owner): run Turn on launcher updates.bat"));
        assert!(pubkey_ok(&"dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6".repeat(3)));
        assert_eq!(conf["plugins"]["updater"]["windows"]["installMode"], "passive");
        assert!(conf["bundle"]["createUpdaterArtifacts"].is_null() || conf["bundle"]["createUpdaterArtifacts"] == false,
            "CI turns updater artifacts on only when the signing key is there");
    }
}
