//! The settings file: client profiles, the chosen realm and the Wine setting, as JSON under the OS app-data dir.
//!
//! Saves are atomic (write a temp file in the same folder, flush it, rename over the old one), so a crash or
//! power cut leaves either the old file or the new one, never half of one. A file that will not parse is kept
//! aside as settings.json.broken and Leyline starts from defaults rather than refusing to open.

use crate::clients::ClientProfile;
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

pub const FILE_NAME: &str = "settings.json";
pub const SCHEMA: u32 = 1;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Wine {
    /// Launch through Wine (macOS and Linux). Ignored on Windows.
    pub enabled: bool,
    /// The wine command, such as `wine`, `wine64` or a full path.
    pub command: String,
    /// Optional WINEPREFIX. Empty means Wine's default.
    pub prefix: String,
}

impl Default for Wine {
    fn default() -> Self {
        Wine { enabled: !cfg!(windows), command: "wine".into(), prefix: String::new() }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub schema: u32,
    pub clients: Vec<ClientProfile>,
    pub selected_client: Option<String>,
    /// The realm address chosen on the Play page.
    pub selected_realm: String,
    pub wine: Wine,
    /// The host kit folder chosen on the Host page (empty: none yet).
    pub host_kit: String,
    /// Mods (manifest keys such as `mod:fps-fix`) whose native code the player OK'd once. Stored here, in the
    /// launcher's own folder, so the notice is shown once per mod, for every client.
    pub native_ok: Vec<String>,
    /// Which Leyline releases to update to: stable (releases) or beta (pre-releases too).
    pub update_channel: crate::update::Channel,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            schema: SCHEMA,
            clients: Vec::new(),
            selected_client: None,
            selected_realm: crate::OFFICIAL_REALM.into(),
            wine: Wine::default(),
            host_kit: String::new(),
            native_ok: Vec::new(),
            update_channel: crate::update::Channel::Stable,
        }
    }
}

impl Settings {
    pub fn client(&self, id: &str) -> Option<&ClientProfile> {
        self.clients.iter().find(|c| c.id == id)
    }
    pub fn client_mut(&mut self, id: &str) -> Option<&mut ClientProfile> {
        self.clients.iter_mut().find(|c| c.id == id)
    }
    /// The player OK'd native code for this mod.
    pub fn native_allowed(&self, key: &str) -> bool {
        self.native_ok.iter().any(|k| k == key)
    }
    pub fn remove_client(&mut self, id: &str) -> bool {
        let n = self.clients.len();
        self.clients.retain(|c| c.id != id);
        if self.selected_client.as_deref() == Some(id) {
            self.selected_client = self.clients.first().map(|c| c.id.clone());
        }
        self.clients.len() != n
    }
}

/// Leyline's data folder: %APPDATA%\Leyline, ~/Library/Application Support/Leyline, ~/.local/share/Leyline.
pub fn app_dir() -> PathBuf {
    dirs::data_dir().unwrap_or_else(std::env::temp_dir).join("Leyline")
}

/// Write `bytes` to `path` atomically.
pub fn write_atomic(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let dir = path.parent().filter(|p| !p.as_os_str().is_empty()).unwrap_or(Path::new("."));
    fs::create_dir_all(dir)?;
    let name = path.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
    let tmp = dir.join(format!(".{name}.{}.tmp", std::process::id()));
    {
        let mut f = fs::File::create(&tmp)?;
        f.write_all(bytes)?;
        f.sync_all()?;
    }
    // On Windows rename replaces an existing file too (MoveFileEx with REPLACE_EXISTING).
    fs::rename(&tmp, path).inspect_err(|_| {
        let _ = fs::remove_file(&tmp);
    })
}

/// Load the settings in `dir`. A missing file gives defaults; a broken one is moved aside, then defaults.
pub fn load(dir: &Path) -> Settings {
    let p = dir.join(FILE_NAME);
    match fs::read(&p) {
        Ok(b) => match serde_json::from_slice::<Settings>(&b) {
            Ok(s) => s,
            Err(_) => {
                let _ = fs::rename(&p, dir.join(format!("{FILE_NAME}.broken")));
                Settings::default()
            }
        },
        Err(_) => Settings::default(),
    }
}

pub fn save(dir: &Path, s: &Settings) -> io::Result<()> {
    let mut b = serde_json::to_vec_pretty(s).map_err(io::Error::other)?;
    b.push(b'\n');
    write_atomic(&dir.join(FILE_NAME), &b)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::clients::Build;

    fn profile() -> ClientProfile {
        ClientProfile {
            id: "c335a-1".into(),
            name: "Client".into(),
            path: "/games/client".into(),
            build: Build::V335a,
            realmlist: "play.openvanilla.app".into(),
            locale: Some("enUS".into()),
            exe_version: Some("3.3.5.12340".into()),
            exe: None,
        }
    }

    #[test]
    fn round_trip() {
        let d = tempfile::tempdir().unwrap();
        assert_eq!(load(d.path()), Settings::default());
        let mut s = Settings::default();
        s.clients.push(profile());
        s.selected_client = Some("c335a-1".into());
        s.wine.command = "wine64".into();
        s.native_ok.push("mod:fps-fix".into());
        s.update_channel = crate::update::Channel::Beta;
        save(d.path(), &s).unwrap();
        assert_eq!(load(d.path()), s);
        assert!(load(d.path()).native_allowed("mod:fps-fix") && !s.native_allowed("mod:other"));
        let text = fs::read_to_string(d.path().join(FILE_NAME)).unwrap();
        assert!(text.contains("\"build\": \"3.3.5a\"") && text.contains("\"update_channel\": \"beta\""));
        // No temp file left behind.
        assert_eq!(fs::read_dir(d.path()).unwrap().count(), 1);
    }

    #[test]
    fn broken_file_is_kept_aside() {
        let d = tempfile::tempdir().unwrap();
        fs::write(d.path().join(FILE_NAME), b"{ not json").unwrap();
        assert_eq!(load(d.path()), Settings::default());
        assert!(d.path().join("settings.json.broken").exists());
    }

    #[test]
    fn missing_fields_take_defaults() {
        let d = tempfile::tempdir().unwrap();
        fs::write(d.path().join(FILE_NAME), br#"{"selected_realm":"x.example.org"}"#).unwrap();
        let s = load(d.path());
        assert_eq!(s.selected_realm, "x.example.org");
        assert_eq!(s.wine.command, "wine");
    }

    #[test]
    fn remove_client_moves_the_selection() {
        let mut s = Settings::default();
        let mut b = profile();
        b.id = "c1121-1".into();
        s.clients = vec![profile(), b];
        s.selected_client = Some("c335a-1".into());
        assert!(s.remove_client("c335a-1"));
        assert_eq!(s.selected_client.as_deref(), Some("c1121-1"));
        assert!(!s.remove_client("nope"));
    }

    #[test]
    fn atomic_write_replaces() {
        let d = tempfile::tempdir().unwrap();
        let p = d.path().join("sub/f.txt");
        write_atomic(&p, b"one").unwrap();
        write_atomic(&p, b"two").unwrap();
        assert_eq!(fs::read(&p).unwrap(), b"two");
    }
}
