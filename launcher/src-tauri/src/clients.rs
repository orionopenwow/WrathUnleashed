//! Game clients: the player's own installed client folders.
//!
//! Adding a client detects its build (the executable's version resource first, then data-file signatures),
//! checks that the folder looks complete, and finds where its realmlist lives. Leyline never downloads or
//! copies game files; a profile is only a path plus what was detected.

use crate::pe_version::{self, FileVersion};
use serde::{Deserialize, Serialize};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

/// The client builds Leyline knows. Each is the player's OWN install, found by its executable's version; Leyline
/// never downloads a client. A build it does not know is listed as `Other`: it can be started and pointed at a
/// realm (the realm file is guessed from the executable's major version), but no mods are offered for it.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Build {
    /// 1.12.1, build 5875.
    #[serde(rename = "1.12.1")]
    V1121,
    /// 2.4.3, build 8606.
    #[serde(rename = "2.4.3")]
    V243,
    /// 3.3.5a, build 12340.
    #[serde(rename = "3.3.5a")]
    V335a,
    /// 4.3.4, build 15595.
    #[serde(rename = "4.3.4")]
    V434,
    /// 5.4.8, build 18414.
    #[serde(rename = "5.4.8")]
    V548,
    /// Any other build ("other").
    #[serde(rename = "other")]
    Other,
}

/// Where a build reads the realm address from.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RealmFile {
    /// `realmlist.wtf` in the client folder (1.12).
    ClientRoot,
    /// `Data/<locale>/realmlist.wtf` (2.4.3, 3.3.5a); a `realmList` line in `WTF/Config.wtf` is kept in step.
    LocaleData,
    /// `SET realmlist "..."` in `WTF/Config.wtf` (4.3.4, 5.4.8).
    ConfigWtf,
}

/// The newest build Leyline offers. Hidden by the owner on 2026-10-30 ("3.3.5 at max until I research"): 4.3.4 and
/// 5.4.8 stay in the code but are not shown to players or hosts. Set this back to 18414 (or set the environment
/// variable `LEYLINE_ALL_CLIENTS=1`) to show 4.3.4 and 5.4.8 again.
pub const MAX_OFFERED_BUILD: u16 = 12340;
/// The override that shows every known build despite `MAX_OFFERED_BUILD`.
pub const ALL_CLIENTS_ENV: &str = "LEYLINE_ALL_CLIENTS";

/// The override is on (`LEYLINE_ALL_CLIENTS=1`).
pub fn all_clients() -> bool {
    all_clients_from(std::env::var(ALL_CLIENTS_ENV).ok().as_deref())
}
pub fn all_clients_from(v: Option<&str>) -> bool {
    matches!(v.map(str::trim), Some("1" | "true" | "yes" | "on"))
}

impl Build {
    /// The builds Leyline knows, oldest first (offered or not: see `OFFERED`).
    pub const KNOWN: [Build; 5] = [Build::V1121, Build::V243, Build::V335a, Build::V434, Build::V548];

    /// Offered to players and hosts now (`MAX_OFFERED_BUILD`, or every build with `all` / the override).
    pub fn offered_in(self, all: bool) -> bool {
        all || self.number() <= MAX_OFFERED_BUILD
    }
    pub fn offered(self) -> bool {
        self.offered_in(all_clients())
    }
    /// The builds offered now, oldest first.
    pub fn offered_list() -> Vec<Build> {
        Build::KNOWN.into_iter().filter(|b| b.offered()).collect()
    }
    /// The build as a player sees it: a build that is not offered shows as `Other` (it still starts and takes a
    /// realm address, but no mods are offered).
    pub fn shown_in(self, all: bool) -> Build {
        if self.offered_in(all) { self } else { Build::Other }
    }

    /// The build number (0 for other builds).
    pub fn number(self) -> u16 {
        match self {
            Build::V1121 => 5875,
            Build::V243 => 8606,
            Build::V335a => 12340,
            Build::V434 => 15595,
            Build::V548 => 18414,
            Build::Other => 0,
        }
    }
    /// The version as players write it (`3.3.5a`), or `other`.
    pub fn version(self) -> &'static str {
        match self {
            Build::V1121 => "1.12.1",
            Build::V243 => "2.4.3",
            Build::V335a => "3.3.5a",
            Build::V434 => "4.3.4",
            Build::V548 => "5.4.8",
            Build::Other => "other",
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            Build::V1121 => "1.12.1 (5875)",
            Build::V243 => "2.4.3 (8606)",
            Build::V335a => "3.3.5a (12340)",
            Build::V434 => "4.3.4 (15595)",
            Build::V548 => "5.4.8 (18414)",
            Build::Other => "other build",
        }
    }
    /// The executable, as named in a stock install (looked up without regard to case).
    pub fn exe_name(self) -> &'static str {
        match self {
            Build::V1121 | Build::V243 => "WoW.exe",
            _ => "Wow.exe",
        }
    }
    /// The `## Interface:` number an addon for this build has in its .toc ("" for other builds: no addons).
    pub fn interface(self) -> &'static str {
        match self {
            Build::V1121 => "11200",
            Build::V243 => "20400",
            Build::V335a => "30300",
            Build::V434 => "40300",
            Build::V548 => "50400",
            Build::Other => "",
        }
    }
    /// The build whose addons carry this `## Interface:` number.
    pub fn from_interface(n: &str) -> Option<Build> {
        Build::KNOWN.into_iter().find(|b| b.interface() == n.trim())
    }
    /// The build as the Workshop catalog names it (`builds` in all.json).
    pub fn catalog_tag(self) -> &'static str {
        match self {
            Build::V1121 => "1.12",
            Build::V243 => "2.4.3",
            Build::V335a => "3.3.5a",
            Build::V434 => "4.3.4",
            Build::V548 => "5.4.8",
            Build::Other => "other",
        }
    }
    /// A build from a version or build number as catalogs and realm listings write it: `3.3.5a`, `3.3.5`,
    /// `12340`, `1.12`, `1.12.1`, `wrath-3.3.5a`, ... None when it is none of the known builds.
    pub fn from_tag(tag: &str) -> Option<Build> {
        let t = tag.trim().to_ascii_lowercase();
        let t = t.rsplit('-').next().unwrap_or(&t);
        Build::KNOWN.into_iter().find(|b| {
            let v = b.version();
            t == v || t == b.catalog_tag() || t == b.number().to_string() || t == v.trim_end_matches('a')
        })
    }
    /// Client patches (`Data/patch-<X>.MPQ`) work the same way on 1.12, 2.4.3 and 3.3.5a only.
    pub fn takes_mpq_patches(self) -> bool {
        matches!(self, Build::V1121 | Build::V243 | Build::V335a)
    }
    /// It keeps its realmlist and locale archives in `Data/<locale>/`.
    fn has_locale(self) -> bool {
        !matches!(self, Build::V1121)
    }
    /// Where this build reads its realm address. `major` (the executable's major version) decides for other builds.
    pub fn realm_file(self, major: Option<u16>) -> RealmFile {
        match self {
            Build::V1121 => RealmFile::ClientRoot,
            Build::V243 | Build::V335a => RealmFile::LocaleData,
            Build::V434 | Build::V548 => RealmFile::ConfigWtf,
            Build::Other => match major {
                Some(0 | 1) => RealmFile::ClientRoot,
                Some(2 | 3) => RealmFile::LocaleData,
                _ => RealmFile::ConfigWtf,
            },
        }
    }
    /// The build of an executable version: matched on the build number; anything else is `Other`.
    pub fn from_version(v: FileVersion) -> Build {
        Build::KNOWN.into_iter().find(|b| b.number() == v.build && b.version().starts_with(&format!("{}.", v.major))).unwrap_or(Build::Other)
    }
}

/// One client the player added. Stored in the settings file.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ClientProfile {
    pub id: String,
    pub name: String,
    pub path: PathBuf,
    pub build: Build,
    /// The realm address last written to this client's realm file.
    #[serde(default)]
    pub realmlist: String,
    /// The locale folder under Data/ (2.4.3 and newer), such as enUS.
    #[serde(default)]
    pub locale: Option<String>,
    /// The executable's file version (`3.3.5.12340`), when it has one.
    #[serde(default)]
    pub exe_version: Option<String>,
    /// The executable's file name as found in the folder, when it is not the build's usual one.
    #[serde(default)]
    pub exe: Option<String>,
}

impl ClientProfile {
    /// The executable's major version, from `exe_version`.
    pub fn major(&self) -> Option<u16> {
        self.exe_version.as_deref().and_then(|v| v.split('.').next()).and_then(|m| m.parse().ok())
    }
    pub fn realm_file(&self) -> RealmFile {
        self.build.realm_file(self.major())
    }
    /// The executable's file name to start.
    pub fn exe_name(&self) -> &str {
        self.exe.as_deref().unwrap_or(self.build.exe_name())
    }
}

/// How a build was recognised.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DetectedBy {
    ExeVersion,
    DataFiles,
}

/// What looking at a folder found.
#[derive(Debug, Clone, Serialize)]
pub struct Detection {
    pub build: Build,
    pub build_label: &'static str,
    pub detected_by: DetectedBy,
    pub exe: Option<PathBuf>,
    pub exe_version: Option<String>,
    pub locale: Option<String>,
    /// Files a complete install has that this folder lacks. Empty means it looks complete.
    pub missing: Vec<String>,
    pub complete: bool,
    pub realm_file: RealmFile,
    pub realmlist_path: PathBuf,
    /// The realm address the client reads now, if any.
    pub current_realmlist: Option<String>,
    /// The addons' `## Interface:` number ("" for other builds).
    pub interface: &'static str,
}

#[derive(Debug)]
pub enum DetectError {
    NotAFolder,
    Unrecognised,
    Io(io::Error),
}

impl std::fmt::Display for DetectError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DetectError::NotAFolder => write!(f, "That is not a folder."),
            DetectError::Unrecognised => write!(
                f,
                "No game client found here. Pick the folder that holds the game's .exe and its Data folder."
            ),
            DetectError::Io(e) => write!(f, "Could not read the folder: {e}"),
        }
    }
}

impl From<io::Error> for DetectError {
    fn from(e: io::Error) -> Self {
        DetectError::Io(e)
    }
}

/// `dir/name`, matching the name without regard to case (installs copied from Windows keep odd casing).
pub fn find_ci(dir: &Path, name: &str) -> Option<PathBuf> {
    let exact = dir.join(name);
    if exact.exists() {
        return Some(exact);
    }
    let want = name.to_ascii_lowercase();
    fs::read_dir(dir).ok()?.flatten().find_map(|e| {
        (e.file_name().to_string_lossy().to_ascii_lowercase() == want).then(|| e.path())
    })
}

/// A path relative to `root`, each part matched without regard to case.
fn find_rel(root: &Path, rel: &str) -> Option<PathBuf> {
    rel.split('/').try_fold(root.to_path_buf(), |d, part| find_ci(&d, part))
}

const LOCALES: &[&str] = &[
    "enUS", "enGB", "deDE", "frFR", "esES", "esMX", "ruRU", "koKR", "zhCN", "zhTW", "enTW", "enCN", "ptBR", "ptPT",
    "itIT",
];

/// The executables a client folder may have, in the order they are tried (the 32-bit one first: it is the one
/// Wine and older add-on loaders expect).
const EXE_CANDIDATES: &[&str] = &["Wow.exe", "Wow-64.exe"];

/// The locale folder under Data/ (2.4.3 and newer keep realmlist.wtf and the locale archives there).
fn find_locale(data: &Path) -> Option<String> {
    let mut found: Vec<String> = fs::read_dir(data)
        .ok()?
        .flatten()
        .filter(|e| e.path().is_dir())
        .filter_map(|e| {
            let n = e.file_name().to_string_lossy().to_string();
            LOCALES.iter().find(|l| l.eq_ignore_ascii_case(&n)).map(|_| n)
        })
        .collect();
    found.sort();
    // Prefer the folder that actually has a realmlist, then enUS, then the first.
    found
        .iter()
        .find(|l| find_ci(&data.join(l), "realmlist.wtf").is_some())
        .or_else(|| found.iter().find(|l| l.eq_ignore_ascii_case("enUS")))
        .or(found.first())
        .cloned()
}

/// The build from the data files alone (no executable, or one without a version resource).
fn by_data_files(root: &Path) -> Option<Build> {
    let data = find_ci(root, "Data")?;
    let has = |n: &str| find_ci(&data, n).is_some();
    if has("expansion4.MPQ") {
        return Some(Build::V548);
    }
    if has("expansion3.MPQ") {
        return Some(Build::V434);
    }
    if has("lichking.MPQ") || has("common-2.MPQ") {
        return Some(Build::V335a);
    }
    if has("expansion.MPQ") && has("common.MPQ") {
        return Some(Build::V243);
    }
    if has("patch.MPQ") && has("dbc.MPQ") && !has("expansion.MPQ") && !has("common.MPQ") {
        return Some(Build::V1121);
    }
    None
}

/// The files a complete install of `build` has, relative to the client folder.
fn required(build: Build, locale: Option<&str>) -> Vec<String> {
    let data: &[&str] = match build {
        Build::V1121 => &[
            "dbc.MPQ", "fonts.MPQ", "interface.MPQ", "misc.MPQ", "model.MPQ", "patch.MPQ", "sound.MPQ",
            "speech.MPQ", "terrain.MPQ", "texture.MPQ", "wmo.MPQ",
        ],
        Build::V243 => &["common.MPQ", "expansion.MPQ", "patch.MPQ"],
        Build::V335a => &["common.MPQ", "common-2.MPQ", "expansion.MPQ", "lichking.MPQ", "patch.MPQ", "patch-2.MPQ"],
        Build::V434 => &["art.MPQ", "expansion1.MPQ", "expansion2.MPQ", "expansion3.MPQ", "world.MPQ"],
        Build::V548 => &["expansion1.MPQ", "expansion2.MPQ", "expansion3.MPQ", "expansion4.MPQ", "world.MPQ"],
        Build::Other => &[],
    };
    let mut v: Vec<String> = data.iter().map(|f| format!("Data/{f}")).collect();
    if build != Build::Other && build.has_locale() {
        match (build, locale) {
            (Build::V243 | Build::V335a, Some(l)) => v.push(format!("Data/{l}/locale-{l}.MPQ")),
            (_, Some(l)) => v.push(format!("Data/{l}")),
            (_, None) => v.push("Data/<locale>/".into()),
        }
    }
    v.insert(0, build.exe_name().to_string());
    v
}

/// What the UI shows for a missing file: the executable is named generically (its real file name carries a
/// brand word), data files by their path so the player can find them.
pub const EXE_LABEL: &str = "the game's .exe";
fn shown(rel: String) -> String {
    if rel.to_ascii_lowercase().ends_with(".exe") {
        EXE_LABEL.to_string()
    } else {
        rel
    }
}

/// Where a client reads its realm address from, by its realm-file rule.
pub fn realm_file_path(root: &Path, rule: RealmFile, locale: Option<&str>) -> PathBuf {
    match rule {
        RealmFile::LocaleData => {
            let l = locale.unwrap_or("enUS");
            let dir = find_rel(root, &format!("Data/{l}")).unwrap_or_else(|| root.join("Data").join(l));
            find_ci(&dir, "realmlist.wtf").unwrap_or_else(|| dir.join("realmlist.wtf"))
        }
        RealmFile::ClientRoot => find_ci(root, "realmlist.wtf").unwrap_or_else(|| root.join("realmlist.wtf")),
        RealmFile::ConfigWtf => config_wtf(root),
    }
}

/// `WTF/Config.wtf`, found without regard to case, or where it would be.
fn config_wtf(root: &Path) -> PathBuf {
    find_rel(root, "WTF/Config.wtf").unwrap_or_else(|| find_ci(root, "WTF").unwrap_or_else(|| root.join("WTF")).join("Config.wtf"))
}

/// Where this build reads its realmlist from (other builds: by their executable's major version, see
/// `ClientProfile::realm_file`).
pub fn realmlist_path(root: &Path, build: Build, locale: Option<&str>) -> PathBuf {
    realm_file_path(root, build.realm_file(None), locale)
}

/// The realm file of a profile.
pub fn profile_realm_file(p: &ClientProfile) -> PathBuf {
    realm_file_path(&p.path, p.realm_file(), p.locale.as_deref())
}

/// Look at a folder and say which client it is. An executable of a build Leyline does not know is `Other`.
pub fn detect(root: &Path) -> Result<Detection, DetectError> {
    detect_in(root, all_clients())
}

/// `detect`, with every known build shown when `all` (else a build that is not offered is `Other`).
pub fn detect_in(root: &Path, all: bool) -> Result<Detection, DetectError> {
    if !root.is_dir() {
        return Err(DetectError::NotAFolder);
    }
    // 1. The executable's version resource.
    let mut exe_version = None;
    let mut exe = None;
    let mut build = None;
    let mut detected_by = DetectedBy::ExeVersion;
    for name in EXE_CANDIDATES {
        if let Some(p) = find_ci(root, name) {
            if exe.is_none() {
                exe = Some(p.clone());
            }
            if let Some(v) = pe_version::read(&p)? {
                exe_version = Some(v.to_string());
                build = Some(Build::from_version(v));
                exe = Some(p);
                break;
            }
        }
    }
    // 2. The data-file signatures (no executable, or one without a version resource).
    if build.is_none() {
        build = by_data_files(root);
        detected_by = DetectedBy::DataFiles;
    }
    let build = build.ok_or(DetectError::Unrecognised)?.shown_in(all);
    let major = exe_version.as_deref().and_then(|v| v.split('.').next()).and_then(|m| m.parse::<u16>().ok());
    let rule = build.realm_file(major);
    let locale = match (build, rule) {
        (Build::V1121, _) | (Build::Other, RealmFile::ClientRoot) => None,
        _ => find_ci(root, "Data").and_then(|d| find_locale(&d)),
    };
    let missing: Vec<String> = required(build, locale.as_deref())
        .into_iter()
        .filter(|rel| {
            if rel.to_ascii_lowercase().ends_with(".exe") {
                return exe.is_none();
            }
            rel.contains('<') || find_rel(root, rel).is_none()
        })
        .map(shown)
        .collect();
    let rl = realm_file_path(root, rule, locale.as_deref());
    let current_realmlist = fs::read_to_string(&rl).ok().and_then(|t| parse_realmlist(&t));
    Ok(Detection {
        build,
        build_label: build.label(),
        detected_by,
        exe,
        exe_version,
        locale,
        complete: missing.is_empty(),
        missing,
        realm_file: rule,
        realmlist_path: rl,
        current_realmlist,
        interface: build.interface(),
    })
}

/// The address in a realmlist.wtf (`set realmlist <host>`) or a Config.wtf (`SET realmlist "<host>"`).
pub fn parse_realmlist(text: &str) -> Option<String> {
    text.lines().find_map(|l| {
        let mut w = l.split_whitespace();
        let (a, b) = (w.next()?, w.next()?);
        (a.eq_ignore_ascii_case("set") && b.eq_ignore_ascii_case("realmlist"))
            .then(|| w.next().map(|h| h.trim_matches('"').to_string()))
            .flatten()
    })
}

/// A realm address must be a plain host or host:port: nothing that could break out of the file.
pub fn valid_realm_address(addr: &str) -> bool {
    !addr.is_empty()
        && addr.len() <= 253
        && addr.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | ':' | '_'))
}

/// `text` with its realmlist line set to `addr` (added when missing). Other lines, such as patchlist, stay.
pub fn with_realmlist(text: &str, addr: &str) -> String {
    let line = format!("set realmlist {addr}");
    let mut done = false;
    let mut out: Vec<String> = Vec::new();
    for l in text.lines() {
        if parse_realmlist(l).is_some() {
            // The first realmlist line is replaced; any later ones are dropped (the client reads only one).
            if !done {
                out.push(line.clone());
                done = true;
            }
        } else {
            out.push(l.to_string());
        }
    }
    if !done {
        out.insert(0, line);
    }
    let mut s = out.join("\r\n");
    s.push_str("\r\n");
    s
}

/// The backup kept next to a realm file the first time Leyline changes it.
pub fn backup_path(rl: &Path) -> PathBuf {
    let mut n = rl.file_name().map(|n| n.to_os_string()).unwrap_or_default();
    n.push(".leyline-backup");
    rl.with_file_name(n)
}

/// Read a file to change, keeping the player's original as a backup the first time. A missing file is "" (its
/// folder is made).
fn read_with_backup(p: &Path) -> io::Result<String> {
    match fs::read_to_string(p) {
        Ok(t) => {
            let bak = backup_path(p);
            if !bak.exists() {
                fs::write(&bak, &t)?;
            }
            Ok(t)
        }
        Err(e) if e.kind() == io::ErrorKind::NotFound => {
            if let Some(d) = p.parent() {
                fs::create_dir_all(d)?;
            }
            Ok(String::new())
        }
        Err(e) => Err(e),
    }
}

/// Point a client at a realm, keeping the player's original file as a backup (made once, the first time, so it
/// always holds the file as it was before Leyline).
///
/// * 1.12: `realmlist.wtf` in the client folder.
/// * 2.4.3, 3.3.5a: `Data/<locale>/realmlist.wtf`; a `realmList` line in `WTF/Config.wtf` overrides it, so when
///   there is one it is updated too (with its own backup).
/// * 4.3.4, 5.4.8: the `SET realmlist "..."` line in `WTF/Config.wtf` (added when missing).
pub fn write_realmlist(profile: &ClientProfile, addr: &str) -> io::Result<PathBuf> {
    if !valid_realm_address(addr) {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, format!("not a realm address: {addr:?}")));
    }
    let rule = profile.realm_file();
    let rl = profile_realm_file(profile);
    let old = read_with_backup(&rl)?;
    match rule {
        RealmFile::ConfigWtf => {
            crate::settings::write_atomic(&rl, config_wtf_with_realmlist(&old, addr, true).unwrap_or_default().as_bytes())?;
        }
        RealmFile::ClientRoot | RealmFile::LocaleData => {
            crate::settings::write_atomic(&rl, with_realmlist(&old, addr).as_bytes())?;
        }
    }
    if rule == RealmFile::LocaleData {
        if let Some(cfg) = find_rel(&profile.path, "WTF/Config.wtf") {
            let text = fs::read_to_string(&cfg)?;
            if let Some(new) = config_wtf_with_realmlist(&text, addr, false) {
                let bak = backup_path(&cfg);
                if !bak.exists() {
                    fs::write(&bak, &text)?;
                }
                crate::settings::write_atomic(&cfg, new.as_bytes())?;
            }
        }
    }
    Ok(rl)
}

/// Config.wtf with its `SET realmlist "..."` line changed (the key keeps its spelling, such as `realmList`).
/// When it has no such line: None, or with `add` the line appended.
fn config_wtf_with_realmlist(text: &str, addr: &str, add: bool) -> Option<String> {
    let mut hit = false;
    let mut lines: Vec<String> = Vec::new();
    for l in text.lines() {
        let mut w = l.split_whitespace();
        match (w.next(), w.next()) {
            (Some(a), Some(b)) if a.eq_ignore_ascii_case("SET") && b.eq_ignore_ascii_case("realmList") => {
                if !hit {
                    lines.push(format!("SET {b} \"{addr}\""));
                }
                hit = true;
            }
            _ => lines.push(l.to_string()),
        }
    }
    if !hit {
        if !add {
            return None;
        }
        lines.push(format!("SET realmlist \"{addr}\""));
    }
    Some(lines.join("\r\n") + "\r\n")
}

/// Put back the realm file(s) the player had before Leyline first changed them. Returns false when there is no
/// backup (Leyline never changed this client's realm address).
pub fn restore_realmlist(profile: &ClientProfile) -> io::Result<bool> {
    let rl = profile_realm_file(profile);
    let bak = backup_path(&rl);
    if !bak.is_file() {
        return Ok(false);
    }
    crate::settings::write_atomic(&rl, &fs::read(&bak)?)?;
    if profile.realm_file() == RealmFile::LocaleData {
        if let Some(cfg) = find_rel(&profile.path, "WTF/Config.wtf") {
            let cbak = backup_path(&cfg);
            if cbak.is_file() {
                crate::settings::write_atomic(&cfg, &fs::read(&cbak)?)?;
            }
        }
    }
    Ok(true)
}

/// Read the realm address a client is pointed at now.
pub fn read_realmlist(profile: &ClientProfile) -> Option<String> {
    fs::read_to_string(profile_realm_file(profile)).ok().and_then(|t| parse_realmlist(&t))
}

/// A new profile from a detection. The id is unique among `existing` ids.
pub fn new_profile(path: &Path, det: &Detection, existing: &[ClientProfile]) -> ClientProfile {
    let base = format!("c{}", det.build.version().replace('.', ""));
    let id = (1..)
        .map(|n| format!("{base}-{n}"))
        .find(|id| !existing.iter().any(|p| &p.id == id))
        .unwrap();
    let folder = path.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
    let label = match (det.build, &det.exe_version) {
        (Build::Other, Some(v)) => format!("other build {v}"),
        (b, _) => b.label().to_string(),
    };
    let exe = det
        .exe
        .as_ref()
        .and_then(|p| p.file_name())
        .map(|n| n.to_string_lossy().to_string())
        .filter(|n| !n.eq_ignore_ascii_case(det.build.exe_name()));
    ClientProfile {
        id,
        name: if folder.is_empty() { label } else { format!("{folder} ({label})") },
        path: path.to_path_buf(),
        build: det.build,
        realmlist: det.current_realmlist.clone().unwrap_or_default(),
        locale: det.locale.clone(),
        exe_version: det.exe_version.clone(),
        exe,
    }
}

#[cfg(test)]
pub mod testutil {
    use super::*;

    pub fn touch(root: &Path, rel: &str, bytes: &[u8]) {
        let p = root.join(rel);
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(p, bytes).unwrap();
    }

    /// A fake 3.3.5a folder: empty placeholder files, no game data.
    pub fn fake_335a(root: &Path, with_exe_version: bool) {
        let exe = if with_exe_version { pe_version::fake_exe(3, 3, 5, 12340) } else { b"MZ".to_vec() };
        touch(root, "Wow.exe", &exe);
        for f in ["common.MPQ", "common-2.MPQ", "expansion.MPQ", "lichking.MPQ", "patch.MPQ", "patch-2.MPQ"] {
            touch(root, &format!("Data/{f}"), b"");
        }
        touch(root, "Data/enUS/locale-enUS.MPQ", b"");
        touch(root, "Data/enUS/realmlist.wtf", b"set realmlist logon.example.org\r\nset patchlist localhost\r\n");
    }

    /// A fake client of any known build: placeholder files only, its realm file says old.example.org.
    pub fn fake_client(root: &Path, b: Build, with_exe_version: bool) {
        match b {
            Build::V1121 => return fake_1121(root, with_exe_version),
            Build::V335a => {
                fake_335a(root, with_exe_version);
                return touch(root, "Data/enUS/realmlist.wtf", b"set realmlist old.example.org\r\n");
            }
            _ => {}
        }
        let (ma, mi, pa) = match b {
            Build::V243 => (2, 4, 3),
            Build::V434 => (4, 3, 4),
            _ => (5, 4, 8),
        };
        let exe = if with_exe_version { pe_version::fake_exe(ma, mi, pa, b.number()) } else { b"MZ".to_vec() };
        touch(root, b.exe_name(), &exe);
        for f in required(b, Some("enUS")).iter().skip(1) {
            if f.ends_with(".MPQ") {
                touch(root, f, b"");
            } else {
                fs::create_dir_all(root.join(f)).unwrap();
            }
        }
        match b.realm_file(None) {
            RealmFile::ConfigWtf => touch(root, "WTF/Config.wtf", b"SET gxApi \"d3d9\"\r\nSET realmlist \"old.example.org\"\r\n"),
            _ => touch(root, "Data/enUS/realmlist.wtf", b"set realmlist old.example.org\r\n"),
        }
    }

    pub fn fake_1121(root: &Path, with_exe_version: bool) {
        let exe = if with_exe_version { pe_version::fake_exe(1, 12, 1, 5875) } else { b"MZ".to_vec() };
        touch(root, "WoW.exe", &exe);
        for f in [
            "dbc.MPQ", "fonts.MPQ", "interface.MPQ", "misc.MPQ", "model.MPQ", "patch.MPQ", "sound.MPQ",
            "speech.MPQ", "terrain.MPQ", "texture.MPQ", "wmo.MPQ",
        ] {
            touch(root, &format!("Data/{f}"), b"");
        }
        touch(root, "realmlist.wtf", b"set realmlist old.example.org\n");
    }
}

#[cfg(test)]
mod tests {
    use super::testutil::*;
    use super::*;

    /// These tests cover every known build, offered or not (see `capped_at_335a_until_the_override` for the cap).
    fn detect(root: &Path) -> Result<Detection, DetectError> {
        detect_in(root, true)
    }

    #[test]
    fn capped_at_335a_until_the_override() {
        assert_eq!(MAX_OFFERED_BUILD, 12340, "hidden by the owner on 2026-10-30: 4.3.4 and 5.4.8 are not offered");
        let shown: Vec<Build> = Build::KNOWN.into_iter().filter(|b| b.offered_in(false)).collect();
        assert_eq!(shown, vec![Build::V1121, Build::V243, Build::V335a]);
        assert!(Build::KNOWN.into_iter().all(|b| b.offered_in(true)), "the override brings 4.3.4 and 5.4.8 back");
        assert!(Build::Other.offered_in(false));
        assert_eq!(Build::V434.shown_in(false), Build::Other);
        assert_eq!(Build::V548.shown_in(true), Build::V548);
        for v in ["1", "true", " yes "] {
            assert!(all_clients_from(Some(v)));
        }
        for v in [None, Some(""), Some("0"), Some("no")] {
            assert!(!all_clients_from(v));
        }
        // A 4.3.4 or 5.4.8 folder is listed as an other build (it still starts and takes a realm address).
        for b in [Build::V434, Build::V548] {
            let d = tempfile::tempdir().unwrap();
            fake_client(d.path(), b, true);
            let det = detect_in(d.path(), false).unwrap();
            assert_eq!((det.build, det.realm_file), (Build::Other, RealmFile::ConfigWtf), "{b:?}");
            assert_eq!(detect_in(d.path(), true).unwrap().build, b);
        }
    }

    #[test]
    fn detects_335a_from_the_exe_version() {
        let d = tempfile::tempdir().unwrap();
        fake_335a(d.path(), true);
        let det = detect(d.path()).unwrap();
        assert_eq!(det.build, Build::V335a);
        assert_eq!(det.detected_by, DetectedBy::ExeVersion);
        assert_eq!(det.exe_version.as_deref(), Some("3.3.5.12340"));
        assert_eq!(det.locale.as_deref(), Some("enUS"));
        assert!(det.complete, "{:?}", det.missing);
        assert_eq!(det.current_realmlist.as_deref(), Some("logon.example.org"));
        assert!(det.realmlist_path.ends_with("Data/enUS/realmlist.wtf"));
    }

    #[test]
    fn detects_1121_from_data_files_when_the_exe_has_no_version() {
        let d = tempfile::tempdir().unwrap();
        fake_1121(d.path(), false);
        let det = detect(d.path()).unwrap();
        assert_eq!(det.build, Build::V1121);
        assert_eq!(det.detected_by, DetectedBy::DataFiles);
        assert!(det.complete, "{:?}", det.missing);
        assert!(det.realmlist_path.ends_with("realmlist.wtf"));
        assert_eq!(det.current_realmlist.as_deref(), Some("old.example.org"));
    }

    #[test]
    fn detects_335a_by_common2_without_an_exe() {
        let d = tempfile::tempdir().unwrap();
        touch(d.path(), "data/COMMON-2.mpq", b"");
        let det = detect(d.path()).unwrap();
        assert_eq!(det.build, Build::V335a);
        assert!(!det.complete);
        assert!(det.missing.contains(&EXE_LABEL.to_string()));
    }

    #[test]
    fn data_with_expansion_is_not_1121() {
        let d = tempfile::tempdir().unwrap();
        for f in ["patch.MPQ", "dbc.MPQ", "expansion.MPQ"] {
            touch(d.path(), &format!("Data/{f}"), b"");
        }
        assert!(matches!(detect(d.path()), Err(DetectError::Unrecognised)));
    }

    #[test]
    fn unknown_builds_are_listed_as_other() {
        let d = tempfile::tempdir().unwrap();
        touch(d.path(), "Wow.exe", &pe_version::fake_exe(7, 3, 5, 26972));
        touch(d.path(), "Data/enUS/realmlist.wtf", b"");
        let det = detect(d.path()).unwrap();
        assert_eq!(det.build, Build::Other);
        assert_eq!(det.exe_version.as_deref(), Some("7.3.5.26972"));
        assert_eq!(det.realm_file, RealmFile::ConfigWtf, "a newer major reads Config.wtf");
        assert_eq!(det.interface, "");
        let p = new_profile(d.path(), &det, &[]);
        assert!(p.id.starts_with("cother-") && p.name.contains("other build 7.3.5.26972"), "{p:?}");
        // An old major reads the realmlist next to the game.
        let o = tempfile::tempdir().unwrap();
        touch(o.path(), "WoW.exe", &pe_version::fake_exe(1, 11, 2, 5464));
        let det = detect(o.path()).unwrap();
        assert_eq!((det.build, det.realm_file), (Build::Other, RealmFile::ClientRoot));
        let e = tempfile::tempdir().unwrap();
        assert!(matches!(detect(e.path()), Err(DetectError::Unrecognised)));
        assert!(matches!(detect(&e.path().join("nope")), Err(DetectError::NotAFolder)));
    }

    #[test]
    fn detects_every_build_by_its_executable() {
        for (b, (ma, mi, pa)) in Build::KNOWN.into_iter().zip([(1, 12, 1), (2, 4, 3), (3, 3, 5), (4, 3, 4), (5, 4, 8)]) {
            let d = tempfile::tempdir().unwrap();
            fake_client(d.path(), b, true);
            let det = detect(d.path()).unwrap();
            assert_eq!(det.build, b);
            assert_eq!(det.detected_by, DetectedBy::ExeVersion);
            assert_eq!(det.exe_version, Some(format!("{ma}.{mi}.{pa}.{}", b.number())));
            assert!(det.complete, "{b:?}: {:?}", det.missing);
            assert_eq!(det.locale.is_some(), b != Build::V1121, "{b:?}");
            // The same folder without a version resource: the data files tell.
            let n = tempfile::tempdir().unwrap();
            fake_client(n.path(), b, false);
            let det = detect(n.path()).unwrap();
            assert_eq!((det.build, det.detected_by), (b, DetectedBy::DataFiles), "{b:?}");
        }
        assert_eq!(Build::KNOWN.map(|b| b.number()), [5875, 8606, 12340, 15595, 18414]);
        assert_eq!(Build::KNOWN.map(|b| b.interface()), ["11200", "20400", "30300", "40300", "50400"]);
        assert_eq!(Build::from_interface("40300"), Some(Build::V434));
        assert_eq!(Build::from_tag("wrath-3.3.5a"), Some(Build::V335a));
        assert_eq!(Build::from_tag("3.3.5"), Some(Build::V335a));
        assert_eq!(Build::from_tag("1.12"), Some(Build::V1121));
        assert_eq!(Build::from_tag("18414"), Some(Build::V548));
        assert_eq!(Build::from_tag("9.9.9"), None);
        // A 64-bit only folder is found too, and remembered.
        let d = tempfile::tempdir().unwrap();
        fake_client(d.path(), Build::V548, true);
        fs::rename(d.path().join("Wow.exe"), d.path().join("Wow-64.exe")).unwrap();
        let det = detect(d.path()).unwrap();
        assert_eq!(det.build, Build::V548);
        let p = new_profile(d.path(), &det, &[]);
        assert_eq!((p.id.as_str(), p.exe_name()), ("c548-1", "Wow-64.exe"));
    }

    #[test]
    fn realm_file_rules_per_build() {
        let want = [
            (Build::V1121, RealmFile::ClientRoot, "realmlist.wtf"),
            (Build::V243, RealmFile::LocaleData, "Data/enUS/realmlist.wtf"),
            (Build::V335a, RealmFile::LocaleData, "Data/enUS/realmlist.wtf"),
            (Build::V434, RealmFile::ConfigWtf, "WTF/Config.wtf"),
            (Build::V548, RealmFile::ConfigWtf, "WTF/Config.wtf"),
        ];
        for (b, rule, rel) in want {
            let d = tempfile::tempdir().unwrap();
            fake_client(d.path(), b, true);
            let det = detect(d.path()).unwrap();
            assert_eq!(det.realm_file, rule, "{b:?}");
            assert_eq!(det.realmlist_path, d.path().join(rel), "{b:?}");
            assert_eq!(det.current_realmlist.as_deref(), Some("old.example.org"), "{b:?}");
            let p = new_profile(d.path(), &det, &[]);
            let rl = write_realmlist(&p, "relay.openvanilla.app:40002").unwrap();
            assert_eq!(rl, d.path().join(rel));
            assert_eq!(read_realmlist(&p).as_deref(), Some("relay.openvanilla.app:40002"), "{b:?}");
            let text = fs::read_to_string(&rl).unwrap();
            if rule == RealmFile::ConfigWtf {
                assert!(text.contains("SET realmlist \"relay.openvanilla.app:40002\"") && text.contains("SET gxApi"), "{text}");
                assert_eq!(text.matches("realmlist").count(), 1, "{text}");
            } else {
                assert!(text.starts_with("set realmlist relay.openvanilla.app:40002"), "{text}");
            }
            assert!(fs::read_to_string(backup_path(&rl)).unwrap().contains("old.example.org"), "{b:?}");
            write_realmlist(&p, "play.openvanilla.app").unwrap();
            assert!(restore_realmlist(&p).unwrap());
            assert_eq!(read_realmlist(&p).as_deref(), Some("old.example.org"), "{b:?}");
        }
        // 4.3.4 without a Config.wtf yet: it is made, with only the realm line; nothing to put back.
        let d = tempfile::tempdir().unwrap();
        fake_client(d.path(), Build::V434, true);
        fs::remove_file(d.path().join("WTF/Config.wtf")).unwrap();
        let p = new_profile(d.path(), &detect(d.path()).unwrap(), &[]);
        write_realmlist(&p, "play.openvanilla.app").unwrap();
        assert_eq!(fs::read_to_string(d.path().join("WTF/Config.wtf")).unwrap(), "SET realmlist \"play.openvanilla.app\"\r\n");
        assert!(!restore_realmlist(&p).unwrap());
    }

    #[test]
    fn reports_missing_files() {
        let d = tempfile::tempdir().unwrap();
        fake_335a(d.path(), true);
        fs::remove_file(d.path().join("Data/expansion.MPQ")).unwrap();
        let det = detect(d.path()).unwrap();
        assert!(!det.complete);
        assert_eq!(det.missing, vec!["Data/expansion.MPQ".to_string()]);
    }

    #[test]
    fn realmlist_text() {
        assert_eq!(parse_realmlist("SET realmlist \"a.b\"\n"), Some("a.b".into()));
        assert_eq!(parse_realmlist("set patchlist x\n"), None);
        assert_eq!(with_realmlist("", "play.openvanilla.app"), "set realmlist play.openvanilla.app\r\n");
        assert_eq!(
            with_realmlist("set realmlist a\nset patchlist p\nset realmlist b\n", "c"),
            "set realmlist c\r\nset patchlist p\r\n"
        );
        assert!(valid_realm_address("play.openvanilla.app"));
        assert!(valid_realm_address("127.0.0.1:3724"));
        assert!(!valid_realm_address("a\nset x"));
        assert!(!valid_realm_address("a b"));
        assert!(!valid_realm_address(""));
    }

    #[test]
    fn writes_realmlist_with_a_backup_for_both_builds() {
        let d = tempfile::tempdir().unwrap();
        fake_335a(d.path(), true);
        touch(d.path(), "WTF/Config.wtf", b"SET locale \"enUS\"\r\nSET realmList \"old.example.org\"\r\n");
        let det = detect(d.path()).unwrap();
        let p = new_profile(d.path(), &det, &[]);
        let rl = write_realmlist(&p, "play.openvanilla.app").unwrap();
        assert_eq!(read_realmlist(&p).as_deref(), Some("play.openvanilla.app"));
        let text = fs::read_to_string(&rl).unwrap();
        assert!(text.contains("set patchlist localhost"));
        let bak = fs::read_to_string(backup_path(&rl)).unwrap();
        assert!(bak.contains("logon.example.org"));
        // A second write keeps the first backup (the player's original).
        write_realmlist(&p, "other.example.org").unwrap();
        assert!(fs::read_to_string(backup_path(&rl)).unwrap().contains("logon.example.org"));
        let cfg = fs::read_to_string(d.path().join("WTF/Config.wtf")).unwrap();
        assert!(cfg.contains("SET realmList \"other.example.org\"") && cfg.contains("SET locale"));
        assert!(write_realmlist(&p, "bad\naddr").is_err());

        let v = tempfile::tempdir().unwrap();
        fake_1121(v.path(), true);
        let p = new_profile(v.path(), &detect(v.path()).unwrap(), &[]);
        assert_eq!(p.build, Build::V1121);
        let rl = write_realmlist(&p, "play.openvanilla.app").unwrap();
        assert_eq!(rl, v.path().join("realmlist.wtf"));
        assert_eq!(read_realmlist(&p).as_deref(), Some("play.openvanilla.app"));
        assert!(backup_path(&rl).exists());
    }

    #[test]
    fn hopping_realms_and_back_then_restoring_the_original() {
        let d = tempfile::tempdir().unwrap();
        fake_335a(d.path(), true);
        touch(d.path(), "WTF/Config.wtf", b"SET realmList \"logon.example.org\"\r\nSET gxApi \"d3d9\"\r\n");
        let p = new_profile(d.path(), &detect(d.path()).unwrap(), &[]);
        // Official, then a Beacon on the relay (host:port), then back to the official realm.
        for addr in ["play.openvanilla.app", "relay.openvanilla.app:40002", "play.openvanilla.app"] {
            write_realmlist(&p, addr).unwrap();
            assert_eq!(read_realmlist(&p).as_deref(), Some(addr));
            let cfg = fs::read_to_string(d.path().join("WTF/Config.wtf")).unwrap();
            assert!(cfg.contains(&format!("SET realmList \"{addr}\"")) && cfg.contains("gxApi"), "{cfg}");
        }
        // The player's own files come back, Config.wtf too.
        assert!(restore_realmlist(&p).unwrap());
        assert_eq!(read_realmlist(&p).as_deref(), Some("logon.example.org"));
        assert!(fs::read_to_string(d.path().join("WTF/Config.wtf")).unwrap().contains("logon.example.org"));

        let v = tempfile::tempdir().unwrap();
        fake_1121(v.path(), true);
        let p = new_profile(v.path(), &detect(v.path()).unwrap(), &[]);
        assert!(!restore_realmlist(&p).unwrap(), "nothing to restore before Leyline changed it");
        write_realmlist(&p, "beacon.example.org:40010").unwrap();
        assert!(restore_realmlist(&p).unwrap());
        assert_eq!(read_realmlist(&p).as_deref(), Some("old.example.org"));
        assert_eq!(Build::V1121.interface(), "11200");
        assert_eq!(Build::V335a.catalog_tag(), "3.3.5a");
    }

    #[test]
    fn profile_ids_are_unique() {
        let d = tempfile::tempdir().unwrap();
        fake_335a(d.path(), true);
        let det = detect(d.path()).unwrap();
        let a = new_profile(d.path(), &det, &[]);
        let b = new_profile(d.path(), &det, std::slice::from_ref(&a));
        assert_eq!(a.id, "c335a-1");
        assert_eq!(b.id, "c335a-2");
        assert!(a.name.ends_with("(3.3.5a (12340))"));
    }
}
