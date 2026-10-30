//! The Host pack: the host kit as a download inside Leyline, so the base launcher stays small and only hosts
//! get the realm tooling (and need Docker).
//!
//! * Where it is listed: the Workshop catalog (`/wrath/mods/all.json`) as a project of category `tools` and
//!   kind `hostpack`; if the catalog does not have it yet, the release's own `hostpack.json`
//!   (`FALLBACK_URL`). Both give a version, a download address, its sha256 and size, and optionally a torrent.
//! * What it holds: our code only (scripts, compose file, the agent, the realm Lua and presets). Built by
//!   `hosting/pack/make-hostpack.py`, which refuses game data; Leyline checks it again on the way in.
//! * Where it goes: `<app data>/hostpack/kit`, with `installed.json` beside it. An update replaces the kit's
//!   files and keeps `state/` (the realm's key, invite and logins), `.env` and `cache/`.

use crate::mods;
use crate::net;
use crate::p2p::flags::Flags;
use crate::p2p::transfer::{self, Kind, Request, Swarm};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};

pub const FALLBACK_URL: &str = "https://github.com/orionopenwow/Leyline/releases/download/host-pack/hostpack.json";
/// Where a pack may be downloaded from (prefixes).
pub const ORIGINS: &[&str] = &["https://play.openvanilla.app/", "https://github.com/orionopenwow/Leyline/releases/download/"];
pub const MAX_PACK: u64 = 64 * 1024 * 1024;
const MAX_FILES: usize = 5000;
/// Kept across updates: one host's own realm.
const KEEP: &[&str] = &["state", ".env", "cache"];

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Descriptor {
    pub name: String,
    pub version: String,
    pub download: String,
    pub sha256: String,
    pub size: Option<u64>,
    /// A `.torrent` for the same zip (used only when `torrent_downloads` is on).
    pub torrent: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Installed {
    pub version: String,
    pub sha256: String,
    pub installed_at: u64,
    pub via: String,
}

fn origin_ok(u: &str) -> bool {
    let local_test = cfg!(test) && u.starts_with("http://127.0.0.1:");
    (net::plain_https(u) || local_test) && u.len() <= 400 && (ORIGINS.iter().any(|o| u.starts_with(o)) || local_test)
}

/// A descriptor made safe, or None.
pub fn clean(d: Descriptor) -> Option<Descriptor> {
    let sha = d.sha256.to_ascii_lowercase();
    let ok = mods::version_tuple(&d.version).is_some()
        && d.version.len() <= 40
        && origin_ok(&d.download)
        && sha.len() == 64
        && sha.chars().all(|c| c.is_ascii_hexdigit());
    ok.then(|| Descriptor {
        name: Some(d.name.trim().chars().take(64).collect::<String>()).filter(|n| !n.is_empty()).unwrap_or_else(|| "Host pack".into()),
        sha256: sha,
        size: d.size.filter(|s| *s <= MAX_PACK),
        torrent: d.torrent.filter(|t| origin_ok(t)),
        ..d
    })
}

/// The Host pack entry in an all.json document: category `tools`, kind `hostpack`, packaged.
pub fn from_catalog(v: &Value) -> Option<Descriptor> {
    let p = v.get("projects")?.as_array()?.iter().find(|p| {
        p.get("category").and_then(Value::as_str) == Some("tools")
            && p.get("kind").and_then(Value::as_str) == Some("hostpack")
            && p.get("source").and_then(Value::as_str) == Some("packaged")
    })?;
    let s = |k: &str| p.get(k).and_then(Value::as_str).unwrap_or("").to_string();
    clean(Descriptor {
        name: s("name"),
        version: s("version"),
        download: s("download"),
        sha256: s("sha256"),
        size: p.get("size").and_then(Value::as_u64),
        torrent: p.get("torrent").and_then(Value::as_str).map(String::from),
    })
}

/// The release's own `hostpack.json` (`{"format":1, name, version, download, sha256, size, torrent}`).
pub fn from_release(v: &Value) -> Option<Descriptor> {
    (v.get("format").and_then(Value::as_u64) == Some(1)).then_some(())?;
    clean(serde_json::from_value(v.clone()).ok()?)
}

/// What the Host pack is now: the catalog (cached by the Discover page) first, then the release file.
pub fn available(app_dir: &Path, fallback_url: &str) -> Result<Descriptor, String> {
    if let Some(d) = net::read_cache(&crate::catalog::cache_path(app_dir)).and_then(|(v, _)| from_catalog(&v)) {
        return Ok(d);
    }
    let v = net::get_json(fallback_url, net::TIMEOUT).map_err(|e| format!("Could not find the Host pack: {e}"))?;
    from_release(&v).ok_or_else(|| "The Host pack listing does not look right.".into())
}

pub fn root(app_dir: &Path) -> PathBuf {
    app_dir.join("hostpack")
}
pub fn kit_dir(app_dir: &Path) -> PathBuf {
    root(app_dir).join("kit")
}

pub fn installed(app_dir: &Path) -> Option<Installed> {
    let i: Installed = serde_json::from_slice(&fs::read(root(app_dir).join("installed.json")).ok()?).ok()?;
    kit_dir(app_dir).is_dir().then_some(i)
}

#[derive(Debug, Clone, Serialize)]
pub struct PackInfo {
    pub installed: Option<Installed>,
    pub available: Option<Descriptor>,
    /// A newer version is listed.
    pub update: bool,
    pub kit_dir: String,
    pub error: Option<String>,
}

pub fn info(app_dir: &Path, fallback_url: &str) -> PackInfo {
    let inst = installed(app_dir);
    let (avail, error) = match available(app_dir, fallback_url) {
        Ok(d) => (Some(d), None),
        Err(e) => (None, Some(e)),
    };
    let update = match (&inst, &avail) {
        (Some(i), Some(a)) => mods::newer(&a.version, &i.version) || (a.version == i.version && a.sha256 != i.sha256),
        _ => false,
    };
    PackInfo { installed: inst, available: avail, update, kit_dir: kit_dir(app_dir).display().to_string(), error }
}

/// The zip's entries without their one shared top folder (`WrathUnleashed host/...`), made safe.
fn entries(zip_path: &Path) -> Result<Vec<(usize, String)>, String> {
    let f = fs::File::open(zip_path).map_err(|e| e.to_string())?;
    let mut z = zip::ZipArchive::new(f).map_err(|e| format!("The Host pack is not a readable zip: {e}"))?;
    if z.len() > MAX_FILES {
        return Err("The Host pack has too many files.".into());
    }
    let mut names = Vec::new();
    for i in 0..z.len() {
        let e = z.by_index(i).map_err(|e| e.to_string())?;
        if let Some(rel) = mods::safe_rel(e.name())? {
            names.push((i, rel));
        }
    }
    let top = names.first().and_then(|(_, n)| n.split_once('/').map(|(t, _)| t.to_string()));
    let strip = top.filter(|t| names.iter().all(|(_, n)| n.starts_with(&format!("{t}/"))));
    Ok(names
        .into_iter()
        .map(|(i, n)| (i, strip.as_ref().map(|t| n[t.len() + 1..].to_string()).unwrap_or(n)))
        .filter(|(_, n)| !KEEP.iter().any(|k| n == k || n.starts_with(&format!("{k}/"))))
        .collect())
}

fn extract(zip_path: &Path, dest: &Path) -> Result<usize, String> {
    let list = entries(zip_path)?;
    let f = fs::File::open(zip_path).map_err(|e| e.to_string())?;
    let mut z = zip::ZipArchive::new(f).map_err(|e| e.to_string())?;
    let mut total = 0u64;
    for (i, rel) in &list {
        let mut e = z.by_index(*i).map_err(|e| e.to_string())?;
        let out = dest.join(rel);
        if let Some(d) = out.parent() {
            fs::create_dir_all(d).map_err(|e| e.to_string())?;
        }
        let mut data = Vec::new();
        (&mut e).take(MAX_PACK + 1).read_to_end(&mut data).map_err(|e| e.to_string())?;
        total += data.len() as u64;
        if total > 4 * MAX_PACK {
            return Err("The Host pack unpacks to too much.".into());
        }
        fs::write(&out, &data).map_err(|e| e.to_string())?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let exe = data.starts_with(b"#!") || e.unix_mode().is_some_and(|m| m & 0o111 != 0);
            fs::set_permissions(&out, fs::Permissions::from_mode(if exe { 0o755 } else { 0o644 })).map_err(|e| e.to_string())?;
        }
    }
    Ok(list.len())
}

/// Download (by the allowed route), verify and install `d`. Returns what is installed now.
pub fn install(app_dir: &Path, d: &Descriptor, flags: &Flags, swarm: &dyn Swarm) -> Result<Installed, String> {
    let d = clean(d.clone()).ok_or("The Host pack listing does not look right.")?;
    let root = root(app_dir);
    let dl = root.join("downloads");
    fs::create_dir_all(&dl).map_err(|e| e.to_string())?;
    let torrent = match (&d.torrent, flags.torrent_downloads) {
        (Some(t), true) => {
            let p = dl.join("hostpack.torrent");
            net::download(t, &p, crate::p2p::torrent::MAX_TORRENT_FILE as u64, net::TIMEOUT, net::TIMEOUT).ok().and_then(|_| fs::read(&p).ok())
        }
        _ => None,
    };
    let name = format!("leyline-host-pack-{}.zip", d.version.replace(|c: char| !c.is_ascii_alphanumeric() && c != '.', "-"));
    let zip_path = dl.join(&name);
    let req = Request { kind: Kind::HostPack, name: name.clone(), sha256: d.sha256.clone(), https_url: d.download.clone(), torrent, max_bytes: MAX_PACK };
    let got = transfer::fetch(&req, &zip_path, flags, swarm)?;
    let result = place(&root, &zip_path);
    let _ = fs::remove_file(&zip_path);
    result?;
    let inst = Installed {
        version: d.version.clone(),
        sha256: got.sha256,
        installed_at: std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|t| t.as_secs()).unwrap_or(0),
        via: serde_json::to_value(&got.via).ok().and_then(|v| v.as_str().map(String::from)).unwrap_or_default(),
    };
    let b = serde_json::to_vec_pretty(&inst).map_err(|e| e.to_string())?;
    crate::settings::write_atomic(&root.join("installed.json"), &b).map_err(|e| e.to_string())?;
    Ok(inst)
}

/// Unpack into `kit.new`, carry over the host's own files, then swap it in.
fn place(root: &Path, zip_path: &Path) -> Result<(), String> {
    let kit = root.join("kit");
    let new = root.join("kit.new");
    let old = root.join("kit.old");
    let _ = fs::remove_dir_all(&new);
    let _ = fs::remove_dir_all(&old);
    fs::create_dir_all(&new).map_err(|e| e.to_string())?;
    let r = (|| {
        extract(zip_path, &new)?;
        if !new.join(super::WINDOWS_SCRIPT).is_file() || !new.join(super::LEYLINE_SCRIPT).is_file() || !new.join("realm-files").is_dir() {
            return Err("The Host pack is missing its host scripts.".into());
        }
        for k in KEEP {
            let from = kit.join(k);
            if from.exists() {
                fs::rename(&from, new.join(k)).map_err(|e| format!("Could not keep your realm's {k}: {e}"))?;
            }
        }
        Ok(())
    })();
    if let Err(e) = r {
        // Put back anything already moved, then drop the half-made folder.
        for k in KEEP {
            if new.join(k).exists() && !kit.join(k).exists() && kit.is_dir() {
                let _ = fs::rename(new.join(k), kit.join(k));
            }
        }
        let _ = fs::remove_dir_all(&new);
        return Err(e);
    }
    if kit.exists() {
        fs::rename(&kit, &old).map_err(|e| format!("Could not replace the old Host pack (is a window open in it?): {e}"))?;
    }
    if let Err(e) = fs::rename(&new, &kit) {
        let _ = fs::rename(&old, &kit);
        return Err(e.to_string());
    }
    let _ = fs::remove_dir_all(&old);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mods::tests::zip_of;
    use crate::net::testserver::*;
    use crate::p2p::transfer::NoSwarm;
    use sha2::{Digest, Sha256};

    fn pack_zip(extra: &[(&str, &[u8])]) -> Vec<u8> {
        let mut e: Vec<(&str, &[u8])> = vec![
            ("WrathUnleashed host/Host a Wrath realm.bat", b"@echo off\r\n"),
            ("WrathUnleashed host/leyline", b"#!/usr/bin/env bash\n"),
            ("WrathUnleashed host/host-wrath-realm.sh", b"#!/usr/bin/env bash\n"),
            ("WrathUnleashed host/realm-files/profiles/main.env", b"WU_X=1\n"),
            ("WrathUnleashed host/state/realm.key", b"never shipped, never unpacked"),
        ];
        e.extend_from_slice(extra);
        zip_of(&e)
    }

    fn desc(base: &str, data: &[u8], v: &str) -> Descriptor {
        Descriptor { name: "Host pack".into(), version: v.into(), download: format!("{base}/hp.zip"), sha256: net::hex(&Sha256::digest(data)), size: Some(data.len() as u64), torrent: None }
    }

    #[test]
    fn descriptors_from_the_catalog_or_the_release() {
        let cat = serde_json::json!({"projects":[
            {"id":"mod:pings","category":"addons","kind":"both","source":"packaged"},
            {"id":"mod:host-pack","name":"Host pack","category":"tools","kind":"hostpack","source":"packaged","version":"2026.1029.1700",
             "download":"https://github.com/orionopenwow/Leyline/releases/download/host-pack/leyline-host-pack-2026.1029.1700.zip",
             "sha256":"AA".repeat(32),"size":12345,"torrent":"https://evil.example.com/x.torrent"}]});
        let d = from_catalog(&cat).unwrap();
        assert_eq!((d.version.as_str(), d.sha256.len(), d.torrent.clone()), ("2026.1029.1700", 64, None));
        let mut bad = cat.clone();
        bad["projects"][1]["download"] = Value::String("https://evil.example.com/hp.zip".into());
        assert!(from_catalog(&bad).is_none(), "downloads only from our site or our release");
        let rel = serde_json::json!({"format":1,"version":"2026.1029.1700","download":"https://play.openvanilla.app/wrath/leyline/hostpack.zip","sha256":"ab".repeat(32)});
        assert!(from_release(&rel).is_some());
        assert!(from_release(&serde_json::json!({"format":2})).is_none());
    }

    #[test]
    fn install_update_keeps_the_realm() {
        let d = tempfile::tempdir().unwrap();
        let v1 = pack_zip(&[("WrathUnleashed host/old-only.txt", b"x")]);
        let base = serve_routes(vec![("/hp.zip", "200 OK", v1.clone())]);
        let i = install(d.path(), &desc(&base, &v1, "2026.1029.1"), &Flags::default(), &NoSwarm).unwrap();
        assert_eq!((i.version.as_str(), i.via.as_str()), ("2026.1029.1", "https"));
        let kit = kit_dir(d.path());
        assert!(kit.join("leyline").is_file() && kit.join("realm-files/profiles/main.env").is_file());
        assert!(!kit.join("state/realm.key").exists(), "a pack never brings a state folder");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(fs::metadata(kit.join("leyline")).unwrap().permissions().mode() & 0o111, 0o111);
        }
        // The host ran it: their realm's own files.
        fs::create_dir_all(kit.join("state")).unwrap();
        fs::write(kit.join("state/realm.key"), b"MY KEY").unwrap();
        fs::write(kit.join(".env"), b"WU_DB=secret").unwrap();
        assert_eq!(installed(d.path()).unwrap().version, "2026.1029.1");

        let v2 = pack_zip(&[("WrathUnleashed host/new.txt", b"y")]);
        let base2 = serve_routes(vec![("/hp.zip", "200 OK", v2.clone())]);
        let p = info(d.path(), &dead_url());
        assert!(p.installed.is_some() && p.available.is_none() && p.error.is_some());
        install(d.path(), &desc(&base2, &v2, "2026.1030.1"), &Flags::default(), &NoSwarm).unwrap();
        assert_eq!(fs::read(kit.join("state/realm.key")).unwrap(), b"MY KEY");
        assert_eq!(fs::read(kit.join(".env")).unwrap(), b"WU_DB=secret");
        assert!(kit.join("new.txt").is_file() && !kit.join("old-only.txt").exists());

        // A bad pack (wrong hash, or game data) leaves the installed kit as it was.
        let evil = pack_zip(&[("WrathUnleashed host/realm-files/x.txt", b"MPQ\x1a")]);
        let base3 = serve_routes(vec![("/hp.zip", "200 OK", evil.clone())]);
        assert!(install(d.path(), &desc(&base3, &evil, "2026.1031.1"), &Flags::default(), &NoSwarm).unwrap_err().starts_with("Refused"));
        let mut wrong = desc(&base2, &v2, "2026.1031.1");
        wrong.sha256 = "00".repeat(32);
        assert!(install(d.path(), &wrong, &Flags::default(), &NoSwarm).is_err());
        let notkit = zip_of(&[("x/readme.txt", b"hi")]);
        let base4 = serve_routes(vec![("/hp.zip", "200 OK", notkit.clone())]);
        assert!(install(d.path(), &desc(&base4, &notkit, "2026.1031.2"), &Flags::default(), &NoSwarm).unwrap_err().contains("missing"));
        assert_eq!(fs::read(kit.join("state/realm.key")).unwrap(), b"MY KEY");
        assert_eq!(installed(d.path()).unwrap().version, "2026.1030.1");
    }

    #[test]
    fn update_is_offered_for_a_newer_listing() {
        let d = tempfile::tempdir().unwrap();
        let v1 = pack_zip(&[]);
        let base = serve_routes(vec![("/hp.zip", "200 OK", v1.clone())]);
        install(d.path(), &desc(&base, &v1, "2026.1029.1"), &Flags::default(), &NoSwarm).unwrap();
        let rel = serde_json::json!({"format":1,"version":"2026.1101.1","download":"https://play.openvanilla.app/wrath/leyline/hostpack.zip","sha256":"ab".repeat(32)});
        let srv = serve_routes(vec![("/hostpack.json", "200 OK", rel.to_string().into_bytes())]);
        let p = info(d.path(), &format!("{srv}/hostpack.json"));
        assert!(p.update && p.available.unwrap().version == "2026.1101.1");
    }
}
