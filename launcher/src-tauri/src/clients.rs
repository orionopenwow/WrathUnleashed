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

/// The client builds Leyline supports.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Build {
    /// 3.3.5a, build 12340.
    #[serde(rename = "3.3.5a")]
    V335a,
    /// 1.12.1, build 5875.
    #[serde(rename = "1.12.1")]
    V1121,
}

impl Build {
    pub fn number(self) -> u16 {
        match self {
            Build::V335a => 12340,
            Build::V1121 => 5875,
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            Build::V335a => "3.3.5a (12340)",
            Build::V1121 => "1.12.1 (5875)",
        }
    }
    /// The executable, as named in a stock install (looked up without regard to case).
    pub fn exe_name(self) -> &'static str {
        match self {
            Build::V335a => "Wow.exe",
            Build::V1121 => "WoW.exe",
        }
    }
    /// The `## Interface:` number an addon for this build has in its .toc.
    pub fn interface(self) -> &'static str {
        match self {
            Build::V335a => "30300",
            Build::V1121 => "11200",
        }
    }
    /// The build as the Workshop catalog names it (`builds` in all.json).
    pub fn catalog_tag(self) -> &'static str {
        match self {
            Build::V335a => "3.3.5a",
            Build::V1121 => "1.12",
        }
    }
    fn from_version(v: FileVersion) -> Option<Build> {
        match (v.major, v.minor, v.patch, v.build) {
            (3, 3, 5, 12340) => Some(Build::V335a),
            (1, 12, 1, 5875) => Some(Build::V1121),
            _ => None,
        }
    }
}

/// One client the player added. Stored in the settings file.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ClientProfile {
    pub id: String,
    pub name: String,
    pub path: PathBuf,
    pub build: Build,
    /// The realm address last written to this client's realmlist.wtf.
    #[serde(default)]
    pub realmlist: String,
    /// The locale folder (3.3.5a only), such as enUS.
    #[serde(default)]
    pub locale: Option<String>,
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
    pub detected_by: DetectedBy,
    pub exe: Option<PathBuf>,
    pub exe_version: Option<String>,
    pub locale: Option<String>,
    /// Files a complete install has that this folder lacks. Empty means it looks complete.
    pub missing: Vec<String>,
    pub complete: bool,
    pub realmlist_path: PathBuf,
    /// The realm address currently in realmlist.wtf, if any.
    pub current_realmlist: Option<String>,
}

#[derive(Debug)]
pub enum DetectError {
    NotAFolder,
    UnsupportedVersion(String),
    Unrecognised,
    Io(io::Error),
}

impl std::fmt::Display for DetectError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DetectError::NotAFolder => write!(f, "That is not a folder."),
            DetectError::UnsupportedVersion(v) => write!(
                f,
                "This client is version {v}. Leyline supports 3.3.5a (12340) and 1.12.1 (5875) for now."
            ),
            DetectError::Unrecognised => write!(
                f,
                "No supported game client found here. Pick the folder that holds the game's .exe and its Data folder."
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
    "enUS", "enGB", "deDE", "frFR", "esES", "esMX", "ruRU", "koKR", "zhCN", "zhTW", "enTW", "enCN", "ptBR", "itIT",
];

/// The locale folder under Data/ (3.3.5a keeps realmlist.wtf and the locale MPQs there).
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

fn by_data_files(root: &Path) -> Option<Build> {
    let data = find_ci(root, "Data")?;
    let has = |n: &str| find_ci(&data, n).is_some();
    if has("lichking.MPQ") || has("common-2.MPQ") {
        return Some(Build::V335a);
    }
    if has("patch.MPQ") && has("dbc.MPQ") && !has("expansion.MPQ") && !has("lichking.MPQ") && !has("common.MPQ") {
        return Some(Build::V1121);
    }
    None
}

/// The files a complete install of `build` has, relative to the client folder.
fn required(build: Build, locale: Option<&str>) -> Vec<String> {
    let mut v: Vec<String> = match build {
        Build::V335a => ["common.MPQ", "common-2.MPQ", "expansion.MPQ", "lichking.MPQ", "patch.MPQ", "patch-2.MPQ"]
            .iter()
            .map(|f| format!("Data/{f}"))
            .collect(),
        Build::V1121 => [
            "dbc.MPQ", "fonts.MPQ", "interface.MPQ", "misc.MPQ", "model.MPQ", "patch.MPQ", "sound.MPQ",
            "speech.MPQ", "terrain.MPQ", "texture.MPQ", "wmo.MPQ",
        ]
        .iter()
        .map(|f| format!("Data/{f}"))
        .collect(),
    };
    if build == Build::V335a {
        match locale {
            Some(l) => v.push(format!("Data/{l}/locale-{l}.MPQ")),
            None => v.push("Data/<locale>/".into()),
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

/// Where this build reads its realmlist from.
pub fn realmlist_path(root: &Path, build: Build, locale: Option<&str>) -> PathBuf {
    match (build, locale) {
        (Build::V335a, Some(l)) => {
            let dir = find_rel(root, &format!("Data/{l}")).unwrap_or_else(|| root.join("Data").join(l));
            find_ci(&dir, "realmlist.wtf").unwrap_or_else(|| dir.join("realmlist.wtf"))
        }
        (Build::V335a, None) => root.join("Data").join("enUS").join("realmlist.wtf"),
        (Build::V1121, _) => find_ci(root, "realmlist.wtf").unwrap_or_else(|| root.join("realmlist.wtf")),
    }
}

/// Look at a folder and say which client it is.
pub fn detect(root: &Path) -> Result<Detection, DetectError> {
    if !root.is_dir() {
        return Err(DetectError::NotAFolder);
    }
    // 1. The executable's version resource.
    let mut exe_version = None;
    let mut build = None;
    let mut detected_by = DetectedBy::ExeVersion;
    for name in ["Wow.exe", "WoW.exe"] {
        if let Some(p) = find_ci(root, name) {
            if let Some(v) = pe_version::read(&p)? {
                exe_version = Some(v.to_string());
                build = Build::from_version(v);
            }
            break;
        }
    }
    // An executable that says it is some other version wins over the data files.
    if let (None, Some(v)) = (build, &exe_version) {
        return Err(DetectError::UnsupportedVersion(v.clone()));
    }
    // 2. The data-file signatures (no executable, or one without a version resource).
    if build.is_none() {
        build = by_data_files(root);
        detected_by = DetectedBy::DataFiles;
    }
    let build = build.ok_or(DetectError::Unrecognised)?;
    let locale = match build {
        Build::V335a => find_ci(root, "Data").and_then(|d| find_locale(&d)),
        Build::V1121 => None,
    };
    let missing: Vec<String> = required(build, locale.as_deref())
        .into_iter()
        .filter(|rel| rel.contains('<') || find_rel(root, rel).is_none())
        .map(shown)
        .collect();
    let rl = realmlist_path(root, build, locale.as_deref());
    let current_realmlist = fs::read_to_string(&rl).ok().and_then(|t| parse_realmlist(&t));
    Ok(Detection {
        build,
        detected_by,
        exe: find_ci(root, build.exe_name()),
        exe_version,
        locale,
        complete: missing.is_empty(),
        missing,
        realmlist_path: rl,
        current_realmlist,
    })
}

/// The address in a realmlist.wtf (`set realmlist <host>`), if there is one.
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

/// The backup kept next to a realmlist.wtf the first time Leyline changes it.
pub fn backup_path(rl: &Path) -> PathBuf {
    let mut n = rl.file_name().map(|n| n.to_os_string()).unwrap_or_default();
    n.push(".leyline-backup");
    rl.with_file_name(n)
}

/// Point a client at a realm: write realmlist.wtf, keeping the player's original as a backup.
///
/// The backup is made once, the first time, so it always holds the file as it was before Leyline. 3.3.5a can
/// also carry a realmList line in WTF/Config.wtf that overrides realmlist.wtf; when it does, that line is
/// updated too (with its own backup).
pub fn write_realmlist(profile: &ClientProfile, addr: &str) -> io::Result<PathBuf> {
    if !valid_realm_address(addr) {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, format!("not a realm address: {addr:?}")));
    }
    let rl = realmlist_path(&profile.path, profile.build, profile.locale.as_deref());
    let old = match fs::read_to_string(&rl) {
        Ok(t) => {
            let bak = backup_path(&rl);
            if !bak.exists() {
                fs::write(&bak, &t)?;
            }
            t
        }
        Err(e) if e.kind() == io::ErrorKind::NotFound => {
            if let Some(d) = rl.parent() {
                fs::create_dir_all(d)?;
            }
            String::new()
        }
        Err(e) => return Err(e),
    };
    crate::settings::write_atomic(&rl, with_realmlist(&old, addr).as_bytes())?;

    if profile.build == Build::V335a {
        if let Some(cfg) = find_rel(&profile.path, "WTF/Config.wtf") {
            let text = fs::read_to_string(&cfg)?;
            if let Some(new) = config_wtf_with_realmlist(&text, addr) {
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

/// Config.wtf with its `SET realmList "..."` line changed, or None when it has no such line.
fn config_wtf_with_realmlist(text: &str, addr: &str) -> Option<String> {
    let mut hit = false;
    let lines: Vec<String> = text
        .lines()
        .map(|l| {
            let mut w = l.split_whitespace();
            if matches!((w.next(), w.next()), (Some(a), Some(b)) if a.eq_ignore_ascii_case("SET") && b.eq_ignore_ascii_case("realmList"))
            {
                hit = true;
                format!("SET realmList \"{addr}\"")
            } else {
                l.to_string()
            }
        })
        .collect();
    hit.then(|| lines.join("\r\n") + "\r\n")
}

/// Put back the realmlist.wtf (and Config.wtf) the player had before Leyline first changed them. Returns false
/// when there is no backup (Leyline never changed this client's realmlist).
pub fn restore_realmlist(profile: &ClientProfile) -> io::Result<bool> {
    let rl = realmlist_path(&profile.path, profile.build, profile.locale.as_deref());
    let bak = backup_path(&rl);
    if !bak.is_file() {
        return Ok(false);
    }
    crate::settings::write_atomic(&rl, &fs::read(&bak)?)?;
    if profile.build == Build::V335a {
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
    let rl = realmlist_path(&profile.path, profile.build, profile.locale.as_deref());
    fs::read_to_string(rl).ok().and_then(|t| parse_realmlist(&t))
}

/// A new profile from a detection. The id is unique among `existing` ids.
pub fn new_profile(path: &Path, det: &Detection, existing: &[ClientProfile]) -> ClientProfile {
    let base = match det.build {
        Build::V335a => "c335a",
        Build::V1121 => "c1121",
    };
    let id = (1..)
        .map(|n| format!("{base}-{n}"))
        .find(|id| !existing.iter().any(|p| &p.id == id))
        .unwrap();
    let folder = path.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
    ClientProfile {
        id,
        name: if folder.is_empty() { det.build.label().to_string() } else { format!("{folder} ({})", det.build.label()) },
        path: path.to_path_buf(),
        build: det.build,
        realmlist: det.current_realmlist.clone().unwrap_or_default(),
        locale: det.locale.clone(),
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
    fn other_versions_are_refused() {
        let d = tempfile::tempdir().unwrap();
        touch(d.path(), "Wow.exe", &pe_version::fake_exe(2, 4, 3, 8606));
        touch(d.path(), "Data/common.MPQ", b"");
        match detect(d.path()) {
            Err(DetectError::UnsupportedVersion(v)) => assert_eq!(v, "2.4.3.8606"),
            other => panic!("{other:?}"),
        }
        let e = tempfile::tempdir().unwrap();
        assert!(matches!(detect(e.path()), Err(DetectError::Unrecognised)));
        assert!(matches!(detect(&e.path().join("nope")), Err(DetectError::NotAFolder)));
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
