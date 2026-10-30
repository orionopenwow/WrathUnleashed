//! Shared `magnet:` links, behind the `magnet_links` flag (OFF by default; `flags.rs`, docs/P2P-AND-TORRENT.md).
//!
//! A magnet link names a torrent by its info-hash. Leyline opens one **only** when that info-hash is one of its own
//! checked packages: a Workshop mod package, a theme pack or the Host pack whose catalog entry (`/wrath/mods/all.json`,
//! cached) carries the package's info-hash as `btih`. Anything else is refused with a plain message, and nothing is
//! fetched or started for it. The link's own trackers and web seeds are checked for shape and then **ignored**: the
//! download uses the catalog's own addresses only, through the one download path (`transfer::fetch`: the closed list
//! of kinds, the refusal list in `checker` and the catalog's sha256). Never game data, never a game client.
//!
//! * `parse`: strict reading of `magnet:?xt=urn:btih:<40 hex | 32 base32>&dn=&tr=&ws=&xl=`.
//! * `known_from_catalog`: the packages a magnet may name, from the cached catalog (no network).
//! * `open`: flag check, parse, resolve, and queue it in an `Inbox` (`magnet_pending` in the app).
//! * `request` / `fetch`: hand an accepted package to `transfer::fetch`.
//!
//! The OS-level `magnet:` scheme handler is NOT registered yet (tauri.conf.json); a link reaches Leyline only through
//! its arguments (`from_args`) or the `magnet_open` command.

use super::flags::Flags;
use super::torrent;
use super::transfer::{self, Kind, Outcome, Request, Swarm};
use crate::catalog;
use crate::net;
use serde::Serialize;
use serde_json::Value;
use std::path::{Path, PathBuf};

pub const MAX_URI: usize = 2048;
const MAX_NAME: usize = 200;
const MAX_TRACKER: usize = 300;
const MAX_LIST: usize = 8;
/// Shared links kept for the UI, newest last.
pub const MAX_PENDING: usize = 20;
/// The plain answer for an info-hash Leyline does not know.
pub const UNKNOWN: &str = "Leyline only opens shared links to its own checked packages.";
pub const OFF: &str = "Shared magnet links are off (Settings > Advanced).";

/// A magnet link, checked.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Magnet {
    /// The v1 info-hash, 40 lower-case hex.
    pub info_hash: String,
    /// `dn`: a display name only; never used as a file name.
    pub name: Option<String>,
    /// `tr`: checked, never contacted.
    pub trackers: Vec<String>,
    /// `ws`: checked, never contacted.
    pub web_seeds: Vec<String>,
    /// `xl`: the size it claims.
    pub length: Option<u64>,
}

fn unescape(v: &str, plus_is_space: bool) -> Result<String, String> {
    let b = v.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        match b[i] {
            b'%' => {
                let h = b.get(i + 1..i + 3).and_then(|h| std::str::from_utf8(h).ok()).filter(|h| h.bytes().all(|c| c.is_ascii_hexdigit()));
                out.push(h.and_then(|h| u8::from_str_radix(h, 16).ok()).ok_or("a bad %-escape in the link")?);
                i += 3;
            }
            b'+' if plus_is_space => {
                out.push(b' ');
                i += 1;
            }
            c => {
                out.push(c);
                i += 1;
            }
        }
    }
    let s = String::from_utf8(out).map_err(|_| "the link is not UTF-8")?;
    if s.chars().any(char::is_control) {
        return Err("the link has control characters in it".into());
    }
    Ok(s)
}

/// RFC 4648 base32 of exactly 20 bytes (32 characters, no padding), any case.
fn base32_20(s: &str) -> Option<[u8; 20]> {
    if s.len() != 32 {
        return None;
    }
    let mut out = [0u8; 20];
    let (mut acc, mut bits, mut n) = (0u64, 0u32, 0usize);
    for c in s.bytes() {
        let v = match c.to_ascii_uppercase() {
            c @ b'A'..=b'Z' => c - b'A',
            c @ b'2'..=b'7' => c - b'2' + 26,
            _ => return None,
        } as u64;
        acc = (acc << 5) | v;
        bits += 5;
        if bits >= 8 {
            bits -= 8;
            out[n] = (acc >> bits) as u8;
            n += 1;
            acc &= (1 << bits) - 1;
        }
    }
    (n == 20).then_some(out)
}

/// `40 hex` or `32 base32` -> 40 lower-case hex.
pub fn info_hash(s: &str) -> Option<String> {
    if s.len() == 40 && s.bytes().all(|c| c.is_ascii_hexdigit()) {
        return Some(s.to_ascii_lowercase());
    }
    base32_20(s).map(|b| net::hex(&b))
}

/// `scheme://host[:port][/path]` with one of `schemes`, a normal host, no user info, no spaces.
fn url_ok(u: &str, schemes: &[&str], max: usize) -> bool {
    if u.is_empty() || u.len() > max || u.chars().any(|c| c.is_whitespace() || c.is_control()) {
        return false;
    }
    let Some((scheme, rest)) = u.split_once("://") else { return false };
    if !schemes.contains(&scheme) {
        return false;
    }
    let auth = rest.split(['/', '?', '#']).next().unwrap_or("");
    if auth.contains('@') {
        return false;
    }
    let (host, port) = match auth.rsplit_once(':') {
        Some((h, p)) => (h, Some(p)),
        None => (auth, None),
    };
    let host_ok = !host.is_empty()
        && host.len() <= 253
        && host.split('.').all(|p| !p.is_empty() && p.len() <= 63 && p.chars().all(|c| c.is_ascii_alphanumeric() || c == '-'));
    let port_ok = port.map_or(true, |p| !p.is_empty() && p.len() <= 5 && p.bytes().all(|c| c.is_ascii_digit()) && p.parse::<u16>().is_ok_and(|n| n > 0));
    host_ok && port_ok
}

/// Read a magnet link, strictly: exactly one `xt=urn:btih:`, at most one `dn` and `xl`, up to 8 `tr` (http, https,
/// udp) and 8 `ws` (https), and nothing else.
pub fn parse(uri: &str) -> Result<Magnet, String> {
    let uri = uri.trim();
    if uri.len() > MAX_URI {
        return Err("the link is too long".into());
    }
    if uri.chars().any(|c| c.is_whitespace() || c.is_control()) {
        return Err("the link has spaces or control characters in it".into());
    }
    let q = match uri.get(..8) {
        Some(p) if p.eq_ignore_ascii_case("magnet:?") => &uri[8..],
        _ => return Err("not a magnet link".into()),
    };
    if q.contains('#') {
        return Err("the link has a fragment".into());
    }
    let mut m = Magnet { info_hash: String::new(), name: None, trackers: vec![], web_seeds: vec![], length: None };
    let mut xt = 0;
    for pair in q.split('&') {
        if pair.is_empty() {
            continue;
        }
        let (k, v) = pair.split_once('=').ok_or("a part of the link has no value")?;
        match k {
            "xt" => {
                xt += 1;
                if xt > 1 {
                    return Err("the link names more than one torrent".into());
                }
                let v = unescape(v, false)?;
                let h = v.get(..9).filter(|p| p.eq_ignore_ascii_case("urn:btih:")).map(|_| &v[9..]).ok_or("only BitTorrent info-hash links are understood")?;
                m.info_hash = info_hash(h).ok_or("the link's info-hash is not 40 hex or 32 base32 characters")?;
            }
            "dn" => {
                if m.name.is_some() {
                    return Err("the link has two names".into());
                }
                let n = unescape(v, true)?;
                if n.trim().is_empty() || n.chars().count() > MAX_NAME {
                    return Err("the link's name is empty or too long".into());
                }
                m.name = Some(n.trim().to_string());
            }
            "tr" => {
                let t = unescape(v, false)?;
                if !url_ok(&t, &["http", "https", "udp"], MAX_TRACKER) || m.trackers.len() >= MAX_LIST {
                    return Err("the link has a tracker Leyline does not take".into());
                }
                m.trackers.push(t);
            }
            "ws" => {
                let w = unescape(v, false)?;
                if !url_ok(&w, &["https"], 400) || !net::plain_https(&w) || m.web_seeds.len() >= MAX_LIST {
                    return Err("the link has a web seed Leyline does not take (https only)".into());
                }
                m.web_seeds.push(w);
            }
            "xl" => {
                if m.length.is_some() {
                    return Err("the link has two sizes".into());
                }
                let n = (!v.is_empty() && v.len() <= 20 && v.bytes().all(|c| c.is_ascii_digit())).then(|| v.parse::<u64>().ok()).flatten();
                m.length = Some(n.filter(|n| *n > 0).ok_or("the link's size is not a number")?);
            }
            _ => return Err("the link has parts Leyline does not take".into()),
        }
    }
    if xt == 0 {
        return Err("the link names no torrent".into());
    }
    Ok(m)
}

/// The first `magnet:` link among the program's arguments (how the OS would hand one over).
pub fn from_args<I: IntoIterator<Item = String>>(args: I) -> Option<String> {
    args.into_iter().skip(1).take(8).find(|a| a.get(..7).is_some_and(|p| p.eq_ignore_ascii_case("magnet:")))
}

/// One package a magnet link may name: a catalog entry that carries its torrent's info-hash.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Known {
    pub info_hash: String,
    pub kind: Kind,
    /// The catalog id (`mod:<id>`), what the Discover page opens.
    pub id: String,
    pub name: String,
    pub version: Option<String>,
    pub size: Option<u64>,
    #[serde(skip)]
    pub sha256: String,
    #[serde(skip)]
    pub download: String,
    /// The package's own `.torrent` (catalog site only), used when `torrent_downloads` is on.
    #[serde(skip)]
    pub torrent: Option<String>,
}

impl Known {
    fn max_bytes(&self) -> u64 {
        match self.kind {
            Kind::ThemePack => crate::themes::MAX_PACK,
            Kind::HostPack => crate::host::pack::MAX_PACK,
            Kind::ModPackage | Kind::LauncherUpdate => crate::mods::MAX_DOWNLOAD,
        }
    }
}

fn btih_of(p: &Value) -> Option<String> {
    p.get("btih").and_then(Value::as_str).filter(|h| h.len() == 40).and_then(info_hash)
}

fn on_site(u: &str, origin: &str) -> bool {
    u.len() <= 400 && !u.chars().any(|c| c.is_whitespace() || c.is_control()) && net::origin(u).as_deref() == Some(origin) && u[origin.len()..].starts_with('/')
}

/// The packages an all.json document lets a magnet link name: packaged mods, theme packs and the Host pack with a
/// sha256, a download on the catalog's own site and a `btih`. An info-hash listed twice is dropped (ambiguous).
pub fn known_from_catalog(v: &Value, origin: &str) -> Vec<Known> {
    let mut out: Vec<Known> = Vec::new();
    let items = v.get("projects").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]);
    for raw in items.iter().take(catalog::MAX_PROJECTS) {
        let Some(info_hash) = btih_of(raw) else { continue };
        let torrent = raw.get("torrent").and_then(Value::as_str).filter(|t| on_site(t, origin)).map(String::from);
        let is_hostpack = raw.get("category").and_then(Value::as_str) == Some("tools") && raw.get("kind").and_then(Value::as_str) == Some("hostpack");
        let k = if is_hostpack {
            let one = serde_json::json!({"projects": [raw]});
            let id = raw.get("id").and_then(Value::as_str).filter(|i| catalog::id_ok(i));
            match (crate::host::pack::from_catalog(&one), id) {
                (Some(d), Some(id)) if on_site(&d.download, origin) => Known {
                    info_hash, kind: Kind::HostPack, id: id.into(), name: d.name, version: Some(d.version), size: d.size, sha256: d.sha256, download: d.download, torrent,
                },
                _ => continue,
            }
        } else {
            let Some(p) = serde_json::from_value::<catalog::Project>(raw.clone()).ok().and_then(|p| catalog::clean_in(p, origin, true)) else { continue };
            let (Some(sha256), Some(download), true) = (p.sha256.clone(), p.download.clone(), p.installable()) else { continue };
            let kind = if p.category == crate::themes::CATEGORY { Kind::ThemePack } else { Kind::ModPackage };
            Known { info_hash, kind, id: p.id, name: p.name, version: p.version, size: p.size, sha256, download, torrent }
        };
        out.push(k);
    }
    let dup = |h: &str, o: &[Known]| o.iter().filter(|k| k.info_hash == h).count() > 1;
    let all = out.clone();
    out.retain(|k| !dup(&k.info_hash, &all));
    out
}

/// The known packages from the cached catalog (no network).
pub fn known(app_dir: &Path) -> Vec<Known> {
    let Some(origin) = net::origin(catalog::URL) else { return vec![] };
    net::read_cache(&catalog::cache_path(app_dir)).map(|(v, _)| known_from_catalog(&v, &origin)).unwrap_or_default()
}

/// Which known package a magnet link names, or why it is refused.
pub fn resolve(m: &Magnet, known: &[Known]) -> Result<Known, String> {
    let k = known.iter().find(|k| k.info_hash == m.info_hash).ok_or(UNKNOWN)?;
    if let (Some(a), Some(b)) = (m.length, k.size) {
        if a != b {
            return Err("The link's size is not the package's, so Leyline will not open it.".into());
        }
    }
    Ok(k.clone())
}

/// What `magnet_open` answers.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum Opened {
    /// The flag is off: nothing was looked at.
    Off,
    /// One of Leyline's own packages. Nothing is downloaded until the player says so (`magnet_fetch`).
    Accepted {
        package: Known,
        /// What the UI opens to show it (the project with its INSTALL button); None for the Host pack (the Host page).
        open: Option<crate::deeplink::Link>,
    },
    Refused { reason: String },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Pending {
    pub info_hash: String,
    /// Seconds since 1970.
    pub received_at: u64,
    pub result: Opened,
}

/// The shared links this session received, for the UI's "Shared links" (newest last, at most `MAX_PENDING`).
#[derive(Debug, Default)]
pub struct Inbox(Vec<Pending>);

impl Inbox {
    pub fn push(&mut self, p: Pending) {
        self.0.retain(|x| x.info_hash != p.info_hash || p.info_hash.is_empty());
        self.0.push(p);
        let n = self.0.len();
        if n > MAX_PENDING {
            self.0.drain(..n - MAX_PENDING);
        }
    }
    pub fn list(&self) -> Vec<Pending> {
        self.0.clone()
    }
    /// Forget one (by info-hash) or all.
    pub fn dismiss(&mut self, info_hash: Option<&str>) {
        match info_hash {
            Some(h) => self.0.retain(|x| x.info_hash != h),
            None => self.0.clear(),
        }
    }
    /// An accepted package waiting under this info-hash.
    pub fn accepted(&self, info_hash: &str) -> Option<&Known> {
        self.0.iter().find_map(|p| match &p.result {
            Opened::Accepted { package, .. } if p.info_hash == info_hash => Some(package),
            _ => None,
        })
    }
}

fn now() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|t| t.as_secs()).unwrap_or(0)
}

/// Open a shared link: with the flag off, `Off` and nothing else; otherwise parse, resolve against `known` and queue
/// the answer in `inbox`. Nothing is fetched here, whatever the answer.
pub fn open(uri: &str, flags: &Flags, known: &[Known], inbox: &mut Inbox) -> Opened {
    if !flags.magnet_links {
        return Opened::Off;
    }
    let (hash, result) = match parse(uri) {
        Err(e) => (String::new(), Opened::Refused { reason: format!("This is not a link Leyline can open: {e}.") }),
        Ok(m) => match resolve(&m, known) {
            Ok(k) => {
                let open = (k.kind != Kind::HostPack).then(|| crate::deeplink::Link::Install(k.id.clone()));
                (m.info_hash, Opened::Accepted { package: k, open })
            }
            Err(reason) => (m.info_hash, Opened::Refused { reason }),
        },
    };
    inbox.push(Pending { info_hash: hash, received_at: now(), result: result.clone() });
    result
}

/// The download request for an accepted package: the catalog's address and sha256, never the link's. A `.torrent`
/// (already fetched from the catalog's site) is used only when its info-hash is the package's.
pub fn request(k: &Known, torrent_raw: Option<Vec<u8>>) -> Result<Request, String> {
    if let Some(raw) = &torrent_raw {
        let meta = torrent::parse(raw)?;
        if meta.info_hash_hex() != k.info_hash {
            return Err("The package's torrent is not the one the link names, so Leyline will not use it.".into());
        }
    }
    let ver = k.version.as_deref().unwrap_or("latest");
    let safe = |s: &str| s.chars().map(|c| if c.is_ascii_alphanumeric() || c == '.' { c } else { '-' }).collect::<String>();
    let name = format!("{}-{}.zip", safe(&k.id.replace(':', "-")), safe(ver));
    Ok(Request { kind: k.kind, name, sha256: k.sha256.clone(), https_url: k.download.clone(), torrent: torrent_raw, max_bytes: k.max_bytes() })
}

pub fn downloads_dir(app_dir: &Path) -> PathBuf {
    app_dir.join("downloads").join("magnet")
}

/// Download an accepted package through `transfer::fetch` (refusal list + sha256) into `downloads_dir`.
pub fn fetch(app_dir: &Path, k: &Known, flags: &Flags, swarm: &dyn Swarm) -> Result<(PathBuf, Outcome), String> {
    if !flags.magnet_links {
        return Err(OFF.into());
    }
    let dir = downloads_dir(app_dir);
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let torrent_raw = match (&k.torrent, flags.torrent_downloads) {
        (Some(t), true) => {
            let p = dir.join(format!("{}.torrent", k.info_hash));
            let got = net::download(t, &p, torrent::MAX_TORRENT_FILE as u64, net::TIMEOUT, net::TIMEOUT).ok().and_then(|_| std::fs::read(&p).ok());
            let _ = std::fs::remove_file(&p);
            got
        }
        _ => None,
    };
    let req = request(k, torrent_raw)?;
    let dest = dir.join(&req.name);
    let out = transfer::fetch(&req, &dest, flags, swarm)?;
    Ok((dest, out))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mods::tests::zip_of;
    use crate::net::testserver::*;
    use crate::p2p::transfer::NoSwarm;
    use sha2::{Digest, Sha256};

    const H: &str = "c12fe1c06bba254a9dc9f519b335aa7c1367a88a";

    fn on() -> Flags {
        Flags { magnet_links: true, ..Default::default() }
    }

    #[test]
    fn parses_good_links() {
        let m = parse(&format!("magnet:?xt=urn:btih:{}&dn=Night+Owl%20theme&tr=udp%3A%2F%2Ftracker.example.org%3A6969&tr=https://t.example.com/announce&ws=https%3A%2F%2Fplay.openvanilla.app%2Fx.zip&xl=1234", H.to_uppercase())).unwrap();
        assert_eq!(m.info_hash, H, "lower-cased");
        assert_eq!(m.name.as_deref(), Some("Night Owl theme"));
        assert_eq!(m.trackers, vec!["udp://tracker.example.org:6969", "https://t.example.com/announce"]);
        assert_eq!(m.web_seeds, vec!["https://play.openvanilla.app/x.zip"]);
        assert_eq!(m.length, Some(1234));
        // Base32 (32 chars) is the same hash.
        let b32 = "YEX6DQDLXISUVHOJ6UM3GNNKPQJWPKEK";
        assert_eq!(parse(&format!("MAGNET:?xt=URN:BTIH:{b32}")).unwrap().info_hash, H);
        assert_eq!(parse(&format!("magnet:?xt=urn:btih:{}", b32.to_lowercase())).unwrap().info_hash, H);
        // What torrent.rs writes for sharing reads back.
        let t = torrent::parse(&torrent::make("p.zip", b"abc", 16384, &["https://play.openvanilla.app/p.zip"])).unwrap();
        assert_eq!(parse(&t.magnet()).unwrap().info_hash, t.info_hash_hex());
    }

    #[test]
    fn refuses_odd_links() {
        let x = format!("xt=urn:btih:{H}");
        let bad = [
            "".to_string(), "magnet:".into(), "magnet:?".into(), "https://example.com/?xt=urn:btih:".into(),
            format!("magnet:{x}"), format!("magnet:?{x}&{x}"), format!("magnet:?{x}&xt=urn:btih:{}", "0".repeat(40)),
            "magnet:?xt=urn:btih:abc".into(), format!("magnet:?xt=urn:btih:{}", "g".repeat(40)),
            format!("magnet:?xt=urn:btih:{}", "1".repeat(32)), format!("magnet:?xt=urn:btmh:1220{}", "0".repeat(64)),
            format!("magnet:?xt=urn:sha1:{H}"), format!("magnet:?{x}&as=https://evil.example.com/x"),
            format!("magnet:?{x}&x.pe=1.2.3.4:5"), format!("magnet:?{x}&dn=a&dn=b"), format!("magnet:?{x}&dn="),
            format!("magnet:?{x}&dn={}", "a".repeat(201)), format!("magnet:?{x}&dn=%0Aevil"), format!("magnet:?{x}&dn=%ZZ"),
            format!("magnet:?{x}&dn=%FF"), format!("magnet:?{x}&tr=wss://t.example.com"), format!("magnet:?{x}&tr=ftp://t.example.com"),
            format!("magnet:?{x}&tr=http://user@t.example.com/"), format!("magnet:?{x}&tr=udp://t.example.com:99999"),
            format!("magnet:?{x}&tr=udp://"), format!("magnet:?{x}&ws=http://play.openvanilla.app/x.zip"),
            format!("magnet:?{x}&ws=https://1.2.3.4/x.zip"), format!("magnet:?{x}&xl=-1"), format!("magnet:?{x}&xl=0"),
            format!("magnet:?{x}&xl=1e9"), format!("magnet:?{x}&xl=1&xl=2"), format!("magnet:?{x}&xl={}", "9".repeat(25)),
            format!("magnet:?{x}&dn"), format!("magnet:?{x}#frag"), format!("magnet:?{x} &dn=a"),
            format!("magnet:?{x}{}", "&tr=udp://t.example.com:1".repeat(9)), format!("magnet:?{x}&dn={}", "a".repeat(MAX_URI)),
            "magnet:?dn=only-a-name".to_string(),
        ];
        for b in bad.iter() {
            assert!(parse(b).is_err(), "{b}");
        }
    }

    #[test]
    fn finds_the_link_in_the_arguments() {
        let a = |v: &[&str]| v.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        let link = format!("magnet:?xt=urn:btih:{H}");
        assert_eq!(from_args(a(&["leyline.exe", "--x", &link])), Some(link.clone()));
        assert_eq!(from_args(a(&[&link])), None, "the program name is not an argument");
        assert_eq!(from_args(a(&["leyline.exe", "leyline://install/mod:pings"])), None);
    }

    fn catalog_doc(base: &str, theme_sha: &str, mod_sha: &str) -> Value {
        serde_json::json!({"projects": [
            {"id": "mod:night-owl", "source": "packaged", "name": "Night Owl", "category": "themes", "version": "1.0.0",
             "download": format!("{base}/wrath/mods/night-owl/download"), "sha256": theme_sha, "btih": H.to_uppercase()},
            {"id": "mod:pings", "source": "packaged", "name": "Pings", "category": "addons", "version": "0.1.0",
             "download": format!("{base}/wrath/mods/pings/download"), "sha256": mod_sha, "btih": "1".repeat(40)},
            {"id": "mod:host-pack", "source": "packaged", "name": "Host pack", "category": "tools", "kind": "hostpack",
             "version": "2026.1029.1700", "download": format!("{base}/wrath/leyline/hostpack.zip"), "sha256": "ab".repeat(32), "size": 999,
             "btih": "2".repeat(40)},
            // Not packages Leyline may open: no btih, a community link, a download elsewhere, a twice-listed hash.
            {"id": "mod:no-hash", "source": "packaged", "download": format!("{base}/wrath/mods/x/download"), "sha256": "cd".repeat(32)},
            {"id": "link:3f9a0c12bd47", "source": "community", "btih": "3".repeat(40)},
            {"id": "mod:elsewhere", "source": "packaged", "download": "https://evil.example.com/x.zip", "sha256": "cd".repeat(32), "btih": "4".repeat(40)},
            {"id": "mod:twin-a", "source": "packaged", "download": format!("{base}/a"), "sha256": "cd".repeat(32), "btih": "5".repeat(40)},
            {"id": "mod:twin-b", "source": "packaged", "download": format!("{base}/b"), "sha256": "ef".repeat(32), "btih": "5".repeat(40)},
        ]})
    }

    #[test]
    fn only_the_catalogs_own_checked_packages_are_known() {
        let base = "https://play.openvanilla.app";
        let k = known_from_catalog(&catalog_doc(base, &"aa".repeat(32), &"bb".repeat(32)), base);
        let ids: Vec<(&str, Kind)> = k.iter().map(|k| (k.id.as_str(), k.kind)).collect();
        assert_eq!(ids, vec![("mod:night-owl", Kind::ThemePack), ("mod:pings", Kind::ModPackage), ("mod:host-pack", Kind::HostPack)]);
        assert_eq!(k[0].info_hash, H);
        let json = serde_json::to_value(&k[0]).unwrap();
        assert!(json.get("sha256").is_none() && json.get("download").is_none(), "the UI sees the package, not its addresses");
    }

    #[test]
    fn off_means_off_and_unknown_hashes_are_refused() {
        let base = "https://play.openvanilla.app";
        let known = known_from_catalog(&catalog_doc(base, &"aa".repeat(32), &"bb".repeat(32)), base);
        let mut inbox = Inbox::default();
        let link = format!("magnet:?xt=urn:btih:{H}&dn=x");
        assert_eq!(open(&link, &Flags::default(), &known, &mut inbox), Opened::Off);
        assert!(inbox.list().is_empty(), "off: nothing queued");
        // Unknown hash: the plain refusal, whatever trackers or web seeds the link brings.
        let r = open(&format!("magnet:?xt=urn:btih:{}&ws=https://evil.example.com/game.zip", "9".repeat(40)), &on(), &known, &mut inbox);
        assert_eq!(r, Opened::Refused { reason: UNKNOWN.into() });
        for h in ["3", "4", "5"] {
            assert_eq!(open(&format!("magnet:?xt=urn:btih:{}", h.repeat(40)), &on(), &known, &mut inbox), Opened::Refused { reason: UNKNOWN.into() }, "{h}");
        }
        assert!(matches!(open("magnet:?xt=urn:btih:nope", &on(), &known, &mut inbox), Opened::Refused { .. }));
        // A wrong size is refused too.
        assert!(matches!(open(&format!("magnet:?xt=urn:btih:{}&xl=5", "2".repeat(40)), &on(), &known, &mut inbox), Opened::Refused { .. }));
        // Known: accepted, with the page to open; queued once even when shared twice.
        let r = open(&link, &on(), &known, &mut inbox);
        let Opened::Accepted { package, open: page } = &r else { panic!("{r:?}") };
        assert_eq!((package.id.as_str(), page.clone()), ("mod:night-owl", Some(crate::deeplink::Link::Install("mod:night-owl".into()))));
        open(&link, &on(), &known, &mut inbox);
        assert_eq!(inbox.list().iter().filter(|p| p.info_hash == H).count(), 1);
        assert!(inbox.accepted(H).is_some() && inbox.accepted(&"9".repeat(40)).is_none());
        let hp = open(&format!("magnet:?xt=urn:btih:{}&xl=999", "2".repeat(40)), &on(), &known, &mut inbox);
        assert!(matches!(hp, Opened::Accepted { open: None, .. }), "the Host pack opens the Host page");
        let json = serde_json::to_value(&r).unwrap();
        assert_eq!(json["status"], "accepted");
        assert_eq!(json["package"]["kind"], "theme_pack");
        assert_eq!(serde_json::to_value(Opened::Off).unwrap(), serde_json::json!({"status": "off"}));
        inbox.dismiss(Some(H));
        assert!(inbox.accepted(H).is_none());
        for i in 0..30 {
            inbox.push(Pending { info_hash: format!("{i:040}"), received_at: 0, result: Opened::Off });
        }
        assert_eq!(inbox.list().len(), MAX_PENDING);
        inbox.dismiss(None);
        assert!(inbox.list().is_empty());
    }

    #[test]
    fn accepted_packages_go_through_the_one_download_path() {
        let theme = zip_of(&[("theme.json", b"{\"id\":\"night-owl\"}")]);
        let game = zip_of(&[("x/patch.txt", b"MPQ\x1a....")]);
        let sha = |b: &[u8]| net::hex(&Sha256::digest(b));
        let base = serve_routes(vec![("/wrath/mods/night-owl/download", "200 OK", theme.clone()), ("/wrath/mods/pings/download", "200 OK", game.clone())]);
        let known = known_from_catalog(&catalog_doc(&base, &sha(&theme), &sha(&game)), &base);
        let d = tempfile::tempdir().unwrap();
        // Flag off: no download.
        assert_eq!(fetch(d.path(), &known[0], &Flags::default(), &NoSwarm).unwrap_err(), OFF);
        let (path, out) = fetch(d.path(), &known[0], &on(), &NoSwarm).unwrap();
        assert_eq!((out.sha256.clone(), out.via), (sha(&theme), transfer::Via::Https));
        assert!(path.starts_with(downloads_dir(d.path())) && path.exists());
        // Game data behind a known hash is still refused by the checker, and nothing is left behind.
        let e = fetch(d.path(), &known[1], &on(), &NoSwarm).unwrap_err();
        assert!(e.starts_with("Refused"), "{e}");
        assert!(!downloads_dir(d.path()).join("mod-pings-0.1.0.zip").exists());
        // A torrent whose info-hash is not the link's is not used.
        let other = torrent::make("x.zip", b"other", 16384, &[]);
        assert!(request(&known[0], Some(other)).unwrap_err().contains("not the one"));
        // The catalog's sha256 still decides.
        let mut k = known[0].clone();
        k.sha256 = "0".repeat(64);
        assert!(fetch(d.path(), &k, &on(), &NoSwarm).unwrap_err().contains("sha256"));
    }

    #[test]
    fn known_reads_the_cached_catalog_only() {
        let d = tempfile::tempdir().unwrap();
        assert!(known(d.path()).is_empty(), "no catalog yet: nothing is known");
        let doc = catalog_doc("https://play.openvanilla.app", &"aa".repeat(32), &"bb".repeat(32));
        crate::settings::write_atomic(&catalog::cache_path(d.path()), doc.to_string().as_bytes()).unwrap();
        assert_eq!(known(d.path()).len(), 3);
    }
}
