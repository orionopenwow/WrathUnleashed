//! Upstream addons: third-party addons the Workshop lists (all.json `source: "upstream"`, id `up:<slug>`) and the
//! launcher installs straight from the author's own repo. We never host them; a copy on our site (`mirror`) only
//! when the entry says `mirror_allowed` (an open licence and no .blp art). Every entry was curated and reviewed by a
//! person first (tools/addon-curate/curate.py, mods/SPEC.md "Upstream addons").
//!
//! * Where from: `install.url` must be the entry's own repo, in one of these shapes only: a GitHub release asset
//!   (`github.com/<o>/<r>/releases/download/...`), a commit archive pinned to a 40-hex commit
//!   (`github.com/<o>/<r>/archive/<commit>.zip`, `gitlab.com/<o>/<r>/-/archive/<commit>/...`,
//!   `codeberg.org/<o>/<r>/archive/<commit>.zip`), or our own site for a mirror. Redirects are followed by hand,
//!   https only, and only to the forges' download hosts (`REDIRECT_HOSTS`).
//! * What is checked: the zip's sha256 when the entry has one (release assets and mirrors are byte-stable), and
//!   always every file: each installed file's sha256 against `install.files` (nothing missing, nothing extra), or the
//!   digest of the whole list. GitHub's commit archives are not byte-stable, their files are.
//! * The rules: `upstream-rules.json`, built in here and read by curate.py too, so the two cannot disagree. Game
//!   data, native code and archives anywhere in the download refuse it. Dev files (.pkgmeta, .github/, README...)
//!   are skipped, not errors. Relaxed for curated entries only: .blp textures when the entry says `blp:
//!   "author-art"`, folder names with a leading `!` or `_` or a `+`, an `## Interface:` list that holds 30300.
//! * How it is installed: through the mod manager (`mods::install`) as one entry keyed `up:<slug>` in the client's
//!   `Leyline/mods.json`, so Remove, turn off and on, and "keep the player's edits" work as for every mod. The
//!   installed `sha256` field holds the upstream `rev`: a catalog entry with another rev is an update.

use crate::catalog::Project;
use crate::clients::Build;
use crate::mods::{self, AddonPlan, InstallMeta, Installed, Plan};
use crate::net;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::fs;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::Duration;

/// The one rules list (tools/addon-curate/curate.py reads the same file).
pub const RULES_JSON: &str = include_str!("upstream-rules.json");

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct Caps {
    pub file: u64,
    pub total: u64,
    pub files: usize,
    pub download: u64,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct Rules {
    pub interface: String,
    pub install_ext: Vec<String>,
    pub blp_ext: String,
    pub refuse_ext: Vec<String>,
    pub refuse_magic: BTreeMap<String, String>,
    pub blp_magic: Vec<String>,
    pub skip_dirs: Vec<String>,
    pub skip_names: Vec<String>,
    pub skip_ext: Vec<String>,
    pub reserved: Vec<String>,
    pub reserved_prefix: Vec<String>,
    pub caps: Caps,
    pub open_licences: Vec<String>,
}

pub fn rules() -> &'static Rules {
    static R: OnceLock<Rules> = OnceLock::new();
    R.get_or_init(|| serde_json::from_str(RULES_JSON).expect("upstream-rules.json"))
}

/// Where a download may be redirected to (https only).
pub const REDIRECT_HOSTS: &[&str] =
    &["objects.githubusercontent.com", "release-assets.githubusercontent.com", "codeload.github.com", "gitlab.com", "codeberg.org"];
/// The forges an entry's repo may be on.
pub const FORGES: &[&str] = &["github.com", "gitlab.com", "codeberg.org"];

/// How an upstream entry is installed (all.json `install`).
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Install {
    /// `release-asset`, `commit-archive` or `mirror`.
    pub from: String,
    pub url: String,
    pub mirror_url: Option<String>,
    /// The release tag or the 40-hex commit.
    pub rev: String,
    /// The zip's sha256 (release assets and mirrors only: GitHub's commit archives are not byte-stable).
    pub sha256: Option<String>,
    pub size: u64,
    pub file_count: u64,
    /// The archive's top folder (`Repo-<commit>/`), taken off every path.
    pub strip_prefix: String,
    /// Archive folder (after strip_prefix) -> addon folder name. `""` is the archive's root ("the repo is the addon").
    pub folders: BTreeMap<String, String>,
    /// What curation skipped (informational: only `files` are ever installed).
    pub skip: Vec<String>,
    /// `<Addon>/<path>` -> sha256 of every installed file.
    pub files: BTreeMap<String, String>,
    /// sha256 of the sorted `<path>\0<sha256>\n` lines of `files` (what is checked when `files` is left out).
    pub files_digest: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Review {
    pub by: String,
    pub at: String,
    pub notes: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Compat {
    pub realm: String,
    /// `works`, `untested` or `broken`.
    pub status: String,
    pub checked_at: String,
}

// ------------------------------------------------------------------------------------------------ the rules

fn ext(p: &str) -> String {
    let base = p.rsplit('/').next().unwrap_or(p);
    match base.rfind('.') {
        Some(i) if i > 0 => base[i..].to_ascii_lowercase(),
        _ => String::new(),
    }
}

fn hex4(head: &[u8]) -> String {
    net::hex(&head[..head.len().min(4)])
}

/// What happens to one file inside an addon folder (`path` relative to the folder; `head` its first bytes):
/// `install`, `skip`, `blp` (a texture, installed only when the entry allows author art) or `refuse: <why>`
/// (the whole entry is refused). curate.py `classify` answers the same (upstream-cases.json).
pub fn classify(path: &str, blp_ok: bool, head: &[u8]) -> String {
    let r = rules();
    let low = path.to_ascii_lowercase();
    let parts: Vec<&str> = low.split('/').collect();
    let base = parts.last().copied().unwrap_or("");
    let e = ext(&low);
    if r.refuse_ext.contains(&e) {
        return format!("refuse: {e} files are never allowed");
    }
    let h = hex4(head);
    if let Some((_, what)) = r.refuse_magic.iter().find(|(m, _)| h.starts_with(m.as_str())) {
        return format!("refuse: {what} (by its first bytes)");
    }
    if r.blp_magic.contains(&h) && e != r.blp_ext {
        return "refuse: a renamed .blp texture".into();
    }
    if parts[..parts.len() - 1].iter().any(|p| r.skip_dirs.iter().any(|d| d == p)) {
        return "skip".into();
    }
    if r.skip_names.iter().any(|n| n == base) || r.skip_ext.contains(&e) {
        return "skip".into();
    }
    if e == r.blp_ext {
        return if blp_ok { "install".into() } else { "blp".into() };
    }
    if r.install_ext.contains(&e) {
        return "install".into();
    }
    "skip".into()
}

/// An addon folder name for a curated entry: letters, digits, `_ . + ! -`, a leading `!` or `_` allowed, at most 64,
/// not the realm's own or the game's (`Blizzard_*`).
pub fn name_ok(n: &str) -> bool {
    let r = rules();
    let low = n.to_ascii_lowercase();
    let first = n.chars().next();
    !n.is_empty()
        && n.len() <= 64
        && first.is_some_and(|c| c.is_ascii_alphanumeric() || c == '!' || c == '_')
        && n.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | '+' | '!' | '-'))
        && !n.ends_with('.')
        && !r.reserved.contains(&low)
        && !r.reserved_prefix.iter().any(|p| low.starts_with(p.as_str()))
}

/// `## Interface:` holds 30300, alone or in a comma list.
pub fn interface_ok(v: &str) -> bool {
    v.split(',').any(|x| x.trim() == rules().interface)
}

const BRAND: &[&str] = &["world of warcraft", "wrath of the lich king", "warcraft", "lich king", "blizzard", "wotlk"];

/// A name to show: TOC colour codes and the game's brand words taken out (curate.py `clean_name`), for upstream
/// entries and for the TOC titles My Mods shows.
pub fn clean_title(raw: &str) -> String {
    // |cAARRGGBB ... |r and |T...|t
    let mut s = String::new();
    let cs: Vec<char> = raw.chars().collect();
    let mut i = 0;
    while i < cs.len() {
        if cs[i] == '|' && i + 1 < cs.len() {
            match cs[i + 1] {
                'c' | 'C' if i + 10 <= cs.len() => {
                    i += 10;
                    continue;
                }
                'r' | 'R' => {
                    i += 2;
                    continue;
                }
                'T' => {
                    let mut j = i + 2;
                    while j + 1 < cs.len() && !(cs[j] == '|' && cs[j + 1] == 't') {
                        j += 1;
                    }
                    i = j + 2;
                    continue;
                }
                _ => {}
            }
        }
        s.push(cs[i]);
        i += 1;
    }
    // Brand phrases, case-insensitive; "wow" as its own word in any case, "WoW"/"WOW" anywhere, "Wow" glued to a
    // capital or digit ("WowAddon") or after lower-case letters ("NewWow"): curate.py BANNED_RE.
    let mut out = s;
    loop {
        let low = out.to_ascii_lowercase();
        let b = out.as_bytes();
        let mut hit = BRAND.iter().find_map(|w| low.find(w).map(|i| (i, w.len())));
        if hit.is_none() {
            let mut k = 0;
            while let Some(j) = low[k..].find("wow") {
                let i = k + j;
                let w = &out[i..i + 3];
                let prev = if i == 0 { None } else { Some(b[i - 1]) };
                let next = b.get(i + 3).copied();
                let letter = |c: Option<u8>| c.is_some_and(|c| c.is_ascii_alphabetic());
                let lower = |c: Option<u8>| c.is_some_and(|c| c.is_ascii_lowercase());
                let glued = w == "Wow"
                    && ((!lower(prev) && next.is_some_and(|c| c.is_ascii_uppercase() || c.is_ascii_digit())) || (lower(prev) && !lower(next)));
                if (!letter(prev) && !letter(next)) || w == "WoW" || w == "WOW" || glued {
                    hit = Some((i, 3));
                    break;
                }
                k = i + 1;
            }
        }
        match hit {
            Some((i, n)) => out.replace_range(i..i + n, " "),
            None => break,
        }
    }
    let out = out.replace("()", " ").replace("[]", " ").replace("( )", " ").replace("[ ]", " ");
    let words: Vec<&str> = out.split_whitespace().collect();
    let joined = words.join(" ");
    let t = joined.trim_matches(|c: char| matches!(c, ' ' | '-' | '_' | '.' | '*'));
    let t: String = t.chars().filter(|c| !c.is_control()).take(64).collect();
    // "Foo--Bar" left by a removed word in the middle of a name
    let mut tidy = String::new();
    for c in t.chars() {
        if matches!(c, '-' | '_' | '.' | ' ') && tidy.ends_with(['-', '_', '.', ' ']) {
            continue;
        }
        tidy.push(c);
    }
    tidy.trim().to_string()
}

// ------------------------------------------------------------------------------------------------ the entry

fn hex64(s: &str) -> bool {
    s.len() == 64 && s.chars().all(|c| c.is_ascii_hexdigit())
}

fn hex40(s: &str) -> bool {
    s.len() == 40 && s.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
}

/// The forge, owner and repo of a canonical repo link (`https://github.com/<o>/<r>`).
pub fn repo_parts(repo: &str) -> Option<(&str, &str, &str)> {
    let rest = repo.strip_prefix("https://")?;
    let mut it = rest.split('/');
    let (host, o, r) = (it.next()?, it.next()?, it.next()?);
    let part = |s: &str| !s.is_empty() && s.len() <= 100 && s.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.')) && !s.starts_with('.');
    (it.next().is_none() && FORGES.contains(&host) && part(o) && part(r)).then_some((host, o, r))
}

/// The download address is the entry's own repo in an allowed shape (or our own site for a mirror).
pub fn url_ok(inst: &Install, repo: &str, origin: &str, mirror_allowed: bool) -> bool {
    let u = inst.url.as_str();
    if u.len() > 400 || u.chars().any(|c| c.is_whitespace() || c.is_control() || matches!(c, '?' | '#' | '\\' | '%')) || u.contains("/../") {
        return false;
    }
    if inst.from == "mirror" {
        let local_test = cfg!(test) && u.starts_with("http://127.0.0.1:");
        return mirror_allowed
            && inst.sha256.as_deref().is_some_and(hex64)
            && (local_test || net::plain_https(u))
            && net::origin(u).as_deref() == Some(origin)
            && u[origin.len()..].starts_with("/wrath/mods/");
    }
    let Some((host, o, r)) = repo_parts(repo) else { return false };
    match (inst.from.as_str(), host) {
        ("release-asset", "github.com") => {
            let pre = format!("https://github.com/{o}/{r}/releases/download/");
            u.strip_prefix(&pre).is_some_and(|rest| {
                let parts: Vec<&str> = rest.split('/').collect();
                parts.len() == 2 && parts.iter().all(|p| !p.is_empty() && *p != "." && *p != "..") && parts[1].to_ascii_lowercase().ends_with(".zip")
            })
        }
        ("commit-archive", "github.com") => hex40(&inst.rev) && u == format!("https://github.com/{o}/{r}/archive/{}.zip", inst.rev),
        ("commit-archive", "gitlab.com") => {
            hex40(&inst.rev) && u == format!("https://gitlab.com/{o}/{r}/-/archive/{rev}/{r}-{rev}.zip", rev = inst.rev)
        }
        ("commit-archive", "codeberg.org") => hex40(&inst.rev) && u == format!("https://codeberg.org/{o}/{r}/archive/{}.zip", inst.rev),
        _ => false,
    }
}

/// A redirect from `from` to `to` may be followed: https, to one of the forges' download hosts (or the same host).
pub fn redirect_ok(from: &str, to: &str) -> bool {
    if cfg!(test) && from.starts_with("http://127.0.0.1:") && to.starts_with("http://127.0.0.1:") {
        return true;
    }
    if !net::plain_https(to) {
        return false;
    }
    let host = |u: &str| net::origin(u).map(|o| o.trim_start_matches("https://").to_string());
    match (host(from), host(to)) {
        (Some(f), Some(t)) => REDIRECT_HOSTS.contains(&t.as_str()) || (f == t && FORGES.contains(&t.as_str())),
        _ => false,
    }
}

/// An entry's install block is sound: an allowed address, folder names, and a file list (or digest) of addon files.
pub fn install_ok(inst: &Install, repo: &str, origin: &str, mirror_allowed: bool, blp_ok: bool) -> bool {
    let r = rules();
    if !matches!(inst.from.as_str(), "release-asset" | "commit-archive" | "mirror") || !url_ok(inst, repo, origin, mirror_allowed) {
        return false;
    }
    if inst.rev.is_empty() || inst.rev.len() > 80 || inst.rev.chars().any(|c| c.is_whitespace() || c.is_control()) {
        return false;
    }
    if inst.sha256.as_deref().is_some_and(|s| !hex64(s)) {
        return false;
    }
    if !inst.strip_prefix.is_empty() && (!inst.strip_prefix.ends_with('/') || mods::safe_rel(inst.strip_prefix.trim_end_matches('/')).ok().flatten().is_none()) {
        return false;
    }
    if inst.folders.is_empty() || inst.folders.len() > 32 {
        return false;
    }
    for (k, v) in &inst.folders {
        if !name_ok(v) || (!k.is_empty() && mods::safe_rel(k).ok().flatten().as_deref() != Some(k.as_str())) {
            return false;
        }
    }
    if inst.folders.contains_key("") && inst.folders.len() > 1 {
        return false;
    }
    if inst.size > r.caps.total || inst.file_count as usize > r.caps.files {
        return false;
    }
    if inst.files.is_empty() {
        return hex64(&inst.files_digest);
    }
    let names: HashSet<&str> = inst.folders.values().map(String::as_str).collect();
    inst.files.len() <= r.caps.files
        && inst.files.iter().all(|(p, sha)| {
            hex64(sha)
                && mods::safe_rel(p).ok().flatten().as_deref() == Some(p.as_str())
                && p.split_once('/').is_some_and(|(top, _)| names.contains(top))
                && classify(p.split_once('/').map(|x| x.1).unwrap_or(""), blp_ok, b"") == "install"
        })
}

/// The digest of a file list (curate.py `files_digest`).
pub fn files_digest(files: &BTreeMap<String, String>) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    for (p, s) in files {
        h.update(p.as_bytes());
        h.update([0u8]);
        h.update(s.as_bytes());
        h.update(b"\n");
    }
    net::hex(&h.finalize())
}

// ------------------------------------------------------------------------------------------------ download

fn agent() -> ureq::Agent {
    ureq::AgentBuilder::new()
        .timeout_connect(net::TIMEOUT)
        .timeout_read(Duration::from_secs(60))
        .redirects(0)
        .user_agent(concat!("Leyline/", env!("CARGO_PKG_VERSION")))
        .build()
}

/// Download `url` into `dest`, following at most 5 redirects by hand and only where `redirect_ok` says. At most
/// `max` bytes. Returns (bytes, sha256).
pub fn download(url: &str, dest: &Path, max: u64) -> Result<(u64, String), String> {
    use sha2::{Digest, Sha256};
    let mut at = url.to_string();
    let mut resp = None;
    for _ in 0..6 {
        let r = match agent().get(&at).call() {
            Ok(r) => r,
            Err(ureq::Error::Status(code, _)) => return Err(format!("the author's site answered {code}")),
            Err(e) => return Err(e.to_string()),
        };
        if (300..400).contains(&r.status()) {
            let loc = r.header("Location").unwrap_or_default().to_string();
            let next = if loc.starts_with('/') { format!("{}{loc}", net::origin(&at).unwrap_or_default()) } else { loc };
            if !redirect_ok(&at, &next) {
                return Err(format!("the download was sent somewhere Leyline does not download from ({})", net::origin(&next).unwrap_or_default()));
            }
            at = next;
            continue;
        }
        resp = Some(r);
        break;
    }
    let resp = resp.ok_or("too many redirects")?;
    if resp.header("Content-Length").and_then(|v| v.trim().parse::<u64>().ok()).is_some_and(|n| n > max) {
        return Err(format!("the download is larger than {} MB", max / 1_048_576));
    }
    let result = (|| {
        let mut f = fs::File::create(dest).map_err(|e| e.to_string())?;
        let mut rd = resp.into_reader().take(max + 1);
        let mut h = Sha256::new();
        let mut buf = vec![0u8; 64 * 1024];
        let mut total = 0u64;
        loop {
            let n = rd.read(&mut buf).map_err(|e| format!("the download broke off: {e}"))?;
            if n == 0 {
                break;
            }
            total += n as u64;
            if total > max {
                return Err(format!("the download is larger than {} MB", max / 1_048_576));
            }
            h.update(&buf[..n]);
            f.write_all(&buf[..n]).map_err(|e| e.to_string())?;
        }
        Ok((total, net::hex(&h.finalize())))
    })();
    if result.is_err() {
        let _ = fs::remove_file(dest);
    }
    result
}

// ------------------------------------------------------------------------------------------------ unpack and check

/// Where an archive path lands: `<Addon>/<inner>` by `strip_prefix` and `folders`, or None (not installed).
pub fn map_path(inst: &Install, raw: &str) -> Option<String> {
    let rel = raw.strip_prefix(inst.strip_prefix.as_str())?;
    if let Some(name) = inst.folders.get("") {
        return Some(format!("{name}/{rel}"));
    }
    let mut best: Option<(&String, &String)> = None;
    for (d, name) in &inst.folders {
        if rel.starts_with(&format!("{d}/")) && best.map_or(true, |(b, _)| d.len() > b.len()) {
            best = Some((d, name));
        }
    }
    best.map(|(d, name)| format!("{name}/{}", &rel[d.len() + 1..]))
}

/// What an unpack found.
#[derive(Debug, Default)]
pub struct Unpacked {
    /// `<Addon>/<inner>` -> where it is now.
    pub files: BTreeMap<String, PathBuf>,
    pub skipped: usize,
}

/// Unpack only the files the entry installs into `dest`, refusing the whole download for game data, native code or
/// archives anywhere in it (outside skipped dev folders), zip-slip, links, passwords, odd packing, or sizes past the caps.
pub fn unpack(zip: &Path, dest: &Path, inst: &Install, blp_ok: bool) -> Result<Unpacked, String> {
    let r = rules();
    let f = fs::File::open(zip).map_err(|e| format!("could not read the download: {e}"))?;
    let mut ar = zip::ZipArchive::new(io::BufReader::new(f)).map_err(|_| "the download is not a zip file (or it is damaged)".to_string())?;
    if ar.len() > r.caps.files * 3 {
        return Err("the download has too many files".into());
    }
    let mut out = Unpacked::default();
    let mut seen = HashSet::new();
    let mut total = 0u64;
    for i in 0..ar.len() {
        let mut file = ar.by_index(i).map_err(|e| format!("the download is damaged or packed in a way Leyline cannot read ({e})"))?;
        if file.is_dir() {
            continue;
        }
        let raw = String::from_utf8_lossy(file.name_raw()).to_string();
        let Some(rel) = mods::safe_rel(&raw)? else { continue };
        let low = rel.to_ascii_lowercase();
        if low.split('/').any(|p| r.skip_dirs.iter().any(|d| d == p)) {
            out.skipped += 1;
            continue;
        }
        if file.encrypted() {
            return Err(format!("the download is password protected: {rel}"));
        }
        if file.unix_mode().is_some_and(|m| m & 0o170000 == 0o120000) {
            return Err(format!("symbolic links are not allowed: {rel}"));
        }
        if !matches!(file.compression(), zip::CompressionMethod::Stored | zip::CompressionMethod::Deflated) {
            return Err(format!("{rel} is packed in a way Leyline cannot read"));
        }
        if !seen.insert(low.clone()) {
            return Err(format!("the download has two files named {rel} (they differ only in case)"));
        }
        if file.size() > r.caps.file {
            return Err(format!("{rel} is larger than {} MB", r.caps.file / 1_048_576));
        }
        let mut head = [0u8; 4];
        let mut body = Vec::new();
        (&mut file).take(r.caps.file + 1).read_to_end(&mut body).map_err(|_| format!("the download is damaged: {rel} does not unpack"))?;
        if body.len() as u64 > r.caps.file {
            return Err(format!("{rel} unpacks bigger than it says"));
        }
        head[..body.len().min(4)].copy_from_slice(&body[..body.len().min(4)]);
        let verdict = classify(&rel, true, &head[..body.len().min(4)]);
        if let Some(why) = verdict.strip_prefix("refuse: ") {
            return Err(format!("{rel}: {why}, so Leyline will not install this addon"));
        }
        let Some(dest_rel) = map_path(inst, &rel) else {
            out.skipped += 1;
            continue;
        };
        let wanted = if inst.files.is_empty() {
            let inner = dest_rel.split_once('/').map(|x| x.1).unwrap_or("");
            let top_toc = !inner.contains('/') && ext(inner) == ".toc";
            let own_toc = top_toc && inst.folders.get("").is_some_and(|n| inner[..inner.len() - 4] != **n);
            classify(inner, blp_ok, &head) == "install" && !own_toc
        } else {
            inst.files.contains_key(&dest_rel)
        };
        if !wanted {
            out.skipped += 1;
            continue;
        }
        total += body.len() as u64;
        if total > r.caps.total || out.files.len() >= r.caps.files {
            return Err("the addon unpacks bigger than Leyline allows".into());
        }
        let to = dest.join(&dest_rel);
        fs::create_dir_all(to.parent().unwrap()).map_err(|e| e.to_string())?;
        fs::write(&to, &body).map_err(|e| e.to_string())?;
        out.files.insert(dest_rel, to);
    }
    Ok(out)
}

/// Every unpacked file against the entry: the file list (each hash, nothing missing) or the digest of the whole set.
pub fn verify(u: &Unpacked, inst: &Install) -> Result<(), String> {
    let bad = |what: String| Err(format!("The download does not match what was reviewed ({what}), so nothing was installed."));
    let mut got = BTreeMap::new();
    for (p, abs) in &u.files {
        got.insert(p.clone(), net::sha256_file(abs).unwrap_or_default());
    }
    if inst.files.is_empty() {
        return if files_digest(&got) == inst.files_digest { Ok(()) } else { bad("the files differ".into()) };
    }
    for (p, want) in &inst.files {
        match got.get(p) {
            None => return bad(format!("{p} is missing")),
            Some(h) if h != want => return bad(format!("{p} changed")),
            _ => {}
        }
    }
    if let Some(extra) = got.keys().find(|k| !inst.files.contains_key(*k)) {
        return bad(format!("{extra} is not in the list"));
    }
    Ok(())
}

fn parse_toc(text: &str) -> BTreeMap<String, String> {
    let mut meta = BTreeMap::new();
    for line in text.lines() {
        let s = line.trim().trim_start_matches('\u{feff}');
        if let Some((k, v)) = s.strip_prefix("##").and_then(|r| r.split_once(':')) {
            meta.entry(k.trim().to_string()).or_insert_with(|| v.trim().to_string());
        }
    }
    meta
}

/// The install plan for verified files: one addon per folder, each with its .toc for this client.
pub fn plan_of(u: &Unpacked, inst: &Install, build: Build) -> Plan {
    let mut plan = Plan::default();
    if build != Build::V335a {
        plan.errors.push(format!("this addon is for 3.3.5a clients; this one is {}", build.catalog_tag()));
        return plan;
    }
    let names: BTreeSet<&String> = inst.folders.values().collect();
    for name in names {
        let pre = format!("{name}/");
        let files: Vec<(String, PathBuf)> =
            u.files.iter().filter_map(|(p, abs)| p.strip_prefix(&pre).map(|inner| (inner.to_string(), abs.clone()))).collect();
        let toc = files.iter().find(|(p, _)| p.eq_ignore_ascii_case(&format!("{name}.toc")));
        let Some((_, toc_abs)) = toc else {
            plan.errors.push(format!("{name}: no {name}.toc"));
            continue;
        };
        let meta = parse_toc(&fs::read_to_string(toc_abs).unwrap_or_default());
        if !interface_ok(meta.get("Interface").map(String::as_str).unwrap_or("")) {
            plan.errors.push(format!("{name}: its .toc is not for this client (## Interface: {})", meta.get("Interface").map(String::as_str).unwrap_or("none")));
        }
        for (p, abs) in &files {
            let e = ext(p);
            if e == ".blp" || [".tga", ".ttf", ".ogg", ".mp3", ".wav"].contains(&e.as_str()) {
                continue;
            }
            if let Some(what) = mods::secret_in(&fs::read(abs).unwrap_or_default()) {
                plan.errors.push(format!("{name}/{p} holds {what}: not installed"));
            }
        }
        let size = files.iter().map(|(_, a)| fs::metadata(a).map(|m| m.len()).unwrap_or(0)).sum();
        plan.addons.push(AddonPlan {
            name: name.clone(),
            files,
            size,
            title: meta.get("Title").map(|t| clean_title(t)).filter(|t| !t.is_empty()),
            version: meta.get("Version").map(|v| v.chars().take(40).collect()),
        });
    }
    if plan.addons.is_empty() && plan.errors.is_empty() {
        plan.errors.push("no addon in the download".into());
    }
    plan
}

/// The project's install block, checked again (catalog::clean already did).
fn checked<'a>(p: &'a Project, origin: &str) -> Result<&'a Install, String> {
    let inst = p.install.as_ref().ok_or("This addon has no install details in the catalog.")?;
    if p.source != "upstream" || p.native || !install_ok(inst, &p.repo, origin, p.mirror_allowed, p.blp == "author-art") {
        return Err("This addon's install details did not check out, so Leyline will not install it.".into());
    }
    if p.review.as_ref().map_or(true, |r| r.by.is_empty()) {
        return Err("This addon has not been reviewed yet.".into());
    }
    Ok(inst)
}

/// Download an upstream addon from its author (or our mirror when allowed) into the launcher's scratch folder,
/// verify it against the reviewed entry, then install it like every mod (key `up:<slug>`).
pub fn install(client: &Path, build: Build, p: &Project, origin: &str, scratch: &Path) -> Result<Installed, String> {
    let inst = checked(p, origin)?.clone();
    if !p.fits(build) {
        return Err(format!("{} is made for the {} client, not this {} one.", p.name, p.builds.join(" / "), build.catalog_tag()));
    }
    let r = rules();
    let dl = mods::Scratch::new(scratch).map_err(|e| format!("could not make a download folder: {e}"))?;
    let zip = dl.dir.join("upstream.zip");
    let max = (inst.size.saturating_mul(2) + 16 * 1_048_576).min(r.caps.download);
    let (_, sha) = download(&inst.url, &zip, max).map_err(|e| format!("Download from the author's site failed: {e}"))?;
    if inst.sha256.as_deref().is_some_and(|want| want != sha) {
        return Err("The download does not match the reviewed file, so it was not installed. Try again later.".into());
    }
    let st = mods::Staging::new(client).map_err(|e| format!("could not make a staging folder in the client: {e}"))?;
    let files = st.files();
    fs::create_dir_all(&files).map_err(|e| e.to_string())?;
    let blp_ok = p.blp == "author-art";
    let u = unpack(&zip, &files, &inst, blp_ok)?;
    verify(&u, &inst)?;
    let mut plan = plan_of(&u, &inst, build);
    if u.skipped > 0 {
        plan.skipped.push(format!("{} file(s) the game does not load (notes, screenshots, dev files)", u.skipped));
    }
    let meta = InstallMeta {
        key: p.id.clone(),
        name: p.name.clone(),
        version: p.version.clone().unwrap_or_else(|| inst.rev.chars().take(7).collect()),
        source: "upstream".into(),
        sha256: inst.rev.clone(),
        category: p.category.clone(),
        credits: p.credits.clone(),
    };
    mods::install(client, build, meta, &plan, false)
}

/// The update an installed upstream addon has: the catalog's version (or short rev) when its rev differs.
pub fn update_for(m: &Installed, p: &Project) -> Option<String> {
    let inst = p.install.as_ref()?;
    (p.source == "upstream" && m.source == "upstream" && !inst.rev.is_empty() && inst.rev != m.sha256)
        .then(|| p.version.clone().filter(|v| !v.is_empty()).unwrap_or_else(|| inst.rev.chars().take(7).collect()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mods::tests::zip_of;
    use crate::net::testserver::*;
    use serde_json::Value;

    const CASES: &str = include_str!("upstream-cases.json");

    #[test]
    fn the_shared_cases_hold() {
        let v: Value = serde_json::from_str(CASES).unwrap();
        for c in v["classify"].as_array().unwrap() {
            let head = c.get("head").and_then(Value::as_str).map(|h| (0..h.len()).step_by(2).map(|i| u8::from_str_radix(&h[i..i + 2], 16).unwrap()).collect::<Vec<u8>>()).unwrap_or_default();
            let got = classify(c["path"].as_str().unwrap(), c["blp_ok"].as_bool().unwrap(), &head);
            assert_eq!(got.split(':').next().unwrap(), c["expect"].as_str().unwrap(), "{c}");
        }
        for c in v["names"].as_array().unwrap() {
            assert_eq!(name_ok(c["name"].as_str().unwrap()), c["ok"].as_bool().unwrap(), "{c}");
        }
        for c in v["interface"].as_array().unwrap() {
            assert_eq!(interface_ok(c["value"].as_str().unwrap()), c["ok"].as_bool().unwrap(), "{c}");
        }
        for c in v["clean_name"].as_array().unwrap() {
            assert_eq!(clean_title(c["raw"].as_str().unwrap()), c["want"].as_str().unwrap(), "{c}");
        }
    }

    #[test]
    fn rules_are_strict_where_they_must_be() {
        let r = rules();
        assert_eq!(r.interface, "30300");
        for e in [".mpq", ".m2", ".dbc", ".wmo", ".adt", ".dll", ".exe", ".asi"] {
            assert!(r.refuse_ext.iter().any(|x| x == e), "{e}");
            assert!(!r.install_ext.iter().any(|x| x == e));
        }
        assert!(!r.install_ext.iter().any(|x| x == ".blp"), ".blp only by the entry's flag");
        assert!(classify("Foo/x.mpq", true, b"").starts_with("refuse"));
        assert!(classify("Foo/x.m2", true, b"").starts_with("refuse"));
        assert!(classify("Foo/x.dll", true, b"").starts_with("refuse"));
    }

    pub fn sha(b: &[u8]) -> String {
        use sha2::{Digest, Sha256};
        net::hex(&Sha256::digest(b))
    }

    const C1: &str = "0123456789abcdef0123456789abcdef01234567";

    fn inst_for(files: &[(&str, &[u8])], folders: &[(&str, &str)], prefix: &str) -> Install {
        let mut m = BTreeMap::new();
        for (p, b) in files {
            m.insert(p.to_string(), sha(b));
        }
        Install {
            from: "commit-archive".into(),
            url: format!("https://github.com/alice/Frames/archive/{C1}.zip"),
            rev: C1.into(),
            size: files.iter().map(|(_, b)| b.len() as u64).sum(),
            file_count: files.len() as u64,
            strip_prefix: prefix.into(),
            folders: folders.iter().map(|(a, b)| (a.to_string(), b.to_string())).collect(),
            files_digest: files_digest(&m),
            files: m,
            ..Default::default()
        }
    }

    #[test]
    fn only_the_entrys_own_repo_in_allowed_shapes() {
        let repo = "https://github.com/alice/Frames";
        let o = "https://play.openvanilla.app";
        let mut i = inst_for(&[("Frames/Frames.toc", b"x")], &[("Frames", "Frames")], "");
        assert!(url_ok(&i, repo, o, false));
        assert!(!url_ok(&i, "https://github.com/mallory/Frames", o, false), "another repo");
        i.url = "https://github.com/alice/Frames/archive/refs/heads/main.zip".into();
        assert!(!url_ok(&i, repo, o, false), "a branch archive is not pinned");
        i.rev = "main".into();
        i.url = "https://github.com/alice/Frames/archive/main.zip".into();
        assert!(!url_ok(&i, repo, o, false), "the rev must be 40 hex");
        i.from = "release-asset".into();
        i.rev = "v1.2".into();
        i.url = "https://github.com/alice/Frames/releases/download/v1.2/Frames.zip".into();
        assert!(url_ok(&i, repo, o, false));
        i.url = "https://github.com/alice/Frames/releases/download/v1.2/../../x/Frames.zip".into();
        assert!(!url_ok(&i, repo, o, false));
        i.url = "https://github.com/alice/Frames/releases/download/v1.2/Frames.exe".into();
        assert!(!url_ok(&i, repo, o, false));
        i.url = "https://evil.example.com/alice/Frames/releases/download/v1.2/Frames.zip".into();
        assert!(!url_ok(&i, repo, o, false));
        i.url = "https://github.com/alice/Frames/releases/download/v1.2/Frames.zip?x=1".into();
        assert!(!url_ok(&i, repo, o, false));
        // GitLab and Codeberg, pinned
        let mut g = inst_for(&[("Frames/Frames.toc", b"x")], &[("Frames", "Frames")], "");
        g.url = format!("https://gitlab.com/alice/Frames/-/archive/{C1}/Frames-{C1}.zip");
        assert!(url_ok(&g, "https://gitlab.com/alice/Frames", o, false));
        g.url = format!("https://codeberg.org/alice/Frames/archive/{C1}.zip");
        assert!(url_ok(&g, "https://codeberg.org/alice/Frames", o, false));
        assert!(!url_ok(&g, "https://gitlab.com/alice/Frames", o, false));
        // A mirror: only when the entry allows it, on our own site, with a sha256
        let mut m = inst_for(&[("Frames/Frames.toc", b"x")], &[("Frames", "Frames")], "");
        m.from = "mirror".into();
        m.url = "https://play.openvanilla.app/wrath/mods/up/frames.zip".into();
        m.sha256 = Some("ab".repeat(32));
        assert!(!url_ok(&m, repo, o, false), "never mirror an entry that does not allow it (no open licence, or .blp)");
        assert!(url_ok(&m, repo, o, true));
        m.sha256 = None;
        assert!(!url_ok(&m, repo, o, true), "a mirror is byte-stable: it needs its sha256");
        m.sha256 = Some("ab".repeat(32));
        m.url = "https://elsewhere.example.com/wrath/mods/up/frames.zip".into();
        assert!(!url_ok(&m, repo, o, true));
    }

    #[test]
    fn redirects_only_to_the_forges_download_hosts() {
        let gh = format!("https://github.com/alice/Frames/archive/{C1}.zip");
        assert!(redirect_ok(&gh, &format!("https://codeload.github.com/alice/Frames/zip/{C1}")));
        assert!(redirect_ok("https://github.com/a/b/releases/download/v1/x.zip", "https://objects.githubusercontent.com/github-production-release-asset/1"));
        assert!(redirect_ok("https://github.com/a/b/releases/download/v1/x.zip", "https://release-assets.githubusercontent.com/x"));
        assert!(!redirect_ok(&gh, "https://evil.example.com/x.zip"));
        assert!(!redirect_ok(&gh, "http://codeload.github.com/alice/Frames/zip/x"), "https only");
        assert!(!redirect_ok(&gh, "https://codeload.github.com.evil.example/x"));
        assert!(!redirect_ok(&gh, "javascript:alert(1)"));
    }

    #[test]
    fn install_blocks_are_checked() {
        let repo = "https://github.com/alice/Frames";
        let o = "https://play.openvanilla.app";
        let ok = inst_for(&[("Frames/Frames.toc", b"x"), ("Frames/a.lua", b"y")], &[("Frames", "Frames")], "Frames-x/");
        assert!(install_ok(&ok, repo, o, false, false));
        let blp = inst_for(&[("Frames/Frames.toc", b"x"), ("Frames/art.blp", b"BLP2")], &[("Frames", "Frames")], "");
        assert!(!install_ok(&blp, repo, o, false, false), ".blp only when the entry says author-art");
        assert!(install_ok(&blp, repo, o, false, true));
        for bad in ["Frames/x.mpq", "Frames/x.m2", "Frames/d3d9.dll", "Other/x.lua", "Frames/../x.lua", "Frames/README.md"] {
            let i = inst_for(&[("Frames/Frames.toc", b"x"), (bad, b"y")], &[("Frames", "Frames")], "");
            assert!(!install_ok(&i, repo, o, true, true), "{bad}");
        }
        let names = inst_for(&[("!Bang/!Bang.toc", b"x"), ("xCT+/xCT+.toc", b"y")], &[("!Bang", "!Bang"), ("xCT+", "xCT+")], "");
        assert!(install_ok(&names, repo, o, false, false), "curated entries may use ! _ + in folder names");
        let reserved = inst_for(&[("Blizzard_X/Blizzard_X.toc", b"x")], &[("Blizzard_X", "Blizzard_X")], "");
        assert!(!install_ok(&reserved, repo, o, false, false));
        let mut digest = ok.clone();
        digest.files.clear();
        assert!(install_ok(&digest, repo, o, false, false), "a digest instead of the list");
        digest.files_digest = "nothex".into();
        assert!(!install_ok(&digest, repo, o, false, false));
    }

    #[test]
    fn folders_map_paths_including_a_repo_that_is_the_addon() {
        let i = inst_for(&[], &[("Skada", "Skada"), ("Libs/Inner", "Inner")], "Skada-WoTLK-abc/");
        assert_eq!(map_path(&i, "Skada-WoTLK-abc/Skada/Core.lua").as_deref(), Some("Skada/Core.lua"));
        assert_eq!(map_path(&i, "Skada-WoTLK-abc/Libs/Inner/x.lua").as_deref(), Some("Inner/x.lua"));
        assert_eq!(map_path(&i, "Skada-WoTLK-abc/README.md"), None);
        assert_eq!(map_path(&i, "Other-abc/Skada/Core.lua"), None, "outside the archive's top folder");
        let root = inst_for(&[], &[("", "Questie-335")], "Questie-abc/");
        assert_eq!(map_path(&root, "Questie-abc/Questie-335.toc").as_deref(), Some("Questie-335/Questie-335.toc"));
        assert_eq!(map_path(&root, "Questie-abc/Database/x.lua").as_deref(), Some("Questie-335/Database/x.lua"));
    }

    fn write(dir: &Path, name: &str, b: &[u8]) -> PathBuf {
        let p = dir.join(name);
        fs::write(&p, b).unwrap();
        p
    }

    const TOC: &[u8] = b"## Interface: 30300, 11508\n## Title: |cff00ff00Frames|r (WotLK)\n## Version: r736\nFrames.lua\n";

    fn archive_entries(extra: &[(&'static str, &'static [u8])]) -> Vec<(&'static str, &'static [u8])> {
        let mut v: Vec<(&str, &[u8])> = vec![
            ("Frames-abc/Frames.toc", TOC),
            ("Frames-abc/Frames.lua", b"print('hi')"),
            ("Frames-abc/Media/art.blp", b"BLP2\x00\x00"),
            ("Frames-abc/.pkgmeta", b"package-as: Frames"),
            ("Frames-abc/.github/workflows/x.yml", b"on: push"),
            ("Frames-abc/LICENSE", b"MIT"),
            ("Frames-abc/README.md", b"# Frames"),
        ];
        v.extend_from_slice(extra);
        v
    }

    fn project(inst: Install, blp: &str) -> Project {
        Project {
            id: "up:frames".into(),
            source: "upstream".into(),
            name: "Frames".into(),
            builds: vec!["3.3.5a".into()],
            repo: "https://github.com/alice/Frames".into(),
            version: Some("r736".into()),
            blp: blp.into(),
            install: Some(inst),
            review: Some(Review { by: "owner".into(), at: "2026-10-31".into(), notes: String::new() }),
            ..Default::default()
        }
    }

    #[test]
    fn unpack_verify_and_install_a_root_is_addon_repo() {
        let d = tempfile::tempdir().unwrap();
        let z = write(d.path(), "a.zip", &zip_of(&archive_entries(&[])));
        let inst = inst_for(
            &[("Frames/Frames.toc", TOC), ("Frames/Frames.lua", b"print('hi')"), ("Frames/Media/art.blp", b"BLP2\x00\x00")],
            &[("", "Frames")],
            "Frames-abc/",
        );
        let out = d.path().join("out");
        let u = unpack(&z, &out, &inst, true).unwrap();
        assert_eq!(u.files.keys().cloned().collect::<Vec<_>>(), ["Frames/Frames.lua", "Frames/Frames.toc", "Frames/Media/art.blp"]);
        assert!(u.skipped >= 4, "dev files are skipped, not errors");
        verify(&u, &inst).unwrap();
        let plan = plan_of(&u, &inst, Build::V335a);
        assert!(plan.errors.is_empty(), "{:?}", plan.errors);
        assert_eq!(plan.addons[0].title.as_deref(), Some("Frames"), "brand words and colours out of the title");
        assert!(!plan_of(&u, &inst, Build::V1121).errors.is_empty());

        // the digest instead of the list selects the same files
        let mut dig = inst.clone();
        dig.files.clear();
        let out2 = d.path().join("out2");
        let u2 = unpack(&z, &out2, &dig, true).unwrap();
        verify(&u2, &dig).unwrap();

        // a changed file, a missing one
        let mut wrong = inst.clone();
        wrong.files.insert("Frames/Frames.lua".into(), sha(b"other"));
        assert!(verify(&u, &wrong).unwrap_err().contains("Frames.lua changed"));
        let mut more = inst.clone();
        more.files.insert("Frames/Gone.lua".into(), sha(b"x"));
        let out3 = d.path().join("out3");
        assert!(verify(&unpack(&z, &out3, &more, true).unwrap(), &more).unwrap_err().contains("missing"));
    }

    #[test]
    fn game_data_and_native_code_anywhere_refuse_the_download() {
        let d = tempfile::tempdir().unwrap();
        let inst = inst_for(&[("Frames/Frames.toc", TOC)], &[("", "Frames")], "Frames-abc/");
        for (i, (name, body)) in [
            ("Frames-abc/Data/patch-4.MPQ", &b"MPQ\x1a...."[..]),
            ("Frames-abc/Models/x.m2", b"MD20"),
            ("Frames-abc/tools/inject.dll", b"MZ\x90\x00"),
            ("Frames-abc/renamed.lua", b"MZ\x90\x00"),
            ("Frames-abc/Media/sneaky.tga", b"BLP2\x00"),
        ]
        .into_iter()
        .enumerate()
        {
            let z = write(d.path(), &format!("{i}.zip"), &zip_of(&archive_entries(&[(name, body)])));
            let e = unpack(&z, &d.path().join(format!("o{i}")), &inst, true).unwrap_err();
            assert!(e.contains("will not install"), "{name}: {e}");
        }
        // .blp not installed when the entry does not allow it (digest mode picks by the rules)
        let mut dig = inst.clone();
        dig.files.clear();
        let z = write(d.path(), "b.zip", &zip_of(&archive_entries(&[])));
        let u = unpack(&z, &d.path().join("ob"), &dig, false).unwrap();
        assert!(!u.files.keys().any(|k| k.ends_with(".blp")));
    }

    #[test]
    fn installs_from_upstream_through_redirects_and_tracks_updates() {
        let d = tempfile::tempdir().unwrap();
        let client = d.path().join("client");
        fs::create_dir_all(client.join("Data")).unwrap();
        fs::create_dir_all(client.join("Interface/AddOns")).unwrap();
        let zip = zip_of(&archive_entries(&[]));
        let base = serve_routes(vec![("/real.zip", "200 OK", zip.clone())]);
        // A local "forge" answering with a redirect, as GitHub does to codeload.
        let redir = {
            use std::net::TcpListener;
            let l = TcpListener::bind("127.0.0.1:0").unwrap();
            let port = l.local_addr().unwrap().port();
            let to = format!("{base}/real.zip");
            std::thread::spawn(move || {
                for s in l.incoming().flatten() {
                    let mut s = s;
                    let mut buf = [0u8; 2048];
                    let _ = s.read(&mut buf);
                    let _ = write!(s, "HTTP/1.1 302 Found\r\nLocation: {to}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
                }
            });
            format!("http://127.0.0.1:{port}/a.zip")
        };
        let dest = d.path().join("dl.zip");
        let (_, got) = download(&redir, &dest, 1 << 20).unwrap();
        assert_eq!(got, sha(&zip));

        let mut inst = inst_for(
            &[("Frames/Frames.toc", TOC), ("Frames/Frames.lua", b"print('hi')"), ("Frames/Media/art.blp", b"BLP2\x00\x00")],
            &[("", "Frames")],
            "Frames-abc/",
        );
        inst.from = "mirror".into();
        inst.sha256 = Some(sha(&zip));
        let site = serve_routes(vec![("/wrath/mods/up/frames.zip", "200 OK", zip.clone())]);
        inst.url = format!("{site}/wrath/mods/up/frames.zip");
        let mut p = project(inst.clone(), "author-art");
        p.mirror_allowed = true;
        let scratch = d.path().join("scratch");
        let m = install(&client, Build::V335a, &p, &site, &scratch).unwrap();
        assert_eq!(m.key, "up:frames");
        assert_eq!(m.source, "upstream");
        assert_eq!(m.sha256, C1, "the rev is what updates compare");
        assert!(client.join("Interface/AddOns/Frames/Media/art.blp").exists());
        assert!(!client.join("Interface/AddOns/Frames/README.md").exists());
        assert!(update_for(&m, &p).is_none());
        let mut newer = p.clone();
        newer.install.as_mut().unwrap().rev = "1111111111111111111111111111111111111111".into();
        newer.version = Some("r737".into());
        assert_eq!(update_for(&m, &newer).as_deref(), Some("r737"));
        // My Mods: the update by rev (not by version number), and the name as the catalog cleaned it.
        let view = mods::with_updates(&mods::load(&client), &[newer.clone()], Build::V335a);
        assert_eq!(view[0].update.as_deref(), Some("r737"));
        assert!(mods::with_updates(&mods::load(&client), &[p.clone()], Build::V335a)[0].update.is_none());
        // The Workshop's install command reaches here through mods::install_project.
        let again = mods::install_project(&client, Build::V335a, &p, &site, &scratch, &|_| false).unwrap();
        assert_eq!(again.key, "up:frames");

        // never mirrored without mirror_allowed; never unreviewed; never with .blp when not flagged
        let mut no_mirror = p.clone();
        no_mirror.mirror_allowed = false;
        assert!(install(&client, Build::V335a, &no_mirror, &site, &scratch).is_err());
        let mut unreviewed = p.clone();
        unreviewed.review = None;
        assert!(install(&client, Build::V335a, &unreviewed, &site, &scratch).unwrap_err().contains("reviewed"));
        let no_blp = Project { blp: "none".into(), ..p.clone() };
        assert!(install(&client, Build::V335a, &no_blp, &site, &scratch).is_err());
        // Remove takes out exactly what was put in.
        mods::uninstall(&client, "up:frames").unwrap();
        assert!(!client.join("Interface/AddOns/Frames").exists());
    }

    /// A real curated entry against a real archive (curate.py's): the launcher picks the same files and gets the same
    /// digest. `UPSTREAM_ZIP=<zip> UPSTREAM_ENTRY=<entry json> cargo test --no-default-features --lib real_archive -- --ignored`
    #[test]
    #[ignore]
    fn real_archive_matches_curation() {
        let zip = PathBuf::from(std::env::var("UPSTREAM_ZIP").unwrap());
        let e: Value = serde_json::from_str(&fs::read_to_string(std::env::var("UPSTREAM_ENTRY").unwrap()).unwrap()).unwrap();
        let mut inst: Install = serde_json::from_value(e["install"].clone()).unwrap();
        let blp_ok = e["blp"] == "author-art";
        let d = tempfile::tempdir().unwrap();
        let listed = inst.files.clone();
        inst.files.clear();
        let u = unpack(&zip, &d.path().join("a"), &inst, blp_ok).unwrap();
        assert_eq!(u.files.keys().cloned().collect::<Vec<_>>(), listed.keys().cloned().collect::<Vec<_>>(), "the same files");
        verify(&u, &inst).unwrap();
        inst.files = listed;
        let u = unpack(&zip, &d.path().join("b"), &inst, blp_ok).unwrap();
        verify(&u, &inst).unwrap();
        let plan = plan_of(&u, &inst, Build::V335a);
        assert!(plan.errors.is_empty(), "{:?}", plan.errors);
    }

    #[test]
    fn tidies_titles() {
        assert_eq!(clean_title("|cff33ff99Grid2|r"), "Grid2");
        assert_eq!(clean_title("RUF [Raeli's Unit Frames]"), "RUF [Raeli's Unit Frames]");
        assert_eq!(clean_title("Skada (WoTLK)"), "Skada");
        assert_eq!(clean_title("WOW Tools"), "Tools");
        assert_eq!(clean_title("Wowhead Links"), "Wowhead Links");
        assert_eq!(clean_title("Skada - Damage"), "Skada Damage");
    }
}
