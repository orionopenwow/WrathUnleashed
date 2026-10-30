//! The hard refusal list for everything Leyline downloads outside the mod installer: the Host pack, theme
//! packs, launcher updates and (when `torrent_downloads` is on) anything fetched through a torrent.
//!
//! A download is refused, whichever way it came, when it holds or is:
//! * game data: archives, textures, models, maps, databases, by file name or by magic bytes;
//! * a game client: the game's own executables or a game `Data/` folder.
//!
//! The mod installer (`mods.rs`) has its own, stricter rules for what may go into a client; this list is the
//! floor under every other download.

use std::fs;
use std::io::Read;
use std::path::Path;

const GAME_EXT: &[&str] = &[".mpq", ".blp", ".m2", ".wmo", ".adt", ".dbc", ".db2", ".skin", ".anim", ".wdt", ".wdl", ".bls", ".casc"];
const GAME_MAGIC: &[&[u8; 4]] = &[b"MPQ\x1a", b"MPQ\x1b", b"BLP1", b"BLP2", b"MD20", b"MD21", b"WDBC", b"WDB2", b"REVM"];
/// Executables and folders that only a game client has.
const CLIENT_NAMES: &[&str] = &["wow.exe", "wow-64.exe", "wowb.exe", "wowt.exe", "wowclassic.exe", "world of warcraft.app", "wow.app", "blizzard launcher.exe", "battle.net.exe", "battle.net launcher.exe"];
/// A zip may hold at most this many entries before it is refused unread.
const MAX_ENTRIES: usize = 20_000;

fn lower_base(name: &str) -> String {
    name.trim_end_matches('/').rsplit(['/', '\\']).next().unwrap_or(name).to_ascii_lowercase()
}

/// Why a path inside a package (or a file name) is refused, or None.
pub fn name_refusal(name: &str) -> Option<String> {
    let base = lower_base(name);
    if CLIENT_NAMES.contains(&base.as_str()) {
        return Some(format!("{name}: a game client file"));
    }
    if base.starts_with("wow") && base.ends_with(".exe") {
        return Some(format!("{name}: a game client file"));
    }
    let lower = name.to_ascii_lowercase().replace('\\', "/");
    if lower.split('/').any(|p| p == "_retail_" || p == "_classic_" || p == "_classic_era_") {
        return Some(format!("{name}: a game client folder"));
    }
    if let Some(e) = GAME_EXT.iter().find(|e| base.ends_with(*e)) {
        return Some(format!("{name}: game data ({e} files are never downloaded by Leyline)"));
    }
    None
}

/// Why these first bytes are refused, or None.
pub fn magic_refusal(name: &str, head: &[u8]) -> Option<String> {
    (head.len() >= 4 && GAME_MAGIC.iter().any(|m| &head[..4] == *m)).then(|| format!("{name}: game data (by its contents)"))
}

/// Check a downloaded file: a zip is checked entry by entry (names and contents), anything else by its own
/// name and first bytes. Ok(()) means nothing on the refusal list.
pub fn check_file(path: &Path, display_name: &str) -> Result<(), String> {
    if let Some(r) = name_refusal(display_name) {
        return Err(r);
    }
    let mut head = [0u8; 4];
    let n = fs::File::open(path).and_then(|mut f| f.read(&mut head)).map_err(|e| e.to_string())?;
    if let Some(r) = magic_refusal(display_name, &head[..n]) {
        return Err(r);
    }
    if n == 4 && &head == b"PK\x03\x04" {
        return check_zip(path);
    }
    Ok(())
}

pub fn check_zip(path: &Path) -> Result<(), String> {
    let f = fs::File::open(path).map_err(|e| e.to_string())?;
    let mut z = zip::ZipArchive::new(f).map_err(|e| format!("not a readable zip: {e}"))?;
    if z.len() > MAX_ENTRIES {
        return Err("the package has too many files".into());
    }
    let mut data_folder_archives = 0;
    for i in 0..z.len() {
        let mut e = z.by_index(i).map_err(|e| format!("not a readable zip: {e}"))?;
        let name = e.name().to_string();
        if let Some(r) = name_refusal(&name) {
            return Err(r);
        }
        if name.to_ascii_lowercase().contains("data/") && name.to_ascii_lowercase().ends_with(".mpq") {
            data_folder_archives += 1;
        }
        if e.is_file() {
            let mut head = [0u8; 4];
            let mut got = 0;
            while got < 4 {
                match e.read(&mut head[got..]) {
                    Ok(0) => break,
                    Ok(k) => got += k,
                    Err(err) => return Err(format!("{name}: could not be read ({err})")),
                }
            }
            if let Some(r) = magic_refusal(&name, &head[..got]) {
                return Err(r);
            }
        }
    }
    if data_folder_archives > 0 {
        return Err("a game Data folder".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mods::tests::zip_of;

    #[test]
    fn names_and_magic() {
        for bad in ["Data/common.MPQ", "x/tex.BLP", "Wow.exe", "wow-64.exe", "WowCustom.exe", "World of Warcraft.app", "a/_retail_/x.txt", "Interface/model.m2"] {
            assert!(name_refusal(bad).is_some(), "{bad}");
        }
        for ok in ["leyline-host.zip", "hostpack.json", "tools/Dockerfile", "Leyline_0.3.0_x64-setup.exe", "Leyline.AppImage", "theme/bg.webp"] {
            assert!(name_refusal(ok).is_none(), "{ok}");
        }
        assert!(magic_refusal("renamed.png", b"MPQ\x1a....").is_some());
        assert!(magic_refusal("ok.png", b"\x89PNG").is_none());
    }

    #[test]
    fn zips_are_checked_inside() {
        let d = tempfile::tempdir().unwrap();
        let good = d.path().join("good.zip");
        fs::write(&good, zip_of(&[("WrathUnleashed host/leyline", b"#!/usr/bin/env bash"), ("WrathUnleashed host/tools/Dockerfile", b"FROM x")])).unwrap();
        assert!(check_file(&good, "good.zip").is_ok());
        let renamed = d.path().join("r.zip");
        fs::write(&renamed, zip_of(&[("pack/readme.txt", b"BLP2 sneaky")])).unwrap();
        assert!(check_file(&renamed, "r.zip").unwrap_err().contains("by its contents"));
        let client = d.path().join("c.zip");
        fs::write(&client, zip_of(&[("Game/Wow.exe", b"MZ")])).unwrap();
        assert!(check_file(&client, "c.zip").unwrap_err().contains("game client"));
        let raw = d.path().join("x.bin");
        fs::write(&raw, b"MPQ\x1b").unwrap();
        assert!(check_file(&raw, "x.bin").is_err());
    }
}
