//! One download path for Leyline's own packages: mod packages, theme packs, the Host pack and launcher
//! updates. Nothing else can be asked for: the kind is a closed list, and every result goes through the
//! refusal list (`checker`) and a sha256 check, however it arrived. Never game data, never a client.
//!
//! Routes, in order:
//! 1. `torrent_downloads` on and the package has a torrent: the swarm (`Swarm`), then the torrent's HTTP web
//!    seeds, each checked piece by piece against the torrent;
//! 2. otherwise, or when 1 fails: the plain HTTPS download.
//!
//! The built-in swarm is `NoSwarm`: Leyline has no BitTorrent peer protocol yet (see docs/P2P-AND-TORRENT.md),
//! so with the flag on a torrent is fetched from its web seeds. A real swarm plugs in behind `Swarm`, with the
//! upload limits in `flags::Limits` (seeding stays off unless the flag, a cap and a ratio are all set).

use super::checker;
use super::flags::Flags;
use super::torrent::{self, Meta};
use serde::Serialize;
use std::fs;
use std::path::Path;
use std::time::Duration;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    ModPackage,
    ThemePack,
    HostPack,
    LauncherUpdate,
}

/// What to fetch. `sha256` is required: an unhashed download is never accepted.
#[derive(Debug, Clone)]
pub struct Request {
    pub kind: Kind,
    /// The file name it is saved and checked under.
    pub name: String,
    pub sha256: String,
    pub https_url: String,
    /// The package's `.torrent`, when the catalog gives one.
    pub torrent: Option<Vec<u8>>,
    pub max_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Via {
    Https,
    WebSeed,
    Swarm,
}

#[derive(Debug, Clone, Serialize)]
pub struct Outcome {
    pub bytes: u64,
    pub sha256: String,
    pub via: Via,
    /// Why the torrent route was not used, when it was tried and failed.
    pub torrent_note: Option<String>,
}

/// A BitTorrent swarm: fetch the whole file into `dest` from peers, or fail. Implementations must honour
/// `flags.limits` for anything they upload.
pub trait Swarm {
    fn fetch(&self, meta: &Meta, dest: &Path, flags: &Flags) -> Result<(), String>;
    fn name(&self) -> &'static str;
}

/// The built-in swarm: no peers. Torrent downloads fall through to their web seeds.
pub struct NoSwarm;

impl Swarm for NoSwarm {
    fn fetch(&self, _meta: &Meta, _dest: &Path, _flags: &Flags) -> Result<(), String> {
        Err("no peer-to-peer engine in this build: using the web seeds".into())
    }
    fn name(&self) -> &'static str {
        "none"
    }
}

const CONNECT: Duration = Duration::from_secs(8);
const READ: Duration = Duration::from_secs(30);

fn sha_ok(s: &str) -> bool {
    s.len() == 64 && s.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
}

fn finish(req: &Request, dest: &Path, via: Via, note: Option<String>) -> Result<Outcome, String> {
    let got = crate::net::sha256_file(dest).map_err(|e| e.to_string())?;
    if got != req.sha256 {
        let _ = fs::remove_file(dest);
        return Err(format!("{}: the download does not match its sha256, so it was thrown away", req.name));
    }
    if let Err(why) = checker::check_file(dest, &req.name) {
        let _ = fs::remove_file(dest);
        return Err(format!("Refused: {why}. Leyline never downloads game data or a game client."));
    }
    let bytes = fs::metadata(dest).map(|m| m.len()).unwrap_or(0);
    Ok(Outcome { bytes, sha256: got, via, torrent_note: note })
}

fn via_torrent(req: &Request, raw: &[u8], dest: &Path, flags: &Flags, swarm: &dyn Swarm) -> Result<(Via, Meta), String> {
    let meta = torrent::parse(raw)?;
    if meta.length > req.max_bytes {
        return Err("the torrent is bigger than this download may be".into());
    }
    if let Some(why) = checker::name_refusal(&meta.name) {
        return Err(format!("Refused: {why}"));
    }
    if swarm.fetch(&meta, dest, flags).is_ok() && torrent::verify(&meta, dest).map(|b| b.is_empty()).unwrap_or(false) {
        return Ok((Via::Swarm, meta));
    }
    let _ = fs::remove_file(dest);
    let mut last = "the torrent has no web seeds".to_string();
    for seed in &meta.web_seeds {
        match crate::net::download(seed, dest, req.max_bytes, CONNECT, READ) {
            Ok(_) => match torrent::verify(&meta, dest) {
                Ok(bad) if bad.is_empty() => return Ok((Via::WebSeed, meta)),
                Ok(bad) => last = format!("{} bad pieces from a web seed", bad.len()),
                Err(e) => last = e,
            },
            Err(e) => last = e,
        }
        let _ = fs::remove_file(dest);
    }
    Err(last)
}

/// Fetch `req` into `dest` by the best allowed route. On any failure nothing is left at `dest`.
pub fn fetch(req: &Request, dest: &Path, flags: &Flags, swarm: &dyn Swarm) -> Result<Outcome, String> {
    if !sha_ok(&req.sha256) {
        return Err("This download has no sha256, so Leyline will not fetch it.".into());
    }
    if let Some(why) = checker::name_refusal(&req.name) {
        return Err(format!("Refused: {why}. Leyline never downloads game data or a game client."));
    }
    let mut note = None;
    if flags.torrent_downloads {
        if let Some(raw) = &req.torrent {
            match via_torrent(req, raw, dest, flags, swarm) {
                Ok((via, _)) => return finish(req, dest, via, None),
                Err(e) if e.starts_with("Refused") => return Err(e),
                Err(e) => note = Some(e),
            }
        }
    }
    if let Err(e) = crate::net::download(&req.https_url, dest, req.max_bytes, CONNECT, READ) {
        let _ = fs::remove_file(dest);
        return Err(match note {
            Some(n) => format!("{e} (the torrent did not work either: {n})"),
            None => e,
        });
    }
    finish(req, dest, Via::Https, note)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mods::tests::zip_of;
    use crate::net::testserver::*;
    use sha2::{Digest, Sha256};

    fn on() -> Flags {
        Flags { torrent_downloads: true, ..Default::default() }
    }

    fn pack() -> Vec<u8> {
        let big: Vec<u8> = (0..70_000u32).map(|i| (i * 7 % 256) as u8).collect();
        zip_of(&[("WrathUnleashed host/leyline", b"#!/usr/bin/env bash\n"), ("WrathUnleashed host/blob.txt", &big)])
    }

    fn req(url: &str, data: &[u8], torrent: Option<Vec<u8>>) -> Request {
        Request {
            kind: Kind::HostPack,
            name: "leyline-host-pack.zip".into(),
            sha256: crate::net::hex(&Sha256::digest(data)),
            https_url: url.into(),
            torrent,
            max_bytes: 10 * 1024 * 1024,
        }
    }

    struct FakeSwarm(Vec<u8>);
    impl Swarm for FakeSwarm {
        fn fetch(&self, _m: &Meta, dest: &Path, _f: &Flags) -> Result<(), String> {
            fs::write(dest, &self.0).map_err(|e| e.to_string())
        }
        fn name(&self) -> &'static str {
            "fake"
        }
    }

    #[test]
    fn flags_off_uses_https_only() {
        let data = pack();
        let base = serve_routes(vec![("/p.zip", "200 OK", data.clone())]);
        let d = tempfile::tempdir().unwrap();
        // A torrent whose only web seed is dead: with the flag off it is never looked at.
        let t = torrent::make("leyline-host-pack.zip", &data, 16384, &[&dead_url()]);
        let o = fetch(&req(&format!("{base}/p.zip"), &data, Some(t)), &d.path().join("p.zip"), &Flags::default(), &NoSwarm).unwrap();
        assert_eq!((o.via, o.bytes), (Via::Https, data.len() as u64));
        assert!(o.torrent_note.is_none());
    }

    #[test]
    fn flags_on_uses_the_web_seed_and_checks_pieces() {
        let data = pack();
        let base = serve_routes(vec![("/seed.zip", "200 OK", data.clone()), ("/p.zip", "200 OK", data.clone())]);
        let d = tempfile::tempdir().unwrap();
        let t = torrent::make("leyline-host-pack.zip", &data, 16384, &[&format!("{base}/seed.zip")]);
        let o = fetch(&req(&format!("{base}/nothing-here"), &data, Some(t)), &d.path().join("p.zip"), &on(), &NoSwarm).unwrap();
        assert_eq!(o.via, Via::WebSeed);
        // A web seed with bad bytes: pieces fail, the HTTPS fallback is used.
        let mut bad = data.clone();
        bad[100] ^= 0xff;
        let base2 = serve_routes(vec![("/seed.zip", "200 OK", bad), ("/p.zip", "200 OK", data.clone())]);
        let t = torrent::make("leyline-host-pack.zip", &data, 16384, &[&format!("{base2}/seed.zip")]);
        let o = fetch(&req(&format!("{base2}/p.zip"), &data, Some(t)), &d.path().join("p.zip"), &on(), &NoSwarm).unwrap();
        assert_eq!(o.via, Via::Https);
        assert!(o.torrent_note.unwrap().contains("bad pieces"));
    }

    #[test]
    fn a_swarm_plugs_in() {
        let data = pack();
        let d = tempfile::tempdir().unwrap();
        let t = torrent::make("leyline-host-pack.zip", &data, 16384, &[]);
        let o = fetch(&req(&dead_url(), &data, Some(t.clone())), &d.path().join("p.zip"), &on(), &FakeSwarm(data.clone())).unwrap();
        assert_eq!(o.via, Via::Swarm);
        // A swarm that hands back the wrong bytes is not trusted.
        assert!(fetch(&req(&dead_url(), &data, Some(t)), &d.path().join("p.zip"), &on(), &FakeSwarm(b"junk".to_vec())).is_err());
        assert!(!d.path().join("p.zip").exists());
    }

    #[test]
    fn game_data_and_clients_are_refused_every_way() {
        let d = tempfile::tempdir().unwrap();
        let gd = zip_of(&[("x/patch.txt", b"MPQ\x1a....")]);
        let base = serve_routes(vec![("/g.zip", "200 OK", gd.clone())]);
        for flags in [Flags::default(), on()] {
            let t = torrent::make("leyline-host-pack.zip", &gd, 16384, &[&format!("{base}/g.zip")]);
            let e = fetch(&req(&format!("{base}/g.zip"), &gd, Some(t)), &d.path().join("g.zip"), &flags, &NoSwarm).unwrap_err();
            assert!(e.starts_with("Refused"), "{e}");
            assert!(!d.path().join("g.zip").exists());
        }
        let mut r = req("https://x.example.com/a", b"x", None);
        r.name = "common.MPQ".into();
        assert!(fetch(&r, &d.path().join("c"), &on(), &NoSwarm).unwrap_err().starts_with("Refused"));
        let t = torrent::make("Wow.exe", b"MZ", 16384, &[]);
        let mut r = req(&dead_url(), b"MZ", Some(t));
        r.name = "ok.zip".into();
        assert!(fetch(&r, &d.path().join("w"), &on(), &NoSwarm).unwrap_err().contains("game client"));
    }

    #[test]
    fn sha256_is_required_and_checked() {
        let data = pack();
        let base = serve_routes(vec![("/p.zip", "200 OK", data.clone())]);
        let d = tempfile::tempdir().unwrap();
        let mut r = req(&format!("{base}/p.zip"), &data, None);
        r.sha256 = "".into();
        assert!(fetch(&r, &d.path().join("p.zip"), &on(), &NoSwarm).unwrap_err().contains("no sha256"));
        r.sha256 = "0".repeat(64);
        assert!(fetch(&r, &d.path().join("p.zip"), &on(), &NoSwarm).unwrap_err().contains("does not match"));
        assert!(!d.path().join("p.zip").exists());
    }
}
