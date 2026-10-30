//! Feature flags for the P2P and torrent features. Everything ships OFF.
//!
//! Two layers:
//! * the site's file, `https://play.openvanilla.app/wrath/leyline/flags.json` (written by the admin console
//!   through `stream/leyline_net.py: write_flags`), checked by its sha256 and cached for offline use;
//! * this PC's own overrides (Settings > Advanced), in `<app data>/leyline-flags-local.json`.
//!
//! A local override wins over the site, both ways: a player can turn a feature off that the site turned on,
//! or try one early. A missing, broken or tampered site file counts as "all off". The format is in
//! `docs/P2P-AND-TORRENT.md`.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

pub const URL: &str = "https://play.openvanilla.app/wrath/leyline/flags.json";
pub const FORMAT: u64 = 1;
pub const LOCAL_FILE: &str = "leyline-flags-local.json";

/// Every flag, in display order, with its plain-words label. Unknown flags in the file are ignored.
pub const KNOWN: &[(&str, &str)] = &[
    ("p2p_hosting", "Direct connections to hosted realms (falls back to the relay)"),
    ("torrent_downloads", "Download packages over BitTorrent, with the website as fallback"),
    ("torrent_seeding", "Share downloaded packages back (uses your upload)"),
    ("webrtc_presence", "See friends online over a direct browser link"),
];

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Limits {
    /// Upload cap while seeding, KB/s. 0 = never upload.
    pub seed_upload_kbps: u32,
    /// Stop seeding a package after this much upload, percent of its size. 0 = never seed.
    pub seed_ratio_pct: u32,
    /// Most peers at once.
    pub max_peers: u32,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct Flags {
    pub p2p_hosting: bool,
    pub torrent_downloads: bool,
    pub torrent_seeding: bool,
    pub webrtc_presence: bool,
    pub limits: Limits,
    /// STUN servers for the NAT check (`host:port`), only used when `p2p_hosting` is on.
    pub stun: Vec<String>,
}

impl Flags {
    pub fn get(&self, name: &str) -> Option<bool> {
        Some(match name {
            "p2p_hosting" => self.p2p_hosting,
            "torrent_downloads" => self.torrent_downloads,
            "torrent_seeding" => self.torrent_seeding,
            "webrtc_presence" => self.webrtc_presence,
            _ => return None,
        })
    }
    fn set(&mut self, name: &str, on: bool) {
        match name {
            "p2p_hosting" => self.p2p_hosting = on,
            "torrent_downloads" => self.torrent_downloads = on,
            "torrent_seeding" => self.torrent_seeding = on,
            "webrtc_presence" => self.webrtc_presence = on,
            _ => {}
        }
    }
    /// Seeding needs downloads on, seeding on, and a non-zero upload cap and ratio.
    pub fn seeding_allowed(&self) -> bool {
        self.torrent_downloads && self.torrent_seeding && self.limits.seed_upload_kbps > 0 && self.limits.seed_ratio_pct > 0
    }
}

/// JSON with sorted keys and no spaces: what the sha256 is taken over. Matches Python's
/// `json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` for the values this file holds.
pub fn canonical(v: &Value) -> String {
    match v {
        Value::Object(m) => {
            let sorted: BTreeMap<&String, &Value> = m.iter().collect();
            let parts: Vec<String> = sorted.iter().map(|(k, x)| format!("{}:{}", Value::String((*k).clone()), canonical(x))).collect();
            format!("{{{}}}", parts.join(","))
        }
        Value::Array(a) => format!("[{}]", a.iter().map(canonical).collect::<Vec<_>>().join(",")),
        other => other.to_string(),
    }
}

/// The hash a flags document must carry: sha256 of the canonical JSON of everything but `sha256`.
pub fn doc_hash(doc: &Value) -> String {
    use sha2::{Digest, Sha256};
    let mut body = doc.clone();
    if let Some(m) = body.as_object_mut() {
        m.remove("sha256");
    }
    crate::net::hex(&Sha256::digest(canonical(&body).as_bytes()))
}

/// Check a site document: format 1 and a matching sha256.
pub fn check(doc: &Value) -> Result<(), String> {
    if doc.get("format").and_then(Value::as_u64) != Some(FORMAT) {
        return Err("unknown flags format".into());
    }
    let want = doc.get("sha256").and_then(Value::as_str).ok_or("the flags file has no sha256")?;
    if want != doc_hash(doc) {
        return Err("the flags file's sha256 does not match".into());
    }
    Ok(())
}

fn stun_ok(s: &str) -> bool {
    match s.rsplit_once(':') {
        Some((h, p)) => {
            p.parse::<u16>().is_ok_and(|p| p > 0)
                && !h.is_empty()
                && h.len() <= 253
                && h.chars().all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-')
        }
        None => false,
    }
}

/// The flags a (checked) site document sets. Anything malformed is off.
pub fn from_doc(doc: &Value) -> Flags {
    let mut f = Flags::default();
    if let Some(m) = doc.get("flags").and_then(Value::as_object) {
        for (k, _) in KNOWN {
            f.set(k, m.get(*k).and_then(Value::as_bool).unwrap_or(false));
        }
    }
    if let Some(l) = doc.get("limits") {
        let n = |k: &str, max: u64| l.get(k).and_then(Value::as_u64).map(|v| v.min(max) as u32).unwrap_or(0);
        f.limits = Limits { seed_upload_kbps: n("seed_upload_kbps", 100_000), seed_ratio_pct: n("seed_ratio_pct", 1000), max_peers: n("max_peers", 200) };
    }
    f.stun = doc
        .get("stun")
        .and_then(Value::as_array)
        .map(|a| a.iter().filter_map(Value::as_str).filter(|s| stun_ok(s)).take(4).map(String::from).collect())
        .unwrap_or_default();
    f
}

/// This PC's overrides: flag name -> on/off, plus optional limits.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Local {
    pub overrides: BTreeMap<String, bool>,
    pub limits: Option<Limits>,
}

pub fn local_path(app_dir: &Path) -> PathBuf {
    app_dir.join(LOCAL_FILE)
}

pub fn load_local(app_dir: &Path) -> Local {
    std::fs::read(local_path(app_dir)).ok().and_then(|b| serde_json::from_slice::<Local>(&b).ok()).map(|mut l| {
        l.overrides.retain(|k, _| KNOWN.iter().any(|(n, _)| n == k));
        l
    }).unwrap_or_default()
}

/// Set (Some) or clear (None: follow the site) one override.
pub fn set_local(app_dir: &Path, name: &str, value: Option<bool>) -> Result<Local, String> {
    if !KNOWN.iter().any(|(n, _)| *n == name) {
        return Err("Unknown setting.".into());
    }
    let mut l = load_local(app_dir);
    match value {
        Some(v) => l.overrides.insert(name.to_string(), v),
        None => l.overrides.remove(name),
    };
    save_local(app_dir, &l)?;
    Ok(l)
}

pub fn set_local_limits(app_dir: &Path, limits: Option<Limits>) -> Result<Local, String> {
    let mut l = load_local(app_dir);
    l.limits = limits.map(|x| Limits { seed_upload_kbps: x.seed_upload_kbps.min(100_000), seed_ratio_pct: x.seed_ratio_pct.min(1000), max_peers: x.max_peers.min(200) });
    save_local(app_dir, &l)?;
    Ok(l)
}

fn save_local(app_dir: &Path, l: &Local) -> Result<(), String> {
    let b = serde_json::to_vec_pretty(l).map_err(|e| e.to_string())?;
    crate::settings::write_atomic(&local_path(app_dir), &b).map_err(|e| format!("Could not save: {e}"))
}

/// Site flags with this PC's overrides on top.
pub fn effective(site: &Flags, local: &Local) -> Flags {
    let mut f = site.clone();
    for (k, v) in &local.overrides {
        f.set(k, *v);
    }
    if let Some(l) = &local.limits {
        f.limits = l.clone();
    }
    f
}

/// What the Settings page shows.
#[derive(Debug, Clone, Serialize)]
pub struct View {
    pub site: Flags,
    pub local: Local,
    pub effective: Flags,
    pub known: Vec<(String, String)>,
    pub from_cache: bool,
    pub error: Option<String>,
}

pub fn cache_path(app_dir: &Path) -> PathBuf {
    app_dir.join("cache").join("leyline-flags.json")
}

/// The site's flags (or the cached copy, or all off) with this PC's overrides.
pub fn load(app_dir: &Path, url: &str) -> View {
    let (site, from_cache, error) = match crate::net::fetch_json(url, &cache_path(app_dir), crate::net::TIMEOUT, check) {
        Ok(f) => (from_doc(&f.value), f.from_cache, f.error),
        Err(e) => (Flags::default(), false, Some(e)),
    };
    let local = load_local(app_dir);
    View { effective: effective(&site, &local), site, local, known: KNOWN.iter().map(|(a, b)| (a.to_string(), b.to_string())).collect(), from_cache, error }
}

/// The flags in force now, without the network (the cached site copy, if any, plus overrides).
pub fn current(app_dir: &Path) -> Flags {
    let site = crate::net::read_cache(&cache_path(app_dir)).filter(|(v, _)| check(v).is_ok()).map(|(v, _)| from_doc(&v)).unwrap_or_default();
    effective(&site, &load_local(app_dir))
}

#[cfg(test)]
pub mod tests {
    use super::*;
    use crate::net::testserver::*;

    /// A site document as `stream/leyline_net.py` writes it (its test checks the same bytes).
    pub fn doc(flags: &[(&str, bool)]) -> Value {
        let mut fl = serde_json::Map::new();
        for (k, _) in KNOWN {
            fl.insert(k.to_string(), Value::Bool(false));
        }
        for (k, v) in flags {
            fl.insert(k.to_string(), Value::Bool(*v));
        }
        let mut d = serde_json::json!({"format": 1, "updated_at": "2026-10-29T00:00:00Z", "flags": fl,
            "limits": {"seed_upload_kbps": 0, "seed_ratio_pct": 0, "max_peers": 0}, "stun": ["stun.cloudflare.com:3478"]});
        let h = doc_hash(&d);
        d["sha256"] = Value::String(h);
        d
    }

    #[test]
    fn defaults_are_all_off() {
        let f = Flags::default();
        assert!(KNOWN.iter().all(|(k, _)| f.get(k) == Some(false)));
        assert!(!f.seeding_allowed());
        let d = tempfile::tempdir().unwrap();
        let v = load(d.path(), &dead_url());
        assert_eq!(v.effective, Flags::default());
        assert!(v.error.is_some());
    }

    #[test]
    fn canonical_matches_python() {
        // python3 -c 'import json;print(json.dumps({"b":[1,True,None],"a":{"z":"é\n","y":0}},sort_keys=True,separators=(",",":"),ensure_ascii=False))'
        let v: Value = serde_json::from_str(r#"{"b":[1,true,null],"a":{"z":"é\n","y":0}}"#).unwrap();
        assert_eq!(canonical(&v), "{\"a\":{\"y\":0,\"z\":\"é\\n\"},\"b\":[1,true,null]}");
    }

    #[test]
    fn site_file_is_hash_checked() {
        let good = doc(&[("torrent_downloads", true)]);
        // The same document from stream/leyline_net.py make_doc() (stream/tests/test_leyline_net.py checks it too).
        assert_eq!(good["sha256"], "9a48f487b97315c24a01ebc948d1d71cd98409a7ece1d294897c7649d29b38c7");
        assert!(check(&good).is_ok());
        let f = from_doc(&good);
        assert!(f.torrent_downloads && !f.p2p_hosting);
        assert_eq!(f.stun, vec!["stun.cloudflare.com:3478"]);
        let mut tampered = good.clone();
        tampered["flags"]["p2p_hosting"] = Value::Bool(true);
        assert!(check(&tampered).unwrap_err().contains("sha256"));
        let d = tempfile::tempdir().unwrap();
        let base = serve_routes(vec![("/f.json", "200 OK", tampered.to_string().into_bytes())]);
        let v = load(d.path(), &format!("{base}/f.json"));
        assert!(!v.effective.p2p_hosting, "a tampered file counts as all off");
        let base = serve_routes(vec![("/f.json", "200 OK", good.to_string().into_bytes())]);
        let v = load(d.path(), &format!("{base}/f.json"));
        assert!(v.effective.torrent_downloads && !v.from_cache);
        assert!(current(d.path()).torrent_downloads, "cached for offline use");
    }

    #[test]
    fn local_overrides_win_both_ways() {
        let d = tempfile::tempdir().unwrap();
        let site = from_doc(&doc(&[("torrent_downloads", true)]));
        set_local(d.path(), "torrent_downloads", Some(false)).unwrap();
        set_local(d.path(), "p2p_hosting", Some(true)).unwrap();
        assert!(set_local(d.path(), "nope", Some(true)).is_err());
        let e = effective(&site, &load_local(d.path()));
        assert!(!e.torrent_downloads && e.p2p_hosting);
        set_local(d.path(), "torrent_downloads", None).unwrap();
        assert!(effective(&site, &load_local(d.path())).torrent_downloads);
        set_local_limits(d.path(), Some(Limits { seed_upload_kbps: 999_999, seed_ratio_pct: 150, max_peers: 10 })).unwrap();
        assert_eq!(load_local(d.path()).limits.unwrap().seed_upload_kbps, 100_000);
    }
}
