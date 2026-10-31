//! The mod manager: install, turn on and off, update and remove mods in one client folder.
//!
//! What goes where:
//! * UI addons go to `Interface/AddOns/<Name>/`. They are checked with the UI rules of `mods/wu-mod.py` and
//!   the site's `wu-addons-core.js`: a `<Name>/<Name>.toc` with the client's `## Interface:` number, every
//!   file the TOC lists present, `<Script file>`/`<Include file>` pointing at real files, addon file types
//!   only, no game data (by extension or by the file's first bytes), 10 MB a file, 50 MB, 2000 files.
//! * Client patches (`.MPQ`, such as the all-races patch `Patch-A.MPQ`) go to a free `Data/patch-<X>.MPQ`
//!   slot. The mod format forbids archives inside a mod package, so a patch is only taken from a plain drop
//!   (the .MPQ itself, or a zip of it), never from a package with a `mod.json`.
//! * The realm half of a mod package (`realm/`) is not for a client: it is skipped, with a note.
//!
//! Every install is staged first in `<client>/Leyline/staging/` (extracted with zip-slip, symlink, password
//! and size checks), validated there, and only then moved into place. Nothing is ever written outside the
//! client folder, and no path inside it may run through a symbolic link. Each client keeps a manifest,
//! `<client>/Leyline/mods.json`, of every file Leyline put there, so removing a mod removes exactly those
//! files, and the last removal takes the `Leyline/` folder (and any folder Leyline made) away too.
//! A turned-off mod's files wait in `<client>/Leyline/disabled/`, where the game does not look.
//!
//! The owner's decision for now: every mod is allowed (no review queue, no signing). These checks are about
//! the install being sound and contained, not about vetting the mod.

use crate::catalog::Project;
use crate::clients::{find_ci, Build};
use crate::net;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::fs;
use std::io::{self, Read};
use std::path::{Component, Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const MIB: u64 = 1024 * 1024;
/// wu-mod.py MAX_FILE_BYTES, MAX_PACKAGE_BYTES, MAX_FILES (and wu-addons-core.js LIMITS).
pub const MAX_FILE: u64 = 10 * MIB;
pub const MAX_PACKAGE: u64 = 50 * MIB;
pub const MAX_FILES: usize = 2000;
/// The Workshop's own cap on a mod zip (stream/workshop.py MAX_ZIP).
pub const MAX_DOWNLOAD: u64 = 60 * MIB;
/// One client patch.
pub const MAX_PATCH: u64 = 1024 * MIB;
/// A dropped zip: the addon cap plus room for patches.
pub const MAX_LOCAL_ZIP: u64 = MAX_PATCH + MAX_PACKAGE;

/// Leyline's own folder inside a client: the manifest, staging and turned-off mods.
pub const DIR: &str = "Leyline";
pub const MANIFEST: &str = "mods.json";
pub const SCHEMA: u32 = 1;

const BLOCKED_EXT: &[(&str, &str)] = &[
    (".mpq", "an archive of game data"),
    (".blp", "a game texture"),
    (".m2", "a game model"),
    (".wmo", "a game world model"),
    (".adt", "a game terrain tile"),
    (".dbc", "a game database"),
    (".skin", "a game model skin"),
    (".anim", "a game animation"),
    (".wdt", "a game map file"),
    (".wdl", "a game map file"),
    (".db2", "a game database"),
    (".bls", "a game shader"),
];
const BLOCKED_MAGIC: &[(&[u8; 4], &str)] = &[
    (b"MPQ\x1a", "an archive of game data"),
    (b"MPQ\x1b", "an archive of game data"),
    (b"BLP1", "a game texture"),
    (b"BLP2", "a game texture"),
    (b"MD20", "a game model"),
    (b"MD21", "a game model"),
    (b"WDBC", "a game database"),
    (b"REVM", "a game map file"),
];
const ALLOWED_EXT: &[&str] = &[".toc", ".lua", ".xml", ".tga", ".ttf", ".ogg", ".mp3", ".wav", ".txt", ".md", ".toml"];
/// Folder names the realm ships itself (wu-mod.py RESERVED_ADDONS).
const RESERVED: &[&str] = &["foreverui", "wrathunleashedui", "wumodcatalog"];
const IGNORED: &[&str] = &[".git", "__pycache__", ".ds_store", "thumbs.db", "desktop.ini", ".gitignore", "__macosx"];
/// A mod package's top level (wu-mod.py TOP_LEVEL_OK): only ui/ goes into a client.
const PACKAGE_TOP: &[&str] =
    &["mod.json", "ui", "realm", "native", "assets", "tests", "readme.md", "readme.txt", "license", "license.txt", "license.md", "changelog.md"];
/// Data/ slots for patches, in the order they are handed out. patch.MPQ, patch-2 and patch-3 are the game's own.
const PATCH_SLOTS: &str = "456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
/// Native code: a mod with any of these needs the player's one-time OK (owner decision: allowed, with a notice).
pub const NATIVE_CODE_EXT: &[&str] = &[".dll", ".asi", ".exe"];
/// What may sit next to native code in the client folder: the code and its own settings and notes.
const NATIVE_EXT: &[&str] = &[".dll", ".asi", ".exe", ".ini", ".conf", ".cfg", ".json", ".toml", ".txt", ".md"];
/// Client folders native files may never go into: the game's data, the UI, saved settings, Leyline's own.
const NATIVE_FORBIDDEN_TOP: &[&str] = &["data", "interface", "wtf", "leyline", "cache", "errors", "logs", "screenshots"];
/// The error an install returns when it has native code the player has not OK'd yet: this prefix, then JSON
/// `{"key", "name", "files"}`. The UI shows the notice, stores the OK (`mod_native_confirm`) and tries again.
pub const NATIVE_CONFIRM: &str = "NATIVE_CONFIRM:";
const WINDOWS_DEVICES: &[&str] = &[
    "con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9", "lpt1", "lpt2",
    "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
];

// ------------------------------------------------------------------------------------------------ names

fn ext(p: &str) -> String {
    let base = p.rsplit('/').next().unwrap_or(p);
    match base.rfind('.') {
        Some(i) if i > 0 => base[i..].to_ascii_lowercase(),
        _ => String::new(),
    }
}

fn ignored(part: &str) -> bool {
    IGNORED.contains(&part.to_ascii_lowercase().as_str())
}

fn is_note(name: &str) -> bool {
    let l = name.to_ascii_lowercase();
    let stem = l.strip_suffix(".md").or_else(|| l.strip_suffix(".txt")).unwrap_or(&l);
    matches!(stem, "readme" | "license" | "licence" | "changelog" | "credits")
}

/// An addon folder name: letters, digits, `_ . -`, starting with a letter, at most 64.
pub fn addon_name_ok(n: &str) -> bool {
    !n.is_empty()
        && n.len() <= 64
        && n.starts_with(|c: char| c.is_ascii_alphabetic())
        && n.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | '-'))
}

/// A zip entry's name made safe and `/`-separated, or None for a folder entry. Refuses absolute paths, drive
/// letters, `..`, empty parts, control and reserved characters, and names Windows cannot hold (zip-slip).
pub fn safe_rel(raw: &str) -> Result<Option<String>, String> {
    let p = raw.replace('\\', "/");
    let bad = || Err(format!("unsafe path in the zip: {p}"));
    if p.starts_with('/') || p.as_bytes().get(1) == Some(&b':') {
        return bad();
    }
    if p.ends_with('/') {
        return Ok(None);
    }
    for part in p.split('/') {
        let stem = part.split('.').next().unwrap_or("").to_ascii_lowercase();
        if part.is_empty()
            || part == "."
            || part == ".."
            || part.ends_with('.')
            || part.ends_with(' ')
            || part.len() > 128
            || part.chars().any(|c| c.is_control() || matches!(c, ':' | '*' | '?' | '"' | '<' | '>' | '|'))
            || WINDOWS_DEVICES.contains(&stem.as_str())
        {
            return bad();
        }
    }
    if p.len() > 400 || p.split('/').count() > 16 {
        return bad();
    }
    Ok(Some(p))
}

fn now() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn fmt_size(n: u64) -> String {
    if n < 1024 {
        format!("{n} B")
    } else if n < MIB {
        format!("{} KB", n.div_ceil(1024))
    } else {
        format!("{:.1} MB", n as f64 / MIB as f64)
    }
}

// ------------------------------------------------------------------------------------------------ staging

/// A scratch folder inside the client (so the final move is a rename), removed when dropped.
pub struct Staging {
    pub dir: PathBuf,
}

impl Staging {
    pub fn new(client: &Path) -> io::Result<Staging> {
        let base = client.join(DIR).join("staging");
        fs::create_dir_all(&base)?;
        let nanos = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
        let dir = base.join(format!("{}-{nanos}", std::process::id()));
        fs::create_dir(&dir)?;
        Ok(Staging { dir })
    }
    /// Where unpacked files go (a sibling of any downloaded zip).
    pub fn files(&self) -> PathBuf {
        self.dir.join("files")
    }
}

impl Drop for Staging {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.dir);
        // The staging folder, then Leyline/ itself, but only when they are empty.
        if let Some(base) = self.dir.parent() {
            let _ = fs::remove_dir(base);
            if let Some(ly) = base.parent() {
                let _ = fs::remove_dir(ly);
            }
        }
    }
}

fn cap_for(rel: &str) -> u64 {
    if ext(rel) == ".mpq" {
        MAX_PATCH
    } else {
        MAX_FILE
    }
}

/// Unpack `zip` into `dest` (a fresh folder), with every check the site's reader makes: zip-slip, symlinks,
/// passwords, packing methods, a file count, per-file and total sizes, and two names that only differ in case.
pub fn extract_zip(zip: &Path, dest: &Path, max_zip: u64) -> Result<(), String> {
    let size = fs::metadata(zip).map_err(|e| format!("could not read the zip: {e}"))?.len();
    if size > max_zip {
        return Err(format!("the zip is larger than {}", fmt_size(max_zip)));
    }
    let f = fs::File::open(zip).map_err(|e| format!("could not read the zip: {e}"))?;
    let mut ar = zip::ZipArchive::new(io::BufReader::new(f)).map_err(|_| "this is not a zip file (or it is damaged)".to_string())?;
    if ar.len() > MAX_FILES + 50 {
        return Err(format!("the zip has more than {MAX_FILES} files"));
    }
    let mut seen = HashSet::new();
    let (mut addon_total, mut patch_total, mut count) = (0u64, 0u64, 0usize);
    for i in 0..ar.len() {
        let mut file = match ar.by_index(i) {
            Ok(f) => f,
            Err(zip::result::ZipError::UnsupportedArchive(m)) if m.to_ascii_lowercase().contains("password") => {
                return Err("the zip is password protected".into())
            }
            Err(e) => return Err(format!("the zip is damaged or uses a packing method Leyline cannot read ({e})")),
        };
        let raw = String::from_utf8_lossy(file.name_raw()).to_string();
        let Some(rel) = safe_rel(&raw)? else { continue };
        if rel.split('/').any(ignored) {
            continue;
        }
        if file.is_dir() {
            continue;
        }
        if file.encrypted() {
            return Err(format!("the zip is password protected: {rel}"));
        }
        if let Some(mode) = file.unix_mode() {
            if mode & 0o170000 == 0o120000 {
                return Err(format!("symbolic links are not allowed: {rel}"));
            }
        }
        if !matches!(file.compression(), zip::CompressionMethod::Stored | zip::CompressionMethod::Deflated) {
            return Err(format!("{rel} uses a packing method Leyline cannot read: repack it as a normal zip"));
        }
        if !seen.insert(rel.to_ascii_lowercase()) {
            return Err(format!("the zip has two files named {rel} (they differ only in upper and lower case)"));
        }
        count += 1;
        if count > MAX_FILES {
            return Err(format!("the zip has more than {MAX_FILES} files"));
        }
        let cap = cap_for(&rel);
        if file.size() > cap {
            return Err(format!("{rel} is larger than {}", fmt_size(cap)));
        }
        let total = if cap == MAX_PATCH { &mut patch_total } else { &mut addon_total };
        *total += file.size();
        if addon_total > MAX_PACKAGE {
            return Err(format!("the zip unpacks to more than {}", fmt_size(MAX_PACKAGE)));
        }
        if patch_total > MAX_PATCH * 2 {
            return Err(format!("the patches in the zip come to more than {}", fmt_size(MAX_PATCH * 2)));
        }
        let out = dest.join(&rel);
        if let Some(d) = out.parent() {
            fs::create_dir_all(d).map_err(|e| e.to_string())?;
        }
        let mut w = fs::File::create(&out).map_err(|e| e.to_string())?;
        // The zip reader checks each file's CRC when it reaches the end; a file that unpacks bigger than it
        // said is cut at the cap and refused.
        let n = io::copy(&mut (&mut file).take(cap + 1), &mut w).map_err(|_| format!("the zip is damaged: {rel} does not unpack"))?;
        if n > cap {
            return Err(format!("{rel} unpacks bigger than it says"));
        }
    }
    Ok(())
}

/// Copy a dropped folder into `dest`, keeping the folder's own name as the first part (as a zip of it would).
/// Symbolic links are refused; the same caps as a zip apply.
pub fn copy_folder(src: &Path, dest: &Path) -> Result<(), String> {
    let name = src.file_name().map(|n| n.to_string_lossy().to_string()).ok_or("that folder has no name")?;
    let mut count = 0usize;
    let mut total = 0u64;
    let mut stack = vec![(src.to_path_buf(), name)];
    while let Some((dir, rel)) = stack.pop() {
        let mut items: Vec<_> = fs::read_dir(&dir).map_err(|e| format!("could not read {rel}: {e}"))?.flatten().collect();
        items.sort_by_key(|e| e.file_name());
        for e in items {
            let n = e.file_name().to_string_lossy().to_string();
            if ignored(&n) {
                continue;
            }
            let r = format!("{rel}/{n}");
            let r = safe_rel(&r)?.ok_or("bad name")?;
            let md = fs::symlink_metadata(e.path()).map_err(|e| e.to_string())?;
            if md.file_type().is_symlink() {
                return Err(format!("symbolic links are not allowed: {r}"));
            }
            if md.is_dir() {
                stack.push((e.path(), r));
                continue;
            }
            count += 1;
            if count > MAX_FILES {
                return Err(format!("it has more than {MAX_FILES} files"));
            }
            let cap = cap_for(&r);
            if md.len() > cap {
                return Err(format!("{r} is larger than {}", fmt_size(cap)));
            }
            if cap == MAX_FILE {
                total += md.len();
                if total > MAX_PACKAGE {
                    return Err(format!("it is larger than {}", fmt_size(MAX_PACKAGE)));
                }
            }
            let out = dest.join(&r);
            fs::create_dir_all(out.parent().unwrap()).map_err(|e| e.to_string())?;
            fs::copy(e.path(), &out).map_err(|e| format!("could not copy {r}: {e}"))?;
        }
    }
    Ok(())
}

/// One staged file: its `/`-separated path under the staging folder, where it is, how big.
#[derive(Debug, Clone)]
pub struct Staged {
    pub rel: String,
    pub abs: PathBuf,
    pub size: u64,
}

/// Every file under `root`, sorted.
pub fn walk(root: &Path) -> io::Result<Vec<Staged>> {
    let mut out = Vec::new();
    let mut stack = vec![(root.to_path_buf(), String::new())];
    while let Some((dir, rel)) = stack.pop() {
        for e in fs::read_dir(&dir)?.flatten() {
            let n = e.file_name().to_string_lossy().to_string();
            let r = if rel.is_empty() { n } else { format!("{rel}/{n}") };
            let md = fs::symlink_metadata(e.path())?;
            if md.file_type().is_symlink() {
                continue;
            }
            if md.is_dir() {
                stack.push((e.path(), r));
            } else {
                out.push(Staged { rel: r, abs: e.path(), size: md.len() });
            }
        }
    }
    out.sort_by(|a, b| a.rel.cmp(&b.rel));
    Ok(out)
}

fn head4(p: &Path) -> [u8; 4] {
    let mut b = [0u8; 4];
    if let Ok(mut f) = fs::File::open(p) {
        let _ = f.read(&mut b);
    }
    b
}

fn read_text(p: &Path, max: u64) -> String {
    let mut s = Vec::new();
    if let Ok(f) = fs::File::open(p) {
        let _ = f.take(max).read_to_end(&mut s);
    }
    String::from_utf8_lossy(&s).to_string()
}

fn read_bytes(p: &Path, max: u64) -> Vec<u8> {
    let mut s = Vec::new();
    if let Ok(f) = fs::File::open(p) {
        let _ = f.take(max).read_to_end(&mut s);
    }
    s
}

// ------------------------------------------------------------------------------------------------ secrets

/// File names that hold secrets (or the player's game account) and never belong in a mod.
fn secret_name(rel: &str) -> Option<&'static str> {
    let low = rel.to_ascii_lowercase();
    let base = low.rsplit('/').next().unwrap_or(&low);
    let parts: Vec<&str> = low.split('/').collect();
    if base == ".env" || base.starts_with(".env.") {
        return Some("an environment file with keys");
    }
    if matches!(base, "id_rsa" | "id_dsa" | "id_ecdsa" | "id_ed25519") {
        return Some("a private SSH key");
    }
    if matches!(base, ".npmrc" | ".netrc" | ".pypirc" | ".git-credentials" | "credentials" | "credentials.json") {
        return Some("a credentials file");
    }
    if [".pem", ".key", ".pfx", ".p12", ".keystore", ".jks", ".kdbx", ".ppk"].contains(&ext(base).as_str()) {
        return Some("a key or certificate store");
    }
    if base == "config.wtf" || parts.windows(2).any(|w| w[0] == "wtf" && w[1] == "account") {
        return Some("the game's saved account settings");
    }
    None
}

fn run_len(b: &[u8], ok: impl Fn(u8) -> bool) -> usize {
    b.iter().take_while(|c| ok(**c)).count()
}

/// A secret inside a file's bytes: private keys, API tokens, webhook addresses. Plain byte scans (no regex),
/// tuned so ordinary addon code does not trip them.
pub fn secret_in(bytes: &[u8]) -> Option<&'static str> {
    let alnum = |c: u8| c.is_ascii_alphanumeric();
    let tok = |c: u8| c.is_ascii_alphanumeric() || c == b'_' || c == b'-';
    let find = |needle: &[u8], from: usize| bytes[from..].windows(needle.len()).position(|w| w == needle).map(|i| from + i);
    let every = |needle: &'static [u8]| {
        let mut at = 0;
        let mut out = Vec::new();
        while let Some(i) = find(needle, at) {
            out.push(i + needle.len());
            at = i + 1;
            if at + needle.len() > bytes.len() {
                break;
            }
        }
        out
    };
    if bytes.len() < 8 {
        return None;
    }
    for i in every(b"-----BEGIN ") {
        let line = &bytes[i..bytes.len().min(i + 40)];
        if line.windows(11).any(|w| w == b"PRIVATE KEY") {
            return Some("a private key");
        }
    }
    for i in every(b"AKIA") {
        if run_len(&bytes[i..], |c| c.is_ascii_uppercase() || c.is_ascii_digit()) >= 16 {
            return Some("a cloud access key");
        }
    }
    for p in [&b"ghp_"[..], b"gho_", b"ghu_", b"ghs_", b"ghr_"] {
        for i in every(p) {
            if run_len(&bytes[i..], alnum) >= 36 {
                return Some("a GitHub token");
            }
        }
    }
    for i in every(b"github_pat_") {
        if run_len(&bytes[i..], tok) >= 22 {
            return Some("a GitHub token");
        }
    }
    for p in [&b"xoxb-"[..], b"xoxp-", b"xoxa-", b"xoxr-", b"xoxs-"] {
        for i in every(p) {
            if run_len(&bytes[i..], tok) >= 10 {
                return Some("a chat bot token");
            }
        }
    }
    for i in every(b"sk-") {
        if run_len(&bytes[i..], tok) >= 32 {
            return Some("an API key");
        }
    }
    for i in every(b"AIza") {
        if run_len(&bytes[i..], tok) >= 35 {
            return Some("an API key");
        }
    }
    for p in [&b"discord.com/api/webhooks/"[..], b"discordapp.com/api/webhooks/"] {
        if !every(p).is_empty() {
            return Some("a chat webhook address");
        }
    }
    None
}

/// File types not worth scanning for text secrets (media; game archives are refused anyway).
fn binary_media(rel: &str) -> bool {
    matches!(ext(rel).as_str(), ".tga" | ".ogg" | ".mp3" | ".wav" | ".ttf" | ".png" | ".jpg" | ".jpeg" | ".webp" | ".mpq")
}

// ------------------------------------------------------------------------------------------------ the rules

/// What a mod package's mod.json says (only what the launcher shows; wu-mod.py checks the rest).
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ModMeta {
    pub id: String,
    pub name: String,
    pub version: String,
    pub author: String,
    pub licence: String,
    pub kind: String,
}

#[derive(Debug, Clone)]
pub struct AddonPlan {
    pub name: String,
    /// (path inside the addon folder, staged file).
    pub files: Vec<(String, PathBuf)>,
    pub size: u64,
    pub title: Option<String>,
    pub version: Option<String>,
}

/// A native file (code or its settings) for the client folder itself, such as `d3d9.dll` or `scripts/x.asi`.
#[derive(Debug, Clone)]
pub struct NativePlan {
    /// Client-relative, `/`-separated.
    pub rel: String,
    pub abs: PathBuf,
    pub size: u64,
}

#[derive(Debug, Clone)]
pub struct PatchPlan {
    pub file_name: String,
    pub abs: PathBuf,
    pub size: u64,
}

/// What a staged drop or package holds, and every reason to refuse it. Install only when `errors` is empty.
#[derive(Debug, Clone, Default)]
pub struct Plan {
    pub meta: Option<ModMeta>,
    pub addons: Vec<AddonPlan>,
    pub patches: Vec<PatchPlan>,
    pub natives: Vec<NativePlan>,
    pub errors: Vec<String>,
    pub warnings: Vec<String>,
    pub skipped: Vec<String>,
}

fn parse_toc(text: &str) -> (HashMap<String, String>, Vec<String>) {
    let mut meta = HashMap::new();
    let mut files = Vec::new();
    for line in text.lines() {
        let s = line.trim().trim_start_matches('\u{feff}');
        if let Some(rest) = s.strip_prefix("##") {
            if let Some((k, v)) = rest.split_once(':') {
                meta.insert(k.trim().to_string(), v.trim().to_string());
            }
        } else if !s.is_empty() && !s.starts_with('#') {
            files.push(s.replace('\\', "/"));
        }
    }
    (meta, files)
}

fn norm_join(base: &str, rel: &str) -> Option<String> {
    let mut out: Vec<&str> = if base.is_empty() { vec![] } else { base.split('/').collect() };
    let rel = rel.replace('\\', "/");
    for part in rel.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                out.pop()?;
            }
            p => out.push(p),
        }
    }
    Some(out.join("/"))
}

/// The `file="..."` of every `<Script>` and `<Include>` tag in an XML file.
fn xml_refs(text: &str) -> Vec<(String, String)> {
    let mut out = Vec::new();
    for tag in ["Script", "Include"] {
        let open = format!("<{tag}");
        let mut at = 0;
        while let Some(i) = text[at..].find(&open) {
            let start = at + i + open.len();
            at = start;
            if !text[start..].starts_with(|c: char| c.is_whitespace() || c == '/' || c == '>') {
                continue;
            }
            let end = text[start..].find('>').map(|j| start + j).unwrap_or(text.len());
            let attrs = &text[start..end];
            let mut k = 0;
            while let Some(j) = attrs[k..].find("file") {
                let p = k + j;
                k = p + 4;
                if p > 0 && !attrs[..p].ends_with(|c: char| c.is_whitespace()) {
                    continue;
                }
                let rest = attrs[p + 4..].trim_start();
                let Some(rest) = rest.strip_prefix('=') else { continue };
                let rest = rest.trim_start();
                let Some(q) = rest.chars().next().filter(|c| *c == '"' || *c == '\'') else { continue };
                if let Some(e) = rest[1..].find(q) {
                    out.push((tag.to_string(), rest[1..1 + e].to_string()));
                }
                break;
            }
        }
    }
    out
}

fn strip_colors(s: &str) -> String {
    // |cAARRGGBB ... |r
    let mut out = String::new();
    let mut it = s.chars().peekable();
    while let Some(c) = it.next() {
        if c == '|' {
            match it.peek() {
                Some('c') | Some('C') => {
                    it.next();
                    for _ in 0..8 {
                        it.next();
                    }
                    continue;
                }
                Some('r') | Some('R') => {
                    it.next();
                    continue;
                }
                _ => {}
            }
        }
        out.push(c);
    }
    out.trim().chars().take(64).collect()
}

fn check_addon(a: &mut AddonPlan, build: Build, warnings: &mut Vec<String>, blocked: &HashSet<PathBuf>, ours: bool) -> Vec<String> {
    let mut errors = Vec::new();
    let at = |p: &str| format!("{}/{p}", a.name);
    if !addon_name_ok(&a.name) {
        errors.push(format!("{}: an addon folder name is letters, digits, _ . and -, starting with a letter", a.name));
        return errors;
    }
    let low = a.name.to_ascii_lowercase();
    // `ours`: Leyline's own addon pack (addons.rs), which ships the realm's own WrathUnleashedUI / WUModCatalog.
    if (!ours && RESERVED.contains(&low.as_str())) || low.starts_with("blizzard_") {
        errors.push(format!("{}: this name is reserved for the game's or the realm's own interface", a.name));
        return errors;
    }
    for (p, abs) in &a.files {
        if blocked.contains(abs) {
            continue; // already refused as game data or a secret
        }
        let e = ext(p);
        if let Some((_, what)) = BLOCKED_EXT.iter().find(|(x, _)| *x == e) {
            errors.push(format!("{} is {what}: game data cannot be in an addon", at(p)));
            continue;
        }
        let h = head4(abs);
        if let Some((_, what)) = BLOCKED_MAGIC.iter().find(|(m, _)| **m == h) {
            errors.push(format!("{} is {what} (renamed): game data cannot be in an addon", at(p)));
            continue;
        }
        if !ALLOWED_EXT.contains(&e.as_str()) {
            let shown = if e.is_empty() { "files without an extension".to_string() } else { e.clone() };
            errors.push(format!("{}: {shown} is not an addon file type (allowed: {})", at(p), ALLOWED_EXT.join(" ")));
            continue;
        }
        let size = fs::metadata(abs).map(|m| m.len()).unwrap_or(0);
        if size > MAX_FILE {
            errors.push(format!("{} is larger than {}", at(p), fmt_size(MAX_FILE)));
        }
    }
    let have: HashMap<&str, &PathBuf> = a.files.iter().map(|(p, abs)| (p.as_str(), abs)).collect();
    let lower: HashMap<String, &str> = a.files.iter().map(|(p, _)| (p.to_ascii_lowercase(), p.as_str())).collect();
    let toc_name = format!("{low}.toc");
    let Some(toc) = lower.get(&toc_name).copied() else {
        errors.push(format!("{}: no {}.toc in the folder (the .toc has the same name as its folder)", a.name, a.name));
        return errors;
    };
    let (meta, listed) = parse_toc(&read_text(have[toc], 1024 * 1024));
    let want = build.interface();
    if want.is_empty() {
        errors.push(format!("{}: Leyline does not know the addon number of this client build, so it installs no addons here", a.name));
        return errors;
    }
    match meta.get("Interface").map(String::as_str) {
        Some(v) if v == want => {}
        got => {
            let hint = match got.and_then(Build::from_interface) {
                Some(b) => format!(": it is made for {} (the {} client)", b.interface(), b.catalog_tag()),
                None => String::new(),
            };
            errors.push(format!(
                "{}: ## Interface must be {want} for this {} client (got {}){hint}",
                at(toc),
                build.catalog_tag(),
                got.unwrap_or("none")
            ));
        }
    }
    match meta.get("Title") {
        Some(t) if !t.is_empty() => a.title = Some(strip_colors(t)),
        _ => warnings.push(format!("{}: no ## Title line", at(toc))),
    }
    a.version = meta.get("Version").map(|v| v.chars().take(40).collect());
    for item in &listed {
        if !have.contains_key(item.as_str()) {
            let hint = lower.get(&item.to_ascii_lowercase()).map(|p| format!(" (the case differs: {p})")).unwrap_or_default();
            errors.push(format!("{} lists {item}, which is not in the folder{hint}", at(toc)));
        }
    }
    for (p, abs) in &a.files {
        if ext(p) != ".xml" {
            continue;
        }
        let text = read_text(abs, MAX_FILE);
        let base = p.rsplit_once('/').map(|(b, _)| b).unwrap_or("");
        for (tag, file) in xml_refs(&text) {
            match norm_join(base, &file) {
                Some(r) if have.contains_key(r.as_str()) => {}
                _ => errors.push(format!("{}: <{tag} file=\"{file}\"> points to a file that is not in the folder", at(p))),
            }
        }
    }
    errors
}

#[derive(Debug, PartialEq)]
enum Layout {
    /// A mod package: mod.json at `root`, addons under `root`ui/.
    Package(String),
    /// An Interface/AddOns/<Name>/ tree under `root`.
    Tree(String),
    /// <Name>/<Name>.toc folders under `root`.
    Folders(String),
    /// One addon's own files at the top: <Name>.toc.
    Single(String),
}

fn locate(paths: &[String]) -> Option<Layout> {
    let low: Vec<String> = paths.iter().map(|p| p.to_ascii_lowercase()).collect();
    if let Some(pkg) = low.iter().find(|p| *p == "mod.json" || (p.ends_with("/mod.json") && p.matches('/').count() == 1)) {
        return Some(Layout::Package(pkg[..pkg.len() - "mod.json".len()].to_string()));
    }
    let tops: BTreeSet<&str> = low.iter().map(|p| p.split('/').next().unwrap_or("")).collect();
    let wrap = if tops.len() == 1 && low.iter().all(|p| p.contains('/')) { format!("{}/", tops.iter().next().unwrap()) } else { String::new() };
    let roots: Vec<String> = if wrap.is_empty() { vec![String::new()] } else { vec![String::new(), wrap.clone()] };
    for r in &roots {
        if low.iter().any(|p| p.starts_with(&format!("{r}interface/addons/"))) {
            return Some(Layout::Tree(r.clone()));
        }
    }
    let toc_at = |r: &str| {
        low.iter().any(|p| {
            p.strip_prefix(r).is_some_and(|rest| {
                let parts: Vec<&str> = rest.split('/').collect();
                parts.len() == 2 && parts[1] == format!("{}.toc", parts[0])
            })
        })
    };
    if toc_at("") {
        return Some(Layout::Folders(String::new()));
    }
    if !wrap.is_empty() && toc_at(&wrap) {
        return Some(Layout::Folders(wrap));
    }
    let root_tocs: Vec<&String> = paths.iter().filter(|p| !p.contains('/') && p.to_ascii_lowercase().ends_with(".toc")).collect();
    if root_tocs.len() == 1 {
        return Some(Layout::Single(root_tocs[0][..root_tocs[0].len() - 4].to_string()));
    }
    None
}

/// Take one native file into the plan, or say why it can't go in the client folder.
fn add_native(plan: &mut Plan, inner: &str, f: &Staged) {
    let parts: Vec<&str> = inner.split('/').collect();
    let top = parts[0].to_ascii_lowercase();
    let e = ext(inner);
    if parts.len() > 3 {
        plan.errors.push(format!("{}: native files sit at most two folders deep in the client folder", f.rel));
    } else if parts.len() > 1 && NATIVE_FORBIDDEN_TOP.contains(&top.as_str()) {
        plan.errors.push(format!("{}: native files may not go into the client's {} folder", f.rel, parts[0]));
    } else if !NATIVE_EXT.contains(&e.as_str()) {
        let shown = if e.is_empty() { "files without an extension".to_string() } else { e };
        plan.errors.push(format!("{}: {shown} is not a native mod file type (allowed: {})", f.rel, NATIVE_EXT.join(" ")));
    } else if f.size > MAX_FILE {
        plan.errors.push(format!("{} is larger than {}", f.rel, fmt_size(MAX_FILE)));
    } else {
        plan.natives.push(NativePlan { rel: inner.to_string(), abs: f.abs.clone(), size: f.size });
    }
}

/// The plan has native code (.dll, .asi, .exe), which needs the player's one-time OK.
pub fn has_native_code(plan: &Plan) -> bool {
    plan.natives.iter().any(|n| NATIVE_CODE_EXT.contains(&ext(&n.rel).as_str()))
}

/// Check staged files (from `walk`) for a client of `build`.
pub fn validate(files: &[Staged], build: Build) -> Plan {
    validate_in(files, build, false)
}

/// `validate` for Leyline's own addon pack (addons.rs): the same checks, and the realm's own addon names allowed.
pub fn validate_ours(files: &[Staged], build: Build) -> Plan {
    validate_in(files, build, true)
}

fn validate_in(files: &[Staged], build: Build, ours: bool) -> Plan {
    let mut plan = Plan::default();
    let files: Vec<&Staged> = files.iter().filter(|f| !f.rel.split('/').any(ignored)).collect();
    if files.is_empty() {
        plan.errors.push("there are no files in it".into());
        return plan;
    }
    if files.len() > MAX_FILES {
        plan.errors.push(format!("it has more than {MAX_FILES} files"));
        return plan;
    }
    let all: Vec<String> = files.iter().map(|f| f.rel.clone()).collect();
    let pkg_root = match locate(&all) {
        Some(Layout::Package(r)) => Some(r),
        _ => None,
    };
    let is_package = pkg_root.is_some();

    // Game data (by extension and by first bytes) and secrets, anywhere in it, even in parts a client never gets.
    let mut blocked: HashSet<PathBuf> = HashSet::new();
    for f in &files {
        let e = ext(&f.rel);
        if let Some(what) = secret_name(&f.rel) {
            plan.errors.push(format!("{} looks like {what}: secrets never go in a mod, take it out", f.rel));
            blocked.insert(f.abs.clone());
            continue;
        }
        if e != ".mpq" {
            if let Some((_, what)) = BLOCKED_EXT.iter().find(|(x, _)| *x == e) {
                plan.errors.push(format!("{} is {what}: game data cannot be in a mod", f.rel));
                blocked.insert(f.abs.clone());
                continue;
            }
            let h = head4(&f.abs);
            if let Some((_, what)) = BLOCKED_MAGIC.iter().find(|(m, _)| **m == h) {
                plan.errors.push(format!("{} is {what} (renamed): game data cannot be in a mod", f.rel));
                blocked.insert(f.abs.clone());
                continue;
            }
        }
        if !binary_media(&f.rel) {
            if let Some(what) = secret_in(&read_bytes(&f.abs, MAX_FILE)) {
                plan.errors.push(format!("{} holds {what}: secrets never go in a mod, take it out", f.rel));
                blocked.insert(f.abs.clone());
            }
        }
    }

    // Client patches: .MPQ files at the top of a plain drop (or of its one folder, or in a Data/ folder there).
    let tops: BTreeSet<&str> = files.iter().map(|f| f.rel.split('/').next().unwrap_or("")).collect();
    let wrap = if tops.len() == 1 && files.iter().all(|f| f.rel.contains('/')) { format!("{}/", tops.iter().next().unwrap()) } else { String::new() };
    let mut rest: Vec<&Staged> = Vec::new();
    for &f in &files {
        if ext(&f.rel) != ".mpq" {
            rest.push(f);
            continue;
        }
        if is_package {
            plan.errors.push(format!("{}: a mod package may not hold game archives (.MPQ); share a patch on its own", f.rel));
            continue;
        }
        let inner = f.rel.strip_prefix(&wrap).unwrap_or(&f.rel);
        let inner_low = inner.to_ascii_lowercase();
        let top_level = !inner.contains('/') || (inner_low.starts_with("data/") && inner.matches('/').count() == 1);
        if !top_level {
            plan.errors.push(format!("{}: a patch goes at the top of the zip (or in its Data folder)", f.rel));
            continue;
        }
        let magic = head4(&f.abs);
        if &magic != b"MPQ\x1a" && &magic != b"MPQ\x1b" {
            plan.errors.push(format!("{}: this is not an MPQ archive", f.rel));
            continue;
        }
        if f.size > MAX_PATCH {
            plan.errors.push(format!("{} is larger than {}", f.rel, fmt_size(MAX_PATCH)));
            continue;
        }
        let file_name = inner.rsplit('/').next().unwrap_or(inner).to_string();
        plan.patches.push(PatchPlan { file_name, abs: f.abs.clone(), size: f.size });
    }
    if !plan.patches.is_empty() && !build.takes_mpq_patches() {
        plan.errors.push(format!(
            "client patches (.MPQ) are for 1.12, 2.4.3 and 3.3.5a clients; this one is {}",
            build.version()
        ));
        plan.patches.clear();
    }
    if !plan.patches.is_empty() {
        plan.warnings.push(
            "a client patch changes the game files your client loads: only add patches from people you trust".into(),
        );
    }

    // Native code for the client folder itself: a package's native/ folder, or .dll/.asi/.exe files at the top of
    // a plain drop (with their own settings files next to them).
    let mut keep: Vec<&Staged> = Vec::new();
    if let Some(root) = &pkg_root {
        let pre = format!("{root}native/");
        for f in rest {
            if f.rel.to_ascii_lowercase().starts_with(&pre) {
                let inner = f.rel[pre.len()..].to_string();
                add_native(&mut plan, &inner, f);
            } else {
                keep.push(f);
            }
        }
    } else {
        let inner_of = |f: &Staged| f.rel.strip_prefix(&wrap).unwrap_or(&f.rel).to_string();
        // Not when that level is an addon's own folder (it has a .toc): code there is an addon error.
        let at_top = |want: &dyn Fn(&str) -> bool| {
            rest.iter().any(|f| {
                let i = inner_of(f);
                !i.contains('/') && want(&ext(&i))
            })
        };
        let top_code = at_top(&|e| NATIVE_CODE_EXT.contains(&e)) && !at_top(&|e| e == ".toc");
        for f in rest {
            let i = inner_of(f);
            if top_code && !i.contains('/') && NATIVE_EXT.contains(&ext(&i).as_str()) && !is_note(&i) {
                add_native(&mut plan, &i, f);
            } else {
                keep.push(f);
            }
        }
    }
    let rest = keep;
    if plan.natives.iter().any(|n| NATIVE_CODE_EXT.contains(&ext(&n.rel).as_str())) {
        let code: Vec<&str> = plan.natives.iter().filter(|n| NATIVE_CODE_EXT.contains(&ext(&n.rel).as_str())).map(|n| n.rel.as_str()).collect();
        plan.warnings.push(format!(
            "this mod has native code ({}): it runs inside your game with full access to your PC, so only add it if you trust its maker",
            code.join(", ")
        ));
    }

    let only_notes = rest.iter().all(|f| {
        let inner = f.rel.strip_prefix(&wrap).unwrap_or(&f.rel);
        !inner.contains('/') && is_note(inner)
    });
    let other = !plan.patches.is_empty() || !plan.natives.is_empty();
    if rest.is_empty() || (only_notes && other) {
        plan.skipped.extend(rest.iter().map(|f| f.rel.clone()));
        if !other && plan.errors.is_empty() {
            plan.errors.push("no addon or patch found in it".into());
        }
        return plan;
    }

    let paths: Vec<String> = rest.iter().map(|f| f.rel.clone()).collect();
    let Some(layout) = locate(&paths) else {
        plan.errors.push("no addon found: an addon is a folder <Name> with a <Name>.toc inside (Interface/AddOns/<Name>/)".into());
        return plan;
    };
    if let Layout::Package(root) = &layout {
        if let Some(f) = rest.iter().find(|f| f.rel.eq_ignore_ascii_case(&format!("{root}mod.json"))) {
            match serde_json::from_str::<ModMeta>(&read_text(&f.abs, 256 * 1024)) {
                Ok(m) if crate::catalog::id_ok(&format!("mod:{}", m.id)) => {
                    plan.meta = Some(ModMeta {
                        name: m.name.chars().take(48).collect(),
                        version: m.version.chars().take(40).collect(),
                        author: m.author.chars().take(80).collect(),
                        licence: m.licence.chars().take(80).collect(),
                        ..m
                    })
                }
                _ => plan.warnings.push("mod.json does not read as a mod package (no valid id): installed as plain addons".into()),
            }
        }
        if rest.iter().any(|f| f.rel.to_ascii_lowercase().starts_with(&format!("{root}realm/"))) {
            plan.warnings.push(
                "this mod also has a realm half: only its addon goes into your client; the realm half runs on a realm that installs it"
                    .into(),
            );
        }
    }
    let (root, addons_at) = match &layout {
        Layout::Package(r) => (r.clone(), "ui/"),
        Layout::Tree(r) => (r.clone(), "interface/addons/"),
        Layout::Folders(r) => (r.clone(), ""),
        Layout::Single(_) => (String::new(), ""),
    };
    let mut by_name: Vec<AddonPlan> = Vec::new();
    for f in &rest {
        if let Layout::Single(name) = &layout {
            let idx = match by_name.iter().position(|a| a.name.eq_ignore_ascii_case(name)) {
                Some(i) => i,
                None => {
                    by_name.push(AddonPlan { name: name.clone(), files: vec![], size: 0, title: None, version: None });
                    by_name.len() - 1
                }
            };
            by_name[idx].files.push((f.rel.clone(), f.abs.clone()));
            continue;
        }
        let low = f.rel.to_ascii_lowercase();
        if !low.starts_with(&root) {
            plan.errors.push(format!("{} is outside Interface/AddOns/<Name>/", f.rel));
            continue;
        }
        let rel = &f.rel[root.len()..];
        let rel_low = rel.to_ascii_lowercase();
        if matches!(layout, Layout::Package(_)) && !rel_low.starts_with("ui/") {
            let top = rel_low.split('/').next().unwrap_or("");
            if PACKAGE_TOP.contains(&top) {
                plan.skipped.push(rel.to_string());
            } else {
                plan.errors.push(format!(
                    "{} is outside Interface/AddOns/<Name>/ (a mod package puts only its ui/ folder in the client)",
                    f.rel
                ));
            }
            continue;
        }
        if !rel_low.starts_with(addons_at) {
            if !rel.contains('/') && is_note(rel) {
                plan.skipped.push(rel.to_string());
            } else {
                plan.errors.push(format!("{} is outside Interface/AddOns/<Name>/", f.rel));
            }
            continue;
        }
        let inner = &rel[addons_at.len()..];
        let Some((name, path)) = inner.split_once('/') else {
            if is_note(inner) {
                plan.skipped.push(rel.to_string());
            } else {
                plan.errors.push(format!("{} is not inside an addon folder (Interface/AddOns/<Name>/)", f.rel));
            }
            continue;
        };
        match by_name.iter_mut().find(|a| a.name.eq_ignore_ascii_case(name)) {
            Some(a) if a.name != name => {
                plan.errors.push(format!("{}: the folder {} is spelled two ways", f.rel, a.name));
            }
            Some(a) => a.files.push((path.to_string(), f.abs.clone())),
            None => by_name.push(AddonPlan {
                name: name.to_string(),
                files: vec![(path.to_string(), f.abs.clone())],
                size: 0,
                title: None,
                version: None,
            }),
        }
    }
    let mut total = 0;
    for mut a in by_name {
        let errs = check_addon(&mut a, build, &mut plan.warnings, &blocked, ours);
        plan.errors.extend(errs);
        a.size = a.files.iter().map(|(_, p)| fs::metadata(p).map(|m| m.len()).unwrap_or(0)).sum();
        total += a.size;
        plan.addons.push(a);
    }
    if plan.addons.is_empty() && plan.patches.is_empty() && plan.natives.is_empty() && plan.errors.is_empty() {
        plan.errors.push("no addon found in it".into());
    }
    total += plan.natives.iter().map(|n| n.size).sum::<u64>();
    if total > MAX_PACKAGE {
        plan.errors.push(format!("it is larger than {}", fmt_size(MAX_PACKAGE)));
    }
    plan
}

// ------------------------------------------------------------------------------------------------ manifest

/// One installed mod, as the manifest keeps it.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Installed {
    /// `mod:<id>` for a catalog mod (or a local package with a mod.json), `local:<addon>` or `patch:<file>`.
    pub key: String,
    pub name: String,
    pub version: String,
    /// `catalog` or `local`.
    pub source: String,
    /// The zip's sha256, when it came as one.
    pub sha256: String,
    pub installed_at: u64,
    pub enabled: bool,
    pub addons: Vec<String>,
    /// Data/ slots, client-relative (`Data/patch-A.MPQ`).
    pub patches: Vec<String>,
    /// Native files in the client folder itself (client-relative), such as `d3d9.dll`.
    pub natives: Vec<String>,
    /// It has native code (.dll, .asi, .exe): the player OK'd it once.
    pub native_code: bool,
    /// Every file Leyline put in the client, client-relative and `/`-separated.
    pub files: Vec<String>,
    /// Each file's sha256 as Leyline wrote it, so removal and updates can tell files the player changed.
    pub hashes: BTreeMap<String, String>,
    /// The addon folders (client-relative) that are this mod's own.
    pub dirs: Vec<String>,
    pub category: String,
    pub credits: String,
    pub warnings: Vec<String>,
    /// Only on the install that just happened (never saved): the player's changed files an update kept.
    #[serde(skip_deserializing, skip_serializing_if = "Vec::is_empty")]
    pub kept: Vec<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Manifest {
    pub schema: u32,
    pub build: String,
    pub mods: Vec<Installed>,
    /// Folders Leyline had to make (such as Interface/AddOns), removed again when they empty.
    pub created_dirs: Vec<String>,
}

impl Manifest {
    pub fn get(&self, key: &str) -> Option<&Installed> {
        self.mods.iter().find(|m| m.key == key)
    }
}

pub fn manifest_path(client: &Path) -> PathBuf {
    client.join(DIR).join(MANIFEST)
}

pub fn load(client: &Path) -> Manifest {
    fs::read(manifest_path(client)).ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_default()
}

fn save(client: &Path, m: &Manifest) -> Result<(), String> {
    let mut b = serde_json::to_vec_pretty(m).map_err(|e| e.to_string())?;
    b.push(b'\n');
    crate::settings::write_atomic(&manifest_path(client), &b).map_err(|e| format!("could not save the mod list: {e}"))
}

fn slug(key: &str) -> String {
    key.chars().map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '.' { c } else { '_' }).collect()
}

fn disabled_dir(client: &Path, key: &str) -> PathBuf {
    client.join(DIR).join("disabled").join(slug(key))
}

/// `client/rel`, refusing anything that would leave the client folder or run through a symbolic link.
fn inside(client: &Path, rel: &str) -> Result<PathBuf, String> {
    let mut p = client.to_path_buf();
    for c in Path::new(rel).components() {
        match c {
            Component::Normal(x) => {
                p.push(x);
                if let Ok(md) = fs::symlink_metadata(&p) {
                    if md.file_type().is_symlink() {
                        return Err(format!("{rel} runs through a link to somewhere else: Leyline will not write there"));
                    }
                }
            }
            _ => return Err(format!("{rel} is not inside the client folder")),
        }
    }
    Ok(p)
}

fn rel_of(client: &Path, p: &Path) -> String {
    p.strip_prefix(client).unwrap_or(p).components().map(|c| c.as_os_str().to_string_lossy().to_string()).collect::<Vec<_>>().join("/")
}

/// Move a file, across drives if need be.
fn move_file(from: &Path, to: &Path) -> io::Result<()> {
    if let Some(d) = to.parent() {
        fs::create_dir_all(d)?;
    }
    if fs::rename(from, to).is_ok() {
        return Ok(());
    }
    fs::copy(from, to)?;
    fs::remove_file(from)
}

/// Move every (from, to) or none: on an error the ones already moved go back.
fn move_all(pairs: &[(PathBuf, PathBuf)]) -> Result<(), String> {
    for (i, (from, to)) in pairs.iter().enumerate() {
        if to.exists() {
            for (f, t) in pairs[..i].iter().rev() {
                let _ = move_file(t, f);
            }
            return Err(format!("{} is in the way", to.display()));
        }
        if let Err(e) = move_file(from, to) {
            for (f, t) in pairs[..i].iter().rev() {
                let _ = move_file(t, f);
            }
            return Err(format!("could not move {}: {e}", from.display()));
        }
    }
    Ok(())
}

/// Remove `dir` and its parents up to (not including) `stop` while they are empty.
fn prune(dir: &Path, stop: &Path) {
    let mut d = dir.to_path_buf();
    while d.starts_with(stop) && d != stop {
        if fs::remove_dir(&d).is_err() {
            break;
        }
        if !d.pop() {
            break;
        }
    }
}

/// Remove the empty folders a file list leaves behind under `base`, deepest first, never above the mod's own
/// addon folders. Returns what is left in those folders (files Leyline did not put there).
fn prune_dirs(base: &Path, files: &[String], dirs: &[String]) -> Vec<String> {
    let mut all: BTreeSet<String> = dirs.iter().cloned().collect();
    for f in files {
        let mut parts: Vec<&str> = f.split('/').collect();
        parts.pop();
        while !parts.is_empty() {
            let d = parts.join("/");
            if dirs.iter().any(|r| d == *r || d.starts_with(&format!("{r}/"))) {
                all.insert(d);
            }
            parts.pop();
        }
    }
    let mut list: Vec<String> = all.into_iter().collect();
    list.sort_by_key(|d| std::cmp::Reverse(d.matches('/').count()));
    for d in &list {
        let _ = fs::remove_dir(base.join(d));
    }
    let mut kept = Vec::new();
    for d in dirs {
        let p = base.join(d);
        if p.is_dir() {
            if let Ok(w) = walk(&p) {
                kept.extend(w.into_iter().map(|s| format!("{d}/{}", s.rel)));
            }
        }
    }
    kept
}

fn addons_dir(client: &Path, created: &mut Vec<String>) -> Result<PathBuf, String> {
    let iface = match find_ci(client, "Interface") {
        Some(p) => p,
        None => {
            created.push("Interface".into());
            client.join("Interface")
        }
    };
    let addons = match find_ci(&iface, "AddOns") {
        Some(p) => p,
        None => {
            created.push(format!("{}/AddOns", rel_of(client, &iface)));
            iface.join("AddOns")
        }
    };
    let rel = rel_of(client, &addons);
    inside(client, &rel)?;
    fs::create_dir_all(&addons).map_err(|e| format!("could not make {rel}: {e}"))?;
    Ok(addons)
}

/// What the install is, for the manifest.
#[derive(Debug, Clone, Default)]
pub struct InstallMeta {
    pub key: String,
    pub name: String,
    pub version: String,
    pub source: String,
    pub sha256: String,
    pub category: String,
    pub credits: String,
}

/// The manifest key, name and version for a local drop, from its mod.json or its addons.
pub fn local_meta(plan: &Plan) -> InstallMeta {
    if let Some(m) = &plan.meta {
        return InstallMeta {
            key: format!("mod:{}", m.id),
            name: if m.name.is_empty() { m.id.clone() } else { m.name.clone() },
            version: m.version.clone(),
            source: "local".into(),
            credits: [m.author.as_str(), m.licence.as_str()].iter().filter(|s| !s.is_empty()).cloned().collect::<Vec<_>>().join(" · "),
            ..Default::default()
        };
    }
    if let Some(a) = plan.addons.first() {
        let name = if plan.addons.len() == 1 {
            a.title.clone().filter(|t| !t.is_empty()).unwrap_or_else(|| a.name.clone())
        } else {
            plan.addons.iter().map(|a| a.name.as_str()).collect::<Vec<_>>().join(", ")
        };
        return InstallMeta {
            key: format!("local:{}", a.name.to_ascii_lowercase()),
            name: name.chars().take(64).collect(),
            version: a.version.clone().unwrap_or_default(),
            source: "local".into(),
            ..Default::default()
        };
    }
    let p = plan.patches.first().map(|p| p.file_name.clone()).unwrap_or_default();
    InstallMeta {
        key: format!("patch:{}", slug(&p.to_ascii_lowercase())),
        name: format!("Client patch {p}"),
        source: "local".into(),
        ..Default::default()
    }
}

fn patch_slot_of(name: &str) -> Option<char> {
    let l = name.to_ascii_lowercase();
    let c = l.strip_prefix("patch-")?.strip_suffix(".mpq")?;
    let mut it = c.chars();
    let ch = it.next()?.to_ascii_uppercase();
    (it.next().is_none() && PATCH_SLOTS.contains(ch)).then_some(ch)
}

/// The sha256 of an installed file, or "" when it can't be read.
fn hash_of(p: &Path) -> String {
    net::sha256_file(p).unwrap_or_default()
}

/// The player changed this file since Leyline put it there (a manifest from before hashes counts as unchanged).
fn changed(m: &Installed, rel: &str, p: &Path) -> bool {
    m.hashes.get(rel).is_some_and(|h| !h.is_empty() && *h != hash_of(p))
}

/// `p.yours`, or `p.yours2`, `p.yours3`... whichever is free: where a player's changed copy goes.
fn free_name(p: &Path) -> PathBuf {
    let name = p.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
    let mut i = 1;
    loop {
        let cand = p.with_file_name(if i == 1 { format!("{name}.yours") } else { format!("{name}.yours{i}") });
        if !cand.exists() {
            return cand;
        }
        i += 1;
    }
}

/// `rel` with each folder spelled the way the client already spells it (Scripts/ vs scripts/).
fn resolve_ci(client: &Path, rel: &str) -> String {
    let parts: Vec<&str> = rel.split('/').collect();
    let mut at = client.to_path_buf();
    let mut out: Vec<String> = Vec::new();
    for (i, part) in parts.iter().enumerate() {
        match find_ci(&at, part) {
            Some(p) => {
                out.push(p.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_else(|| part.to_string()));
                at = p;
            }
            None => {
                out.extend(parts[i..].iter().map(|x| x.to_string()));
                break;
            }
        }
    }
    out.join("/")
}

/// What the player's native-code OK is stored under: the mod's key plus a digest of every native file it brings
/// (its client-relative name and sha256), so the OK covers these exact files. An update that changes a DLL, an
/// .asi or their settings has a new consent key and asks again. `<key>:<16 hex>`, or `native:<32 hex>` for a key
/// too long for that (what `mod_native_confirm` takes: at most 80 of `[A-Za-z0-9:._-]`).
pub fn native_consent_key(key: &str, plan: &Plan) -> String {
    use sha2::{Digest, Sha256};
    let mut files: Vec<(String, String)> = plan
        .natives
        .iter()
        .map(|n| (n.rel.to_ascii_lowercase(), net::sha256_file(&n.abs).unwrap_or_else(|_| format!("unreadable:{}", n.size))))
        .collect();
    files.sort();
    let mut h = Sha256::new();
    for (rel, sha) in &files {
        h.update(rel.as_bytes());
        h.update([0u8]);
        h.update(sha.as_bytes());
        h.update([b'\n']);
    }
    let d = h.finalize().iter().map(|b| format!("{b:02x}")).collect::<String>();
    let plain = key.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, ':' | '.' | '_' | '-'));
    if plain && key.len() + 17 <= 80 {
        format!("{key}:{}", &d[..16])
    } else {
        let mut k = Sha256::new();
        k.update(key.as_bytes());
        k.update([0u8]);
        k.update(d.as_bytes());
        let kd = k.finalize().iter().map(|b| format!("{b:02x}")).collect::<String>();
        format!("native:{}", &kd[..32])
    }
}

fn native_confirm_error(meta: &InstallMeta, plan: &Plan) -> String {
    let files: Vec<&str> = plan.natives.iter().map(|n| n.rel.as_str()).collect();
    // "key" is the consent key (what mod_native_confirm stores); "mod" is the mod's own key.
    format!(
        "{NATIVE_CONFIRM}{}",
        serde_json::json!({ "key": native_consent_key(&meta.key, plan), "mod": meta.key, "name": meta.name, "files": files })
    )
}

/// Put a validated plan into the client. Replaces the same mod (same key) when it is already installed (an
/// update): files the player changed since are not lost, see `Installed::kept`. Native code needs `native_ok`
/// (the player's OK for this mod and these exact native files, `native_consent_key`); without it the error starts with `NATIVE_CONFIRM`. Nothing that is
/// installed is ever run.
pub fn install(client: &Path, build: Build, meta: InstallMeta, plan: &Plan, native_ok: bool) -> Result<Installed, String> {
    if !plan.errors.is_empty() {
        return Err(plan.errors.join("\n"));
    }
    if plan.addons.is_empty() && plan.patches.is_empty() && plan.natives.is_empty() {
        return Err("nothing to install".into());
    }
    if has_native_code(plan) && !native_ok {
        return Err(native_confirm_error(&meta, plan));
    }
    let mut man = load(client);
    man.schema = SCHEMA;
    man.build = build.catalog_tag().into();
    let old = man.get(&meta.key).cloned();
    let others: Vec<&Installed> = man.mods.iter().filter(|m| m.key != meta.key).collect();

    let mut created = Vec::new();
    let mut moves: Vec<(PathBuf, PathBuf)> = Vec::new();
    let mut files = Vec::new();
    let mut dirs = Vec::new();
    let mut hashes = BTreeMap::new();
    if !plan.addons.is_empty() {
        let addons = addons_dir(client, &mut created)?;
        for a in &plan.addons {
            if let Some(o) = others.iter().find(|m| m.addons.iter().any(|x| x.eq_ignore_ascii_case(&a.name))) {
                return Err(format!("{} is already installed by \"{}\": remove that one first", a.name, o.name));
            }
            if let Some(there) = find_ci(&addons, &a.name) {
                let ours = old.as_ref().is_some_and(|o| o.enabled && o.addons.iter().any(|x| x.eq_ignore_ascii_case(&a.name)));
                if !ours {
                    return Err(format!(
                        "An addon folder named {} is already in this client ({}), and Leyline did not put it there. Remove it first, or keep yours and skip this mod.",
                        a.name,
                        rel_of(client, &there)
                    ));
                }
            }
            let dest = addons.join(&a.name);
            let dir_rel = rel_of(client, &dest);
            inside(client, &dir_rel)?;
            dirs.push(dir_rel.clone());
            for (p, abs) in &a.files {
                let rel = format!("{dir_rel}/{p}");
                moves.push((abs.clone(), inside(client, &rel)?));
                hashes.insert(rel.clone(), hash_of(abs));
                files.push(rel);
            }
        }
    }
    let mut slots = Vec::new();
    if !plan.patches.is_empty() {
        let data = find_ci(client, "Data").ok_or("this client has no Data folder")?;
        let data_rel = rel_of(client, &data);
        let taken = |c: char, slots: &Vec<String>| {
            let n = format!("patch-{c}.MPQ");
            let mine = old.as_ref().is_some_and(|o| o.patches.iter().any(|p| p.eq_ignore_ascii_case(&format!("{data_rel}/{n}"))));
            (find_ci(&data, &n).is_some() && !mine)
                || others.iter().any(|m| m.patches.iter().any(|p| p.eq_ignore_ascii_case(&format!("{data_rel}/{n}"))))
                || slots.iter().any(|s: &String| s.eq_ignore_ascii_case(&format!("{data_rel}/{n}")))
        };
        let mut reuse: Vec<char> =
            old.as_ref().map(|o| o.patches.iter().filter_map(|p| patch_slot_of(p.rsplit('/').next().unwrap_or(p))).collect()).unwrap_or_default();
        for p in &plan.patches {
            let own = patch_slot_of(&p.file_name).filter(|c| !taken(*c, &slots));
            let pick = own
                .or_else(|| {
                    let i = reuse.iter().position(|c| !taken(*c, &slots))?;
                    Some(reuse.remove(i))
                })
                .or_else(|| PATCH_SLOTS.chars().find(|c| !taken(*c, &slots)))
                .ok_or("every patch slot in Data is taken")?;
            let rel = format!("{data_rel}/patch-{pick}.MPQ");
            moves.push((p.abs.clone(), inside(client, &rel)?));
            hashes.insert(rel.clone(), hash_of(&p.abs));
            files.push(rel.clone());
            slots.push(rel);
        }
    }
    // Native files go in the client folder itself. Never over a file Leyline did not put there (the game's own
    // executable, the player's own d3d9.dll), and a folder they need is the mod's own when Leyline makes it.
    let mut natives = Vec::new();
    for n in &plan.natives {
        let rel = resolve_ci(client, &n.rel);
        let same = |m: &Installed| m.files.iter().any(|f| f.eq_ignore_ascii_case(&rel));
        if let Some(o) = others.iter().find(|m| same(m)) {
            return Err(format!("{rel} is already installed by \"{}\": remove that one first", o.name));
        }
        if client.join(&rel).exists() && !old.as_ref().is_some_and(|o| o.enabled && same(o)) {
            return Err(format!(
                "{rel} is already in this client folder, and Leyline did not put it there. Leyline never replaces the game's own files or yours: move it away first if you want this mod."
            ));
        }
        if let Some((d, _)) = rel.split_once('/') {
            let mine_before = old.as_ref().is_some_and(|o| o.dirs.iter().any(|x| x.eq_ignore_ascii_case(d)));
            if (find_ci(client, d).is_none() || mine_before) && !dirs.iter().any(|x: &String| x.eq_ignore_ascii_case(d)) {
                dirs.push(d.to_string());
            }
        }
        moves.push((n.abs.clone(), inside(client, &rel)?));
        hashes.insert(rel.clone(), hash_of(&n.abs));
        files.push(rel.clone());
        natives.push(rel);
    }

    // The old version steps aside (into staging) so a failed install can put it back. A file the player changed
    // is never thrown away: it stays where it is, or, when the new version brings a file of the same name, it is
    // renamed to <name>.yours next to it.
    let new_low: HashSet<String> = files.iter().map(|f| f.to_ascii_lowercase()).collect();
    let aside = Staging::new(client).map_err(|e| e.to_string())?;
    let mut aside_moves = Vec::new();
    let mut yours_moves = Vec::new();
    let mut kept = Vec::new();
    if let Some(o) = &old {
        let base = if o.enabled { client.to_path_buf() } else { disabled_dir(client, &o.key) };
        for f in &o.files {
            let from = base.join(f);
            if !from.is_file() {
                continue;
            }
            if changed(o, f, &from) {
                let live = inside(client, f)?;
                if new_low.contains(&f.to_ascii_lowercase()) || (!o.enabled && live.exists()) {
                    let to = free_name(&live);
                    kept.push(format!("{f} (you changed it: your copy is now {})", rel_of(client, &to)));
                    yours_moves.push((from, to));
                } else {
                    kept.push(format!("{f} (you changed it, so it stays)"));
                    if !o.enabled {
                        yours_moves.push((from, live));
                    }
                }
                continue;
            }
            aside_moves.push((from, aside.dir.join("old").join(f)));
        }
        move_all(&aside_moves)?;
        if let Err(e) = move_all(&yours_moves) {
            let back: Vec<(PathBuf, PathBuf)> = aside_moves.iter().map(|(a, b)| (b.clone(), a.clone())).collect();
            let _ = move_all(&back);
            return Err(e);
        }
        // Files Leyline did not put there (notes the player added, say) stay where they are.
        prune_dirs(&base, &o.files, &o.dirs);
        if !o.enabled {
            let _ = fs::remove_dir_all(disabled_dir(client, &o.key));
            prune(&client.join(DIR).join("disabled"), &client.join(DIR));
        }
    }
    if let Err(e) = move_all(&moves) {
        let back: Vec<(PathBuf, PathBuf)> =
            yours_moves.iter().chain(aside_moves.iter()).map(|(a, b)| (b.clone(), a.clone())).collect();
        let _ = move_all(&back);
        return Err(e);
    }
    for c in created {
        if !man.created_dirs.contains(&c) {
            man.created_dirs.push(c);
        }
    }
    let mut entry = Installed {
        key: meta.key.clone(),
        name: meta.name,
        version: meta.version,
        source: meta.source,
        sha256: meta.sha256,
        installed_at: now(),
        enabled: true,
        addons: plan.addons.iter().map(|a| a.name.clone()).collect(),
        patches: slots,
        natives,
        native_code: has_native_code(plan),
        files,
        hashes,
        dirs,
        category: meta.category,
        credits: meta.credits,
        warnings: plan.warnings.clone(),
        kept: Vec::new(),
    };
    man.mods.retain(|m| m.key != meta.key);
    man.mods.push(entry.clone());
    man.mods.sort_by_key(|m| m.name.to_ascii_lowercase());
    save(client, &man)?;
    entry.kept = kept;
    Ok(entry)
}

/// What a removal did.
#[derive(Debug, Clone, Default, Serialize)]
pub struct Removed {
    pub removed_files: usize,
    /// Files in the mod's folders that Leyline did not put there, left alone.
    pub kept: Vec<String>,
    /// Files Leyline put there that the player changed since: left in place (they are the player's now).
    pub changed: Vec<String>,
}

/// Remove a mod: exactly the files the manifest lists and that are still as Leyline wrote them, then the
/// folders they leave empty. A file the player changed stays, and is reported.
pub fn uninstall(client: &Path, key: &str) -> Result<Removed, String> {
    let mut man = load(client);
    let entry = man.get(key).cloned().ok_or("That mod is not installed in this client.")?;
    let base = if entry.enabled { client.to_path_buf() } else { disabled_dir(client, key) };
    let mut out = Removed::default();
    for f in &entry.files {
        let p = if entry.enabled { inside(client, f)? } else { base.join(f) };
        match fs::symlink_metadata(&p) {
            Ok(md) if md.is_file() => {
                if changed(&entry, f, &p) {
                    if entry.enabled {
                        out.changed.push(f.clone());
                    } else {
                        // A turned-off mod's changed file goes back to where the player had it (or next to it).
                        let live = inside(client, f)?;
                        let to = if live.exists() { free_name(&live) } else { live };
                        move_file(&p, &to).map_err(|e| format!("could not keep {f}: {e}"))?;
                        out.changed.push(rel_of(client, &to));
                    }
                    continue;
                }
                fs::remove_file(&p).map_err(|e| format!("could not remove {f}: {e}"))?;
                out.removed_files += 1;
            }
            _ => {}
        }
    }
    out.kept = prune_dirs(&base, &entry.files, &entry.dirs);
    out.kept.retain(|k| !out.changed.contains(k));
    if !entry.enabled {
        let _ = fs::remove_dir_all(disabled_dir(client, key));
        prune(&client.join(DIR).join("disabled"), &client.join(DIR));
    }
    man.mods.retain(|m| m.key != key);
    if man.mods.is_empty() {
        let mut created = man.created_dirs.clone();
        created.sort_by_key(|d| std::cmp::Reverse(d.matches('/').count()));
        for d in created {
            let _ = fs::remove_dir(client.join(d));
        }
        let _ = fs::remove_file(manifest_path(client));
        let lr = client.join(DIR);
        let _ = fs::remove_dir(lr.join("disabled"));
        let _ = fs::remove_dir(lr.join("staging"));
        let _ = fs::remove_dir(&lr);
    } else {
        save(client, &man)?;
    }
    Ok(out)
}

/// Turn a mod off (its files wait in Leyline/disabled/, where the game does not look) or back on.
pub fn set_enabled(client: &Path, key: &str, on: bool) -> Result<(), String> {
    let mut man = load(client);
    let idx = man.mods.iter().position(|m| m.key == key).ok_or("That mod is not installed in this client.")?;
    let entry = man.mods[idx].clone();
    if entry.enabled == on {
        return Ok(());
    }
    let stash = disabled_dir(client, key);
    let mut pairs = Vec::new();
    for f in &entry.files {
        let live = inside(client, f)?;
        let off = stash.join(f);
        if on {
            if off.is_file() {
                pairs.push((off, live));
            }
        } else if live.is_file() {
            pairs.push((live, off));
        }
    }
    if on {
        // Addon folders (Interface/AddOns/<Name>) must be free again; a native mod's own folder may be shared.
        for d in entry.dirs.iter().filter(|d| d.contains('/')) {
            if client.join(d).exists() {
                return Err(format!("{d} is in use by something else now: remove it, or remove and reinstall this mod"));
            }
        }
        for p in entry.patches.iter().chain(entry.natives.iter()) {
            if client.join(p).exists() {
                return Err(format!("{p} is taken now: move it away, or remove and reinstall this mod"));
            }
        }
    }
    move_all(&pairs)?;
    if on {
        // Every file went back, so only empty folders are left in the stash.
        let _ = fs::remove_dir_all(&stash);
        prune(&client.join(DIR).join("disabled"), &client.join(DIR));
    } else {
        prune_dirs(client, &entry.files, &entry.dirs);
    }
    man.mods[idx].enabled = on;
    save(client, &man)
}

// ------------------------------------------------------------------------------------------------ installs

/// A scratch folder under the launcher's own data folder (outside every client), removed when dropped.
pub struct Scratch {
    pub dir: PathBuf,
}

impl Scratch {
    pub fn new(base: &Path) -> io::Result<Scratch> {
        let root = base.join("downloads");
        fs::create_dir_all(&root)?;
        let nanos = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
        let dir = root.join(format!("{}-{nanos}", std::process::id()));
        fs::create_dir(&dir)?;
        Ok(Scratch { dir })
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.dir);
        if let Some(root) = self.dir.parent() {
            let _ = fs::remove_dir(root);
        }
    }
}

/// Check and install a local zip, .MPQ, native file (.dll, .asi, .exe) or folder. `native_ok(consent key)` says
/// whether the player already OK'd that mod's native files as they are now (`native_consent_key`).
pub fn install_local(client: &Path, build: Build, src: &Path, native_ok: &dyn Fn(&str) -> bool) -> Result<Installed, String> {
    let st = Staging::new(client).map_err(|e| format!("could not make a staging folder in the client: {e}"))?;
    let files = st.files();
    fs::create_dir_all(&files).map_err(|e| e.to_string())?;
    let md = fs::metadata(src).map_err(|e| format!("could not read {}: {e}", src.display()))?;
    let mut sha = String::new();
    if md.is_dir() {
        copy_folder(src, &files)?;
    } else {
        let name = src.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
        let magic = head4(src);
        let single = ext(&name) == ".mpq" || NATIVE_CODE_EXT.contains(&ext(&name).as_str());
        if &magic[..2] == b"PK" && ext(&name) != ".exe" {
            extract_zip(src, &files, MAX_LOCAL_ZIP)?;
            sha = net::sha256_file(src).unwrap_or_default();
        } else if single {
            let cap = cap_for(&name);
            if md.len() > cap {
                return Err(format!("{name} is larger than {}", fmt_size(cap)));
            }
            let n = safe_rel(&name)?.ok_or("bad file name")?;
            fs::copy(src, files.join(n)).map_err(|e| e.to_string())?;
            sha = net::sha256_file(src).unwrap_or_default();
        } else {
            return Err(format!("{name}: drop a .zip, an addon folder, a client patch (.MPQ) or a native mod (.dll, .asi)"));
        }
    }
    let staged = walk(&files).map_err(|e| e.to_string())?;
    let plan = validate(&staged, build);
    let mut meta = local_meta(&plan);
    meta.sha256 = sha;
    let ok = native_ok(&native_consent_key(&meta.key, &plan));
    install(client, build, meta, &plan, ok)
}

/// Download a catalog mod (over https, from the catalog's own site only) into the launcher's scratch folder,
/// check its sha256 against the catalog before the client folder is touched, then install it like a local zip.
/// A catalog entry without a sha256 is refused.
pub fn install_project(
    client: &Path,
    build: Build,
    p: &Project,
    catalog_origin: &str,
    scratch: &Path,
    native_ok: &dyn Fn(&str) -> bool,
) -> Result<Installed, String> {
    if !p.installable() {
        return Err(if p.repo.is_empty() {
            "This project has no download in the catalog.".into()
        } else {
            "This is a community link: get it from its page, then drop the zip on My Mods.".into()
        });
    }
    if !p.fits(build) {
        return Err(format!("{} is made for the {} client, not this {} one.", p.name, p.builds.join(" / "), build.catalog_tag()));
    }
    let url = p.download.as_deref().unwrap_or_default();
    // The tests serve plain http on 127.0.0.1; the app only ever has the https catalog.
    if !cfg!(test) && !url.starts_with("https://") {
        return Err("Leyline only downloads mods over https.".into());
    }
    if net::origin(url).as_deref() != Some(catalog_origin) {
        return Err("That download is not on the Workshop's own site.".into());
    }
    let want = p.sha256.clone().ok_or_else(|| format!("{} has no checksum in the catalog, so Leyline will not install it.", p.name))?;
    if p.size.is_some_and(|n| n > MAX_DOWNLOAD) {
        return Err(format!("{} is larger than the {} download limit.", p.name, fmt_size(MAX_DOWNLOAD)));
    }
    let dl = Scratch::new(scratch).map_err(|e| format!("could not make a download folder: {e}"))?;
    let zip = dl.dir.join("download.zip");
    let (_, sha) = net::download(url, &zip, MAX_DOWNLOAD, net::TIMEOUT, Duration::from_secs(30))
        .map_err(|e| format!("Download failed: {e}"))?;
    if sha != want {
        return Err("The download does not match the catalog's checksum, so it was not installed. Try again later.".into());
    }
    let st = Staging::new(client).map_err(|e| format!("could not make a staging folder in the client: {e}"))?;
    let files = st.files();
    fs::create_dir_all(&files).map_err(|e| e.to_string())?;
    extract_zip(&zip, &files, MAX_DOWNLOAD)?;
    let mut plan = validate(&walk(&files).map_err(|e| e.to_string())?, build);
    if !plan.patches.is_empty() {
        plan.errors.push("A Workshop mod may not carry game archives (.MPQ).".into());
    }
    if plan.addons.is_empty() && plan.natives.is_empty() && plan.errors.is_empty() {
        return Err(format!("{} has no addon for the client (it is a realm mod: it runs on a realm, not in your game).", p.name));
    }
    let meta = InstallMeta {
        key: p.id.clone(),
        name: p.name.clone(),
        version: p.version.clone().unwrap_or_default(),
        source: "catalog".into(),
        sha256: sha,
        category: p.category.clone(),
        credits: p.credits.clone(),
    };
    let ok = native_ok(&native_consent_key(&meta.key, &plan));
    install(client, build, meta, &plan, ok)
}

// ------------------------------------------------------------------------------------------------ updates

/// (major, minor, patch) of a version such as `0.1.0` or `v1.2`, missing parts as 0.
pub fn version_tuple(v: &str) -> Option<(u64, u64, u64)> {
    let v = v.trim().trim_start_matches(['v', 'V']);
    let core = v.split(['-', '+']).next()?;
    let mut it = core.split('.').map(|x| x.parse::<u64>());
    let a = it.next()?.ok()?;
    let b = it.next().unwrap_or(Ok(0)).ok()?;
    let c = it.next().unwrap_or(Ok(0)).ok()?;
    Some((a, b, c))
}

/// `latest` is newer than `have`.
pub fn newer(latest: &str, have: &str) -> bool {
    match (version_tuple(latest), version_tuple(have)) {
        (Some(l), Some(h)) => l > h,
        _ => false,
    }
}

/// An installed mod for the UI, with what the catalog says about it now.
#[derive(Debug, Clone, Serialize)]
pub struct InstalledView {
    #[serde(flatten)]
    pub mod_: Installed,
    pub update: Option<String>,
    /// The catalog lists it, and for this client.
    pub in_catalog: bool,
}

pub fn with_updates(man: &Manifest, catalog: &[Project], build: Build) -> Vec<InstalledView> {
    man.mods
        .iter()
        // Leyline's own addon pack has its own row (Mods › Our addons, addons.rs), not a Workshop card.
        .filter(|m| m.key != crate::addons::KEY)
        .map(|m| {
            let p = catalog.iter().find(|p| p.id == m.key && p.installable() && p.fits(build));
            let update = p.and_then(|p| p.version.clone()).filter(|v| newer(v, &m.version));
            InstalledView { mod_: m.clone(), update, in_catalog: p.is_some() }
        })
        .collect()
}

#[cfg(test)]
pub mod tests {
    use super::*;
    use crate::clients::testutil::{fake_1121, fake_335a, touch};
    use crate::net::testserver::serve_routes;
    use std::io::Write;

    /// A zip of (name, bytes); a name ending in '/' is a folder entry.
    pub fn zip_of(entries: &[(&str, &[u8])]) -> Vec<u8> {
        let mut buf = io::Cursor::new(Vec::new());
        {
            let mut w = zip::ZipWriter::new(&mut buf);
            let opt = zip::write::SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated);
            for (n, b) in entries {
                if n.ends_with('/') {
                    w.add_directory(*n, opt).unwrap();
                } else {
                    w.start_file(*n, opt).unwrap();
                    w.write_all(b).unwrap();
                }
            }
            w.finish().unwrap();
        }
        buf.into_inner()
    }

    /// install_local with no native OKs given.
    fn install_local_t(c: &Path, b: Build, src: &Path) -> Result<Installed, String> {
        install_local(c, b, src, &|_| false)
    }

    /// install_project with a throwaway launcher folder and no native OKs given.
    fn install_project_t(c: &Path, b: Build, p: &Project, origin: &str) -> Result<Installed, String> {
        let scratch = tempfile::tempdir().unwrap();
        let r = install_project(c, b, p, origin, scratch.path(), &|_| false);
        assert!(!scratch.path().join("downloads").exists(), "the download folder is cleaned up");
        r
    }

    fn toc(name: &str, iface: &str, files: &[&str]) -> Vec<u8> {
        format!("## Interface: {iface}\n## Title: |cff33ff99{name}|r\n## Version: 1.2.0\n{}\n", files.join("\n")).into_bytes()
    }

    fn client335() -> tempfile::TempDir {
        let d = tempfile::tempdir().unwrap();
        fake_335a(d.path(), true);
        d
    }

    fn write(dir: &Path, name: &str, bytes: &[u8]) -> PathBuf {
        let p = dir.join(name);
        fs::write(&p, bytes).unwrap();
        p
    }

    /// Every file under the client, for "nothing left behind" checks.
    fn tree(root: &Path) -> Vec<String> {
        walk(root).unwrap().into_iter().map(|s| s.rel).collect()
    }

    #[test]
    fn safe_paths() {
        assert_eq!(safe_rel("a/b.lua").unwrap().as_deref(), Some("a/b.lua"));
        assert_eq!(safe_rel("a\\b.lua").unwrap().as_deref(), Some("a/b.lua"));
        assert_eq!(safe_rel("dir/").unwrap(), None);
        for bad in ["../x", "a/../../x", "/etc/passwd", "C:/x", "c:x", "a//b", "a/./b", "a/CON.txt", "a/x:y", "a/b. ", "a/b."] {
            assert!(safe_rel(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn zip_slip_and_symlinks_are_refused() {
        let d = tempfile::tempdir().unwrap();
        let out = d.path().join("out");
        fs::create_dir(&out).unwrap();
        let z = write(d.path(), "slip.zip", &zip_of(&[("Ok/Ok.toc", b"x"), ("../../evil.lua", b"boom")]));
        assert!(extract_zip(&z, &out, MAX_DOWNLOAD).unwrap_err().contains("unsafe path"));
        assert!(!d.path().join("evil.lua").exists() && !d.path().parent().unwrap().join("evil.lua").exists());

        let z = write(d.path(), "abs.zip", &zip_of(&[("/tmp/evil.lua", b"boom")]));
        assert!(extract_zip(&z, &out, MAX_DOWNLOAD).is_err());

        // A symlink entry (unix mode 120777).
        let mut buf = io::Cursor::new(Vec::new());
        {
            let mut w = zip::ZipWriter::new(&mut buf);
            w.add_symlink("A/link", "/etc/passwd", zip::write::SimpleFileOptions::default()).unwrap();
            w.finish().unwrap();
        }
        let z = write(d.path(), "link.zip", &buf.into_inner());
        assert!(extract_zip(&z, &out, MAX_DOWNLOAD).unwrap_err().contains("symbolic links"));

        let z = write(d.path(), "case.zip", &zip_of(&[("A/x.lua", b"1"), ("a/X.lua", b"2")]));
        assert!(extract_zip(&z, &out, MAX_DOWNLOAD).unwrap_err().contains("upper and lower case"));

        let z = write(d.path(), "notzip.zip", b"PK nonsense");
        assert!(extract_zip(&z, &out, MAX_DOWNLOAD).is_err());
    }

    #[test]
    fn size_caps() {
        let d = tempfile::tempdir().unwrap();
        let out = d.path().join("out");
        fs::create_dir(&out).unwrap();
        let big = vec![b'a'; (MAX_FILE + 1) as usize];
        let z = write(d.path(), "big.zip", &zip_of(&[("A/big.lua", &big)]));
        assert!(extract_zip(&z, &out, MAX_DOWNLOAD).unwrap_err().contains("larger than"));
        let z = write(d.path(), "small.zip", &zip_of(&[("A/a.lua", b"x")]));
        assert!(extract_zip(&z, &out, 10).unwrap_err().contains("larger than"), "the zip itself is capped");
    }

    fn plan_of(entries: &[(&str, &[u8])], build: Build) -> (tempfile::TempDir, Plan) {
        let d = tempfile::tempdir().unwrap();
        let z = write(d.path(), "m.zip", &zip_of(entries));
        let out = d.path().join("out");
        fs::create_dir(&out).unwrap();
        extract_zip(&z, &out, MAX_LOCAL_ZIP).unwrap();
        let p = validate(&walk(&out).unwrap(), build);
        (d, p)
    }

    #[test]
    fn validation_follows_the_ui_rules() {
        // A good plain addon zip.
        let t = toc("Frames", "30300", &["Frames.lua", "Frames.xml"]);
        let xml = br#"<Ui><Script file="Frames.lua"/><Include file='sub\more.xml'/></Ui>"#;
        let (_d, p) = plan_of(
            &[("Frames/Frames.toc", &t), ("Frames/Frames.lua", b"print(1)"), ("Frames/Frames.xml", xml), ("Frames/sub/more.xml", b"<Ui/>"), ("README.md", b"hi")],
            Build::V335a,
        );
        assert!(p.errors.is_empty(), "{:?}", p.errors);
        assert_eq!(p.addons.len(), 1);
        assert_eq!(p.addons[0].title.as_deref(), Some("Frames"), "colour codes stripped");
        assert_eq!(p.skipped, vec!["README.md"]);

        // Game data, by extension and by first bytes; a missing TOC file; a bad XML reference; a wrong Interface.
        let t = toc("Bad", "30300", &["Bad.lua", "Missing.lua"]);
        let (_d, p) = plan_of(
            &[
                ("Bad/Bad.toc", &t),
                ("Bad/Bad.lua", b"x"),
                ("Bad/tex.blp", b"BLP2...."),
                ("Bad/renamed.tga", b"MPQ\x1a...."),
                ("Bad/run.exe", b"MZ"),
                ("Bad/x.xml", br#"<Ui><Script file="..\..\nope.lua"/></Ui>"#),
            ],
            Build::V335a,
        );
        let all = p.errors.join("\n");
        assert!(all.contains("tex.blp is a game texture"), "{all}");
        assert!(all.contains("renamed.tga is an archive of game data (renamed)"), "{all}");
        assert!(all.contains(".exe is not an addon file type"), "{all}");
        assert!(all.contains("lists Missing.lua"), "{all}");
        assert!(all.contains("points to a file that is not in the folder"), "{all}");

        // The Interface number follows the client.
        let t = toc("Old", "11200", &[]);
        let (_d, p) = plan_of(&[("Old/Old.toc", &t)], Build::V335a);
        assert!(p.errors[0].contains("must be 30300") && p.errors[0].contains("1.12 client"), "{:?}", p.errors);
        let (_d, p) = plan_of(&[("Old/Old.toc", &t)], Build::V1121);
        assert!(p.errors.is_empty(), "{:?}", p.errors);
        // Every build has its own number; other builds take no addons.
        for b in Build::KNOWN {
            let t = toc("Frames", b.interface(), &[]);
            let (_d, p) = plan_of(&[("Frames/Frames.toc", &t)], b);
            assert!(p.errors.is_empty(), "{b:?}: {:?}", p.errors);
        }
        let t = toc("Frames", "40300", &[]);
        let (_d, p) = plan_of(&[("Frames/Frames.toc", &t)], Build::V548);
        assert!(p.errors[0].contains("must be 50400") && p.errors[0].contains("the 4.3.4 client"), "{:?}", p.errors);
        let (_d, p) = plan_of(&[("Frames/Frames.toc", &t)], Build::Other);
        assert!(p.errors[0].contains("installs no addons"), "{:?}", p.errors);
        let (_d, p) = plan_of(&[("Patch-A.MPQ", b"MPQ\x1a")], Build::V434);
        assert!(p.patches.is_empty() && p.errors.join(" ").contains("1.12, 2.4.3 and 3.3.5a"), "{:?}", p.errors);
        let (_d, p) = plan_of(&[("Patch-A.MPQ", b"MPQ\x1a")], Build::V243);
        assert_eq!(p.patches.len(), 1, "{:?}", p.errors);

        // Reserved and badly named folders; files outside an addon folder.
        let t = toc("ForeverUI", "30300", &[]);
        let (_d, p) = plan_of(&[("ForeverUI/ForeverUI.toc", &t), ("loose.lua", b"x")], Build::V335a);
        assert!(p.errors.iter().any(|e| e.contains("reserved")));
        assert!(p.errors.iter().any(|e| e.contains("loose.lua")));

        // An Interface/AddOns tree wrapped in a folder; a single addon's own files.
        let t = toc("Deep", "30300", &["Deep.lua"]);
        let (_d, p) = plan_of(&[("pack/Interface/AddOns/Deep/Deep.toc", &t), ("pack/Interface/AddOns/Deep/Deep.lua", b"")], Build::V335a);
        assert!(p.errors.is_empty() && p.addons[0].name == "Deep", "{:?}", p.errors);
        let t = toc("Solo", "30300", &["Solo.lua"]);
        let (_d, p) = plan_of(&[("Solo.toc", &t), ("Solo.lua", b"")], Build::V335a);
        assert!(p.errors.is_empty() && p.addons[0].name == "Solo", "{:?}", p.errors);

        // Nothing usable.
        let (_d, p) = plan_of(&[("notes.txt", b"x"), ("x.lua", b"")], Build::V335a);
        assert!(p.errors[0].contains("no addon found"));
    }

    #[test]
    fn mod_packages_install_their_ui_half_only() {
        let t = toc("WUPings", "30300", &["WUPings.lua"]);
        let mj = br#"{"id":"pings","name":"Pings","version":"0.1.0","author":"WrathUnleashed","licence":"MIT","kind":"both","wu":"1.0","description":"x"}"#;
        let (_d, p) = plan_of(
            &[
                ("pings/mod.json", mj),
                ("pings/ui/WUPings/WUPings.toc", &t),
                ("pings/ui/WUPings/WUPings.lua", b""),
                ("pings/realm/pings.lua", b"-- realm"),
                ("pings/assets/CREDITS.txt", b"x"),
                ("pings/LICENSE", b"MIT"),
            ],
            Build::V335a,
        );
        assert!(p.errors.is_empty(), "{:?}", p.errors);
        assert_eq!(p.meta.as_ref().unwrap().id, "pings");
        assert!(p.warnings.iter().any(|w| w.contains("realm half")));
        assert!(p.skipped.iter().any(|s| s.starts_with("realm/")));
        assert_eq!(local_meta(&p).key, "mod:pings");
        // An archive inside a package breaks the mod format.
        let (_d, p) = plan_of(&[("m/mod.json", mj), ("m/ui/WUPings/WUPings.toc", &t), ("m/ui/WUPings/WUPings.lua", b""), ("m/data.MPQ", b"MPQ\x1a")], Build::V335a);
        assert!(p.errors.iter().any(|e| e.contains("may not hold game archives")), "{:?}", p.errors);
    }

    #[test]
    fn install_disable_enable_uninstall_leaves_nothing() {
        let c = client335();
        let before = tree(c.path());
        let d = tempfile::tempdir().unwrap();
        let t = toc("Frames", "30300", &["Frames.lua", "art/bar.tga"]);
        let z = write(d.path(), "frames.zip", &zip_of(&[("Frames/", b""), ("Frames/Frames.toc", &t), ("Frames/Frames.lua", b"x"), ("Frames/art/bar.tga", b"TGA")]));
        let m = install_local_t(c.path(), Build::V335a, &z).unwrap();
        assert_eq!(m.key, "local:frames");
        assert_eq!(m.version, "1.2.0");
        assert!(c.path().join("Interface/AddOns/Frames/art/bar.tga").is_file());
        assert_eq!(load(c.path()).mods.len(), 1);
        assert!(!c.path().join("Leyline/staging").exists(), "staging is cleaned up");

        set_enabled(c.path(), "local:frames", false).unwrap();
        assert!(!c.path().join("Interface/AddOns/Frames").exists());
        assert!(c.path().join("Leyline/disabled/local_frames/Interface/AddOns/Frames/Frames.toc").is_file());
        set_enabled(c.path(), "local:frames", true).unwrap();
        assert!(c.path().join("Interface/AddOns/Frames/Frames.toc").is_file());
        assert!(!c.path().join("Leyline/disabled").exists());

        // Installing it again replaces it in place (same key).
        install_local_t(c.path(), Build::V335a, &z).unwrap();
        assert_eq!(load(c.path()).mods.len(), 1);

        let r = uninstall(c.path(), "local:frames").unwrap();
        assert_eq!(r.removed_files, 3);
        assert!(r.kept.is_empty());
        assert_eq!(tree(c.path()), before, "the client is exactly as it was");
        assert!(!c.path().join("Interface").exists() && !c.path().join("Leyline").exists());

        // Uninstalling while turned off works too.
        install_local_t(c.path(), Build::V335a, &z).unwrap();
        set_enabled(c.path(), "local:frames", false).unwrap();
        uninstall(c.path(), "local:frames").unwrap();
        assert_eq!(tree(c.path()), before);
    }

    #[test]
    fn files_the_player_added_are_kept() {
        let c = client335();
        let d = tempfile::tempdir().unwrap();
        let t = toc("Frames", "30300", &["Frames.lua"]);
        let z = write(d.path(), "f.zip", &zip_of(&[("Frames/Frames.toc", &t), ("Frames/Frames.lua", b"x")]));
        install_local_t(c.path(), Build::V335a, &z).unwrap();
        touch(c.path(), "Interface/AddOns/Frames/mine.txt", b"my notes");
        let r = uninstall(c.path(), "local:frames").unwrap();
        assert_eq!(r.kept, vec!["Interface/AddOns/Frames/mine.txt"]);
        assert!(c.path().join("Interface/AddOns/Frames/mine.txt").is_file());
    }

    #[test]
    fn an_addon_leyline_did_not_install_is_never_overwritten() {
        let c = client335();
        touch(c.path(), "Interface/AddOns/Frames/Frames.toc", b"## Interface: 30300\n");
        let d = tempfile::tempdir().unwrap();
        let t = toc("Frames", "30300", &["Frames.lua"]);
        let z = write(d.path(), "f.zip", &zip_of(&[("Frames/Frames.toc", &t), ("Frames/Frames.lua", b"x")]));
        let e = install_local_t(c.path(), Build::V335a, &z).unwrap_err();
        assert!(e.contains("Leyline did not put it there"), "{e}");
        assert_eq!(fs::read(c.path().join("Interface/AddOns/Frames/Frames.toc")).unwrap(), b"## Interface: 30300\n");
        assert!(!c.path().join("Interface/AddOns/Frames/Frames.lua").exists());
        // Two mods may not share an addon folder.
        let t2 = toc("Bars", "30300", &[]);
        let z1 = write(d.path(), "a.zip", &zip_of(&[("Bars/Bars.toc", &t2)]));
        install_local_t(c.path(), Build::V335a, &z1).unwrap();
        let mj = br#"{"id":"bars-plus","name":"Bars Plus","version":"1.0.0"}"#;
        let z2 = write(d.path(), "b.zip", &zip_of(&[("mod.json", mj), ("ui/Bars/Bars.toc", &t2)]));
        assert!(install_local_t(c.path(), Build::V335a, &z2).unwrap_err().contains("already installed by"));
    }

    #[cfg(unix)]
    #[test]
    fn never_writes_through_a_link_out_of_the_client() {
        let c = client335();
        let elsewhere = tempfile::tempdir().unwrap();
        fs::create_dir_all(c.path().join("Interface")).unwrap();
        std::os::unix::fs::symlink(elsewhere.path(), c.path().join("Interface/AddOns")).unwrap();
        let d = tempfile::tempdir().unwrap();
        let t = toc("Frames", "30300", &[]);
        let z = write(d.path(), "f.zip", &zip_of(&[("Frames/Frames.toc", &t)]));
        assert!(install_local_t(c.path(), Build::V335a, &z).unwrap_err().contains("link"));
        assert_eq!(fs::read_dir(elsewhere.path()).unwrap().count(), 0);
        // A dropped folder holding a link is refused.
        let src = d.path().join("Linked");
        fs::create_dir(&src).unwrap();
        fs::write(src.join("Linked.toc"), &t).unwrap();
        std::os::unix::fs::symlink("/etc/passwd", src.join("x.lua")).unwrap();
        let c2 = client335();
        assert!(install_local_t(c2.path(), Build::V335a, &src).unwrap_err().contains("symbolic links"));
    }

    #[test]
    fn a_dropped_folder_installs() {
        let c = client335();
        let d = tempfile::tempdir().unwrap();
        let src = d.path().join("Meter");
        fs::create_dir(&src).unwrap();
        fs::write(src.join("Meter.toc"), toc("Meter", "30300", &["Meter.lua"])).unwrap();
        fs::write(src.join("Meter.lua"), b"x").unwrap();
        fs::create_dir(src.join(".git")).unwrap();
        fs::write(src.join(".git/HEAD"), b"ref").unwrap();
        let m = install_local_t(c.path(), Build::V335a, &src).unwrap();
        assert_eq!(m.files, vec!["Interface/AddOns/Meter/Meter.lua", "Interface/AddOns/Meter/Meter.toc"]);
    }

    #[test]
    fn patches_go_to_a_free_data_slot_and_come_out_again() {
        let c = client335();
        let before = tree(c.path());
        touch(c.path(), "Data/patch-4.MPQ", b"MPQ\x1aother");
        let before4 = tree(c.path());
        let d = tempfile::tempdir().unwrap();
        // Its own name (Patch-A) when free.
        let p = write(d.path(), "Patch-A.MPQ", b"MPQ\x1apatch");
        let m = install_local_t(c.path(), Build::V335a, &p).unwrap();
        assert_eq!(m.patches, vec!["Data/patch-A.MPQ"]);
        assert!(m.warnings.iter().any(|w| w.contains("trust")));
        // A zip of a patch with a readme; its name is taken, so the next free slot (4 is the player's own).
        // A zip of the same patch with a readme: the same key, so it replaces the first in its slot.
        let z = write(d.path(), "pz.zip", &zip_of(&[("Patch-A.MPQ", b"MPQ\x1asecond"), ("README.txt", b"read me")]));
        let m2 = install_local_t(c.path(), Build::V335a, &z).unwrap();
        assert_eq!(m2.patches, vec!["Data/patch-A.MPQ"]);
        assert_eq!(load(c.path()).mods.len(), 1);
        assert_eq!(fs::read(c.path().join("Data/patch-A.MPQ")).unwrap(), b"MPQ\x1asecond");
        // Not an MPQ, and the stock names are never handed out.
        let bad = write(d.path(), "patch-B.MPQ", b"nope");
        assert!(install_local_t(c.path(), Build::V335a, &bad).unwrap_err().contains("not an MPQ"));
        assert_eq!(patch_slot_of("patch-2.MPQ"), None);
        assert_eq!(patch_slot_of("PATCH-z.mpq"), Some('Z'));
        // Turn off and on, then remove: the player's own patch-4 stays.
        let key = load(c.path()).mods[0].key.clone();
        set_enabled(c.path(), &key, false).unwrap();
        assert!(!c.path().join("Data/patch-A.MPQ").exists());
        set_enabled(c.path(), &key, true).unwrap();
        uninstall(c.path(), &key).unwrap();
        assert_eq!(tree(c.path()), before4);
        fs::remove_file(c.path().join("Data/patch-4.MPQ")).unwrap();
        assert_eq!(tree(c.path()), before);
    }

    #[test]
    fn a_second_patch_takes_the_next_slot() {
        let c = client335();
        touch(c.path(), "Data/patch-4.MPQ", b"MPQ\x1aother");
        let d = tempfile::tempdir().unwrap();
        let a = write(d.path(), "Patch-A.MPQ", b"MPQ\x1aa");
        install_local_t(c.path(), Build::V335a, &a).unwrap();
        let b = write(d.path(), "custom.mpq", b"MPQ\x1bb");
        let m = install_local_t(c.path(), Build::V335a, &b).unwrap();
        assert_eq!(m.patches, vec!["Data/patch-5.MPQ"], "4 is the player's, A is taken by the other mod");
        assert_eq!(load(c.path()).mods.len(), 2);
    }

    const T: &str = "## Interface: 30300\n## Title: Pings\nWUPings.lua\n";

    fn pings_zip(lua: &[u8]) -> Vec<u8> {
        zip_of(&[
            ("pings/mod.json", br#"{"id":"pings","name":"Pings","version":"0.1.0"}"#),
            ("pings/ui/WUPings/WUPings.toc", T.as_bytes()),
            ("pings/ui/WUPings/WUPings.lua", lua),
            ("pings/realm/pings.lua", b"-- realm"),
        ])
    }

    fn project(base: &str, sha: Option<String>, version: &str) -> Project {
        Project {
            id: "mod:pings".into(),
            source: "packaged".into(),
            name: "Pings".into(),
            builds: vec!["3.3.5a".into()],
            version: Some(version.into()),
            download: Some(format!("{base}/wrath/mods/pings/download")),
            sha256: sha,
            credits: "Pings by WrathUnleashed · MIT".into(),
            ..Default::default()
        }
    }

    #[test]
    fn catalog_install_checks_the_hash_and_shows_updates() {
        let zip = pings_zip(b"-- v1");
        let sha = {
            use sha2::{Digest, Sha256};
            net::hex(&Sha256::digest(&zip))
        };
        let base = serve_routes(vec![("/wrath/mods/pings/download", "200 OK", zip)]);
        let c = client335();
        let before = tree(c.path());

        // A wrong hash installs nothing.
        let e = install_project_t(c.path(), Build::V335a, &project(&base, Some("0".repeat(64)), "0.1.0"), &base).unwrap_err();
        assert!(e.contains("checksum"), "{e}");
        assert_eq!(tree(c.path()), before);

        let m = install_project_t(c.path(), Build::V335a, &project(&base, Some(sha.clone()), "0.1.0"), &base).unwrap();
        assert_eq!((m.key.as_str(), m.source.as_str(), m.version.as_str()), ("mod:pings", "catalog", "0.1.0"));
        assert_eq!(m.sha256, sha);
        assert!(c.path().join("Interface/AddOns/WUPings/WUPings.lua").is_file());
        assert!(!c.path().join("Interface/AddOns/pings").exists(), "the realm half stays out");

        // The catalog moves on: an update shows; the other client is never offered it.
        let newer_p = project(&base, Some(sha.clone()), "0.2.0");
        let v = with_updates(&load(c.path()), std::slice::from_ref(&newer_p), Build::V335a);
        assert_eq!(v[0].update.as_deref(), Some("0.2.0"));
        let v = with_updates(&load(c.path()), &[project(&base, None, "0.1.0")], Build::V335a);
        assert_eq!(v[0].update, None);

        // Wrong client, another site, a community link.
        let v1121 = tempfile::tempdir().unwrap();
        fake_1121(v1121.path(), true);
        assert!(install_project_t(v1121.path(), Build::V1121, &newer_p, &base).unwrap_err().contains("made for the 3.3.5a client"));
        assert!(install_project_t(c.path(), Build::V335a, &newer_p, "https://play.openvanilla.app").unwrap_err().contains("own site"));
        let link = Project { id: "link:3f9a0c12bd47".into(), source: "community".into(), repo: "https://github.com/a/b".into(), ..Default::default() };
        assert!(install_project_t(c.path(), Build::V335a, &link, &base).unwrap_err().contains("community link"));

        uninstall(c.path(), "mod:pings").unwrap();
        assert_eq!(tree(c.path()), before);
    }

    #[test]
    fn a_download_over_the_cap_is_refused() {
        let base = serve_routes(vec![("/big", "200 OK", vec![0u8; 4096])]);
        let d = tempfile::tempdir().unwrap();
        let e = net::download(&format!("{base}/big"), &d.path().join("x"), 1000, net::TIMEOUT, net::TIMEOUT).unwrap_err();
        assert!(e.contains("limit"), "{e}");
        assert!(!d.path().join("x").exists());
    }

    #[test]
    fn versions_compare() {
        assert!(newer("0.2.0", "0.1.9"));
        assert!(newer("1.0", "0.9.9"));
        assert!(newer("launcher-v0.2.0".trim_start_matches("launcher-"), "0.1.0"));
        assert!(!newer("0.1.0", "0.1.0"));
        assert!(!newer("x", "0.1.0"));
        assert_eq!(version_tuple("v1.2.3-beta"), Some((1, 2, 3)));
    }

    #[test]
    fn a_catalog_entry_without_a_checksum_is_refused_and_the_client_is_untouched() {
        let zip = pings_zip(b"-- v1");
        let base = serve_routes(vec![("/wrath/mods/pings/download", "200 OK", zip)]);
        let c = client335();
        let before = tree(c.path());
        let e = install_project_t(c.path(), Build::V335a, &project(&base, None, "0.1.0"), &base).unwrap_err();
        assert!(e.contains("no checksum"), "{e}");
        let e = install_project_t(c.path(), Build::V335a, &project(&base, Some("ab".repeat(32)), "0.1.0"), &base).unwrap_err();
        assert!(e.contains("checksum"), "{e}");
        assert_eq!(tree(c.path()), before, "nothing was written into the client, not even staging");
    }

    #[test]
    fn game_data_is_refused_anywhere_by_its_first_bytes() {
        let t = toc("Frames", "30300", &["Frames.lua"]);
        for (magic, what) in [(&b"MPQ\x1a"[..], "archive"), (b"MD20", "model"), (b"BLP2", "texture"), (b"REVM", "map file"), (b"WDBC", "database")] {
            let mut bytes = magic.to_vec();
            bytes.extend_from_slice(b"rest of the file");
            // In an addon, renamed to an allowed type.
            let (_d, p) = plan_of(&[("Frames/Frames.toc", &t), ("Frames/Frames.lua", b""), ("Frames/art.tga", &bytes)], Build::V335a);
            assert!(p.errors.iter().any(|e| e.contains("art.tga") && e.contains(what) && e.contains("game data")), "{:?}", p.errors);
            // In a part of a package that never goes into a client.
            let mj = br#"{"id":"frames","name":"Frames","version":"1.0.0"}"#;
            let (_d, p) = plan_of(&[("mod.json", mj), ("ui/Frames/Frames.toc", &t), ("ui/Frames/Frames.lua", b""), ("assets/pic.png", &bytes)], Build::V335a);
            assert!(p.errors.iter().any(|e| e.contains("assets/pic.png") && e.contains("game data")), "{:?}", p.errors);
        }
        // A Workshop download may not carry a client patch.
        let zip = zip_of(&[("Patch-A.MPQ", b"MPQ\x1apatch")]);
        let sha = net::hex(&{
            use sha2::{Digest, Sha256};
            Sha256::digest(&zip)
        });
        let base = serve_routes(vec![("/wrath/mods/pings/download", "200 OK", zip)]);
        let c = client335();
        let before = tree(c.path());
        let e = install_project_t(c.path(), Build::V335a, &project(&base, Some(sha), "0.1.0"), &base).unwrap_err();
        assert!(e.contains("game archives"), "{e}");
        assert_eq!(tree(c.path()), before);
    }

    #[test]
    fn secrets_are_refused() {
        // The secret-shaped samples are put together at run time, so this file itself passes the Leyline export's
        // own secret scan (tools/leyline-repo/export.py).
        assert_eq!(secret_in(format!("-----BEGIN {}PRIVATE KEY-----\nabc", "OPENSSH ").as_bytes()), Some("a private key"));
        assert_eq!(secret_in(format!("-----BEGIN {}PRIVATE KEY-----", "RSA ").as_bytes()), Some("a private key"));
        assert_eq!(secret_in(format!("local k = 'AKIA{}'", "ABCDEFGHIJKLMNOP").as_bytes()), Some("a cloud access key"));
        assert_eq!(secret_in(format!("token = \"ghp_{}\"", "a1".repeat(18)).as_bytes()), Some("a GitHub token"));
        assert_eq!(secret_in(format!("x = 'xox{}-1234567890-abcdef'", "b").as_bytes()), Some("a chat bot token"));
        assert_eq!(secret_in(format!("KEY=sk-ant-{}", "A".repeat(40)).as_bytes()), Some("an API key"));
        assert_eq!(secret_in(b"https://discord.com/api/webhooks/123/abc"), Some("a chat webhook address"));
        // Ordinary addon code is fine.
        assert_eq!(secret_in(b"local ask = desk-top; -- BEGIN PUBLIC KEY is fine\nprint('sk-1')\nlocal AKIA = 1"), None);
        assert_eq!(secret_in(b"-----BEGIN CERTIFICATE-----"), None);

        let t = toc("Frames", "30300", &["Frames.lua"]);
        let (_d, p) = plan_of(&[("Frames/Frames.toc", &t), ("Frames/Frames.lua", b"local hook = 'https://discord.com/api/webhooks/1/x'")], Build::V335a);
        assert!(p.errors.iter().any(|e| e.contains("Frames/Frames.lua holds a chat webhook address")), "{:?}", p.errors);
        let (_d, p) = plan_of(&[("Frames/Frames.toc", &t), ("Frames/Frames.lua", b""), ("Frames/.env", b"A=1")], Build::V335a);
        assert!(p.errors.iter().any(|e| e.contains("Frames/.env looks like an environment file")), "{:?}", p.errors);
        let (_d, p) = plan_of(&[("Frames/Frames.toc", &t), ("Frames/Frames.lua", b""), ("WTF/Account/ME/x.lua", b"")], Build::V335a);
        assert!(p.errors.iter().any(|e| e.contains("saved account settings")), "{:?}", p.errors);
        let (_d, p) = plan_of(&[("Frames/Frames.toc", &t), ("Frames/Frames.lua", b""), ("Frames/server.pem", b"x")], Build::V335a);
        assert!(p.errors.iter().any(|e| e.contains("key or certificate")), "{:?}", p.errors);
    }

    #[test]
    fn removal_keeps_files_the_player_changed() {
        let c = client335();
        let d = tempfile::tempdir().unwrap();
        let t = toc("Frames", "30300", &["Frames.lua", "config.lua"]);
        let z = write(d.path(), "f.zip", &zip_of(&[("Frames/Frames.toc", &t), ("Frames/Frames.lua", b"x"), ("Frames/config.lua", b"size = 1")]));
        let m = install_local_t(c.path(), Build::V335a, &z).unwrap();
        assert_eq!(m.hashes.len(), 3, "every file's hash is kept");
        assert_eq!(load(c.path()).mods[0].hashes, m.hashes);
        fs::write(c.path().join("Interface/AddOns/Frames/config.lua"), b"size = 2").unwrap();
        let r = uninstall(c.path(), "local:frames").unwrap();
        assert_eq!(r.removed_files, 2);
        assert_eq!(r.changed, vec!["Interface/AddOns/Frames/config.lua"]);
        assert!(r.kept.is_empty(), "{:?}", r.kept);
        assert_eq!(fs::read(c.path().join("Interface/AddOns/Frames/config.lua")).unwrap(), b"size = 2");
        assert!(!c.path().join("Interface/AddOns/Frames/Frames.lua").exists());
        assert!(load(c.path()).mods.is_empty());

        // Changed while turned off: the player's copy comes back out of Leyline's folder.
        fs::remove_dir_all(c.path().join("Interface")).unwrap();
        install_local_t(c.path(), Build::V335a, &z).unwrap();
        fs::write(c.path().join("Interface/AddOns/Frames/config.lua"), b"size = 3").unwrap();
        set_enabled(c.path(), "local:frames", false).unwrap();
        let r = uninstall(c.path(), "local:frames").unwrap();
        assert_eq!(r.changed, vec!["Interface/AddOns/Frames/config.lua"]);
        assert_eq!(fs::read(c.path().join("Interface/AddOns/Frames/config.lua")).unwrap(), b"size = 3");
        assert!(!c.path().join("Leyline").exists());
    }

    #[test]
    fn an_update_replaces_the_files() {
        let c = client335();
        let before = tree(c.path());
        let mk = |lua: &[u8], extra: bool| {
            let mut e: Vec<(&str, &[u8])> = vec![
                ("pings/mod.json", br#"{"id":"pings","name":"Pings","version":"0.1.0"}"#),
                ("pings/ui/WUPings/WUPings.toc", b"## Interface: 30300\n## Title: Pings\nWUPings.lua\n"),
                ("pings/ui/WUPings/WUPings.lua", lua),
            ];
            if extra {
                e.push(("pings/ui/WUPings/old.lua", b"-- gone in 0.2"));
            }
            zip_of(&e)
        };
        let sha = |z: &[u8]| {
            use sha2::{Digest, Sha256};
            net::hex(&Sha256::digest(z))
        };
        let (v1, v2) = (mk(b"-- v1", true), mk(b"-- v2", false));
        let (s1, s2) = (sha(&v1), sha(&v2));
        let base = serve_routes(vec![("/v1", "200 OK", v1), ("/v2", "200 OK", v2)]);
        let at = |path: &str, sha: &str, ver: &str| Project { download: Some(format!("{base}{path}")), ..project(&base, Some(sha.into()), ver) };

        install_project_t(c.path(), Build::V335a, &at("/v1", &s1, "0.1.0"), &base).unwrap();
        let lua = c.path().join("Interface/AddOns/WUPings/WUPings.lua");
        assert_eq!(fs::read(&lua).unwrap(), b"-- v1");
        let v = with_updates(&load(c.path()), &[at("/v2", &s2, "0.2.0")], Build::V335a);
        assert_eq!(v[0].update.as_deref(), Some("0.2.0"));

        let m = install_project_t(c.path(), Build::V335a, &at("/v2", &s2, "0.2.0"), &base).unwrap();
        assert_eq!(m.version, "0.2.0");
        assert_eq!(fs::read(&lua).unwrap(), b"-- v2", "the file is replaced");
        assert!(!c.path().join("Interface/AddOns/WUPings/old.lua").exists(), "a file the new version dropped is gone");
        assert!(m.kept.is_empty());
        let man = load(c.path());
        assert_eq!(man.mods.len(), 1);
        assert_eq!(man.mods[0].version, "0.2.0");
        assert!(man.mods[0].kept.is_empty() && !fs::read_to_string(manifest_path(c.path())).unwrap().contains("\"kept\""));
        assert_eq!(with_updates(&man, &[at("/v2", &s2, "0.2.0")], Build::V335a)[0].update, None);

        // The player edited a file; the next update keeps their copy next to the new one.
        fs::write(&lua, b"-- mine").unwrap();
        let m = install_project_t(c.path(), Build::V335a, &at("/v1", &s1, "0.1.0"), &base).unwrap();
        assert_eq!(fs::read(&lua).unwrap(), b"-- v1");
        assert_eq!(fs::read(c.path().join("Interface/AddOns/WUPings/WUPings.lua.yours")).unwrap(), b"-- mine");
        assert!(m.kept[0].contains("WUPings.lua.yours"), "{:?}", m.kept);

        let r = uninstall(c.path(), "mod:pings").unwrap();
        assert_eq!(r.kept, vec!["Interface/AddOns/WUPings/WUPings.lua.yours"]);
        fs::remove_dir_all(c.path().join("Interface")).unwrap();
        assert_eq!(tree(c.path()), before);
    }

    #[test]
    fn native_code_needs_a_one_time_ok_and_never_replaces_the_games_files() {
        let c = client335();
        let before = tree(c.path());
        let d = tempfile::tempdir().unwrap();
        // A plain drop: the dll and its settings at the top, a readme skipped.
        let z = write(d.path(), "fix.zip", &zip_of(&[("fix/d3d9.dll", b"MZ\x90\x00dll"), ("fix/fix.conf", b"a=1"), ("fix/README.txt", b"hi")]));
        let e = install_local_t(c.path(), Build::V335a, &z).unwrap_err();
        let json = e.strip_prefix(NATIVE_CONFIRM).expect("asks for the OK first");
        let v: serde_json::Value = serde_json::from_str(json).unwrap();
        assert_eq!(v["files"], serde_json::json!(["d3d9.dll", "fix.conf"]));
        let key = v["key"].as_str().unwrap().to_string();
        let modkey = v["mod"].as_str().unwrap().to_string();
        assert_eq!(tree(c.path()), before, "nothing installed before the OK");

        let m = install_local(c.path(), Build::V335a, &z, &|k| k == key).unwrap();
        assert!(m.native_code);
        assert_eq!(m.natives, vec!["d3d9.dll", "fix.conf"]);
        assert!(m.warnings.iter().any(|w| w.contains("native code")));
        assert_eq!(fs::read(c.path().join("d3d9.dll")).unwrap(), b"MZ\x90\x00dll");
        // Off and on again, then out.
        set_enabled(c.path(), &modkey, false).unwrap();
        assert!(!c.path().join("d3d9.dll").exists());
        set_enabled(c.path(), &modkey, true).unwrap();
        uninstall(c.path(), &modkey).unwrap();
        assert_eq!(tree(c.path()), before);

        // The OK is for these exact native files: the same mod with a changed DLL asks again, the same files don't.
        let mj = br#"{"id":"dx-fix","name":"DX Fix","version":"1.0.0"}"#;
        let v1 = write(d.path(), "dx1.zip", &zip_of(&[("mod.json", mj), ("native/d3d9.dll", b"MZone"), ("native/dx.ini", b"a=1")]));
        let e = install_local_t(c.path(), Build::V335a, &v1).unwrap_err();
        let info: serde_json::Value = serde_json::from_str(e.strip_prefix(NATIVE_CONFIRM).unwrap()).unwrap();
        let ok1 = info["key"].as_str().unwrap().to_string();
        assert_eq!(info["mod"], "mod:dx-fix");
        assert!(ok1.starts_with("mod:dx-fix:") && ok1.len() == "mod:dx-fix:".len() + 16, "{ok1}");
        let oks = std::cell::RefCell::new(vec![ok1.clone()]);
        let allowed = |k: &str| oks.borrow().iter().any(|x| x == k);
        install_local(c.path(), Build::V335a, &v1, &allowed).unwrap();
        let again = write(d.path(), "dx1b.zip", &zip_of(&[("mod.json", mj), ("native/dx.ini", b"a=1"), ("native/d3d9.dll", b"MZone")]));
        install_local(c.path(), Build::V335a, &again, &allowed).expect("the same files: no new question");
        let v2 = write(d.path(), "dx2.zip", &zip_of(&[("mod.json", mj), ("native/d3d9.dll", b"MZtwo"), ("native/dx.ini", b"a=1")]));
        let e = install_local(c.path(), Build::V335a, &v2, &allowed).unwrap_err();
        let info2: serde_json::Value = serde_json::from_str(e.strip_prefix(NATIVE_CONFIRM).expect("a changed DLL asks again")).unwrap();
        let ok2 = info2["key"].as_str().unwrap().to_string();
        assert_ne!(ok1, ok2);
        assert_eq!(fs::read(c.path().join("d3d9.dll")).unwrap(), b"MZone", "the old DLL stays until the new one is OK'd");
        let v3 = write(d.path(), "dx3.zip", &zip_of(&[("mod.json", mj), ("native/d3d9.dll", b"MZone"), ("native/dx.ini", b"a=2")]));
        assert!(install_local(c.path(), Build::V335a, &v3, &allowed).unwrap_err().starts_with(NATIVE_CONFIRM), "changed settings ask too");
        oks.borrow_mut().push(ok2);
        install_local(c.path(), Build::V335a, &v2, &allowed).unwrap();
        assert_eq!(fs::read(c.path().join("d3d9.dll")).unwrap(), b"MZtwo");
        uninstall(c.path(), "mod:dx-fix").unwrap();
        assert_eq!(tree(c.path()), before);
        // A key too long for "<key>:<hex>" still gets a consent key mod_native_confirm takes.
        let long = native_consent_key(&format!("local:{}", "a".repeat(70)), &Plan::default());
        assert!(long.starts_with("native:") && long.len() <= 80, "{long}");

        // A package's native/ folder, with an .asi in a folder Leyline makes and takes away again.
        let mj = br#"{"id":"fps-fix","name":"FPS Fix","version":"1.0.0"}"#;
        let z = write(d.path(), "pkg.zip", &zip_of(&[("mod.json", mj), ("native/scripts/fps.asi", b"MZasi"), ("native/fps.ini", b"x=1")]));
        let m = install_local(c.path(), Build::V335a, &z, &|_| true).unwrap();
        assert_eq!(m.key, "mod:fps-fix");
        assert!(c.path().join("scripts/fps.asi").is_file());
        uninstall(c.path(), "mod:fps-fix").unwrap();
        assert_eq!(tree(c.path()), before);

        // Never over the game's own executable or a file the player has.
        let exe = before.iter().find(|f| f.to_ascii_lowercase().ends_with(".exe") && !f.contains('/')).expect("the fake client has an exe").clone();
        let z = write(d.path(), "bad.zip", &zip_of(&[(exe.as_str(), b"MZevil"), ("x.dll", b"MZ")]));
        let e = install_local(c.path(), Build::V335a, &z, &|_| true).unwrap_err();
        assert!(e.contains("Leyline did not put it there"), "{e}");
        assert_eq!(tree(c.path()), before);
        // Not into Data/, Interface/ or WTF/, and only native file types.
        let z = write(d.path(), "bad2.zip", &zip_of(&[("mod.json", mj), ("native/Data/x.dll", b"MZ"), ("native/run.bat", b"x")]));
        let (_d, p) = (0, validate(&{
            let st = d.path().join("st");
            fs::create_dir_all(&st).unwrap();
            extract_zip(&z, &st, MAX_LOCAL_ZIP).unwrap();
            walk(&st).unwrap()
        }, Build::V335a));
        assert!(p.errors.iter().any(|e| e.contains("may not go into the client's Data folder")), "{:?}", p.errors);
        assert!(p.errors.iter().any(|e| e.contains(".bat is not a native mod file type")), "{:?}", p.errors);
        // The 1.12 client takes native mods too.
        let v1121 = tempfile::tempdir().unwrap();
        fake_1121(v1121.path(), true);
        let z = write(d.path(), "v.zip", &zip_of(&[("nampower.dll", b"MZ")]));
        install_local(v1121.path(), Build::V1121, &z, &|_| true).unwrap();
        assert!(v1121.path().join("nampower.dll").is_file());
    }

    #[test]
    fn xml_references_are_read() {
        let r = xml_refs(r#"<Ui><Script file="a.lua"/><Script
            file = 'b\c.lua'></Script><Include file="x.xml"/><ScriptX file="no"/></Ui>"#);
        assert_eq!(r, vec![("Script".into(), "a.lua".into()), ("Script".into(), "b\\c.lua".into()), ("Include".into(), "x.xml".into())]);
    }
}
