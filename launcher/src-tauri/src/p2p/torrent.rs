//! `.torrent` metainfo (BEP 3) for single-file packages, with HTTP web seeds (BEP 19 `url-list`), and the
//! piece check. Leyline's packages are one zip each, so multi-file torrents are refused.
//!
//! What is here: reading the metainfo, the info-hash, and checking a downloaded file piece by piece against
//! it. What is not: the peer wire protocol (BEP 3 peers, DHT, trackers). That sits behind
//! `transfer::Swarm`; the built-in one (`NoSwarm`) has no peers, so a torrent download is fetched from its web
//! seeds and checked against the torrent's piece hashes and the catalog's sha256.

use super::bencode::{self, Value};
use super::sha1;
use std::fs;
use std::io::Read;
use std::path::Path;

/// Leyline's own torrents are small; a bigger one is refused before anything is fetched.
pub const MAX_TORRENT_FILE: usize = 1024 * 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Meta {
    pub name: String,
    pub length: u64,
    pub piece_length: u64,
    pub pieces: Vec<[u8; 20]>,
    pub info_hash: [u8; 20],
    /// HTTP(S) web seeds.
    pub web_seeds: Vec<String>,
    /// Trackers (kept for a real swarm later; unused by the built-in one).
    pub trackers: Vec<String>,
}

impl Meta {
    pub fn info_hash_hex(&self) -> String {
        crate::net::hex(&self.info_hash)
    }
    /// The magnet link (info-hash, name, web seeds), for sharing.
    pub fn magnet(&self) -> String {
        let enc = |s: &str| s.bytes().map(|b| if b.is_ascii_alphanumeric() || b"-._~".contains(&b) { (b as char).to_string() } else { format!("%{b:02X}") }).collect::<String>();
        let mut m = format!("magnet:?xt=urn:btih:{}&dn={}", self.info_hash_hex(), enc(&self.name));
        for w in &self.web_seeds {
            m.push_str(&format!("&ws={}", enc(w)));
        }
        m
    }
}

fn web_seed_ok(u: &str) -> bool {
    crate::net::plain_https(u) || u.starts_with("http://127.0.0.1:")
}

pub fn parse(raw: &[u8]) -> Result<Meta, String> {
    if raw.len() > MAX_TORRENT_FILE {
        return Err("the torrent file is too big".into());
    }
    let (v, info_raw) = bencode::decode(raw)?;
    let info = v.get("info").ok_or("the torrent file has no info")?;
    let info_raw = info_raw.ok_or("the torrent file has no info")?;
    if info.get("files").is_some() {
        return Err("Leyline only takes single-file torrents".into());
    }
    let name = info.get("name").and_then(Value::str).ok_or("the torrent has no name")?.to_string();
    if name.is_empty() || name.contains(['/', '\\']) || name.starts_with('.') || name.len() > 200 {
        return Err("the torrent's file name is not allowed".into());
    }
    let length = info.get("length").and_then(Value::int).filter(|l| *l > 0).ok_or("the torrent has no length")? as u64;
    let piece_length = info.get("piece length").and_then(Value::int).filter(|l| (16 * 1024..=64 * 1024 * 1024).contains(l)).ok_or("bad piece length")? as u64;
    let pieces_raw = info.get("pieces").and_then(Value::bytes).ok_or("the torrent has no pieces")?;
    if pieces_raw.len() % 20 != 0 {
        return Err("bad pieces in the torrent".into());
    }
    let pieces: Vec<[u8; 20]> = pieces_raw.chunks_exact(20).map(|c| c.try_into().unwrap()).collect();
    if pieces.len() as u64 != length.div_ceil(piece_length) {
        return Err("the torrent's pieces do not match its length".into());
    }
    let strings = |key: &str| -> Vec<String> {
        match v.get(key) {
            Some(Value::Bytes(b)) => std::str::from_utf8(b).ok().map(|s| vec![s.to_string()]).unwrap_or_default(),
            Some(Value::List(l)) => l.iter().filter_map(|x| x.str().map(String::from)).collect(),
            _ => vec![],
        }
    };
    let web_seeds = strings("url-list").into_iter().filter(|u| web_seed_ok(u)).take(8).collect();
    let mut trackers = strings("announce");
    if let Some(l) = v.get("announce-list").and_then(Value::list) {
        trackers.extend(l.iter().filter_map(Value::list).flatten().filter_map(|x| x.str().map(String::from)));
    }
    trackers.retain(|t| t.starts_with("https://") || t.starts_with("udp://") || t.starts_with("http://"));
    trackers.truncate(8);
    Ok(Meta { name, length, piece_length, pieces, info_hash: sha1::digest(info_raw), web_seeds, trackers })
}

/// Check every piece of `file` against the torrent. Returns the indexes of bad pieces (empty = all good).
pub fn verify(meta: &Meta, file: &Path) -> Result<Vec<usize>, String> {
    let md = fs::metadata(file).map_err(|e| e.to_string())?;
    if md.len() != meta.length {
        return Err(format!("the file is {} bytes, the torrent says {}", md.len(), meta.length));
    }
    let mut f = fs::File::open(file).map_err(|e| e.to_string())?;
    let mut buf = vec![0u8; meta.piece_length as usize];
    let mut bad = Vec::new();
    for (i, want) in meta.pieces.iter().enumerate() {
        let n = if i + 1 == meta.pieces.len() { (meta.length - meta.piece_length * i as u64) as usize } else { buf.len() };
        f.read_exact(&mut buf[..n]).map_err(|e| e.to_string())?;
        if &sha1::digest(&buf[..n]) != want {
            bad.push(i);
        }
    }
    Ok(bad)
}

/// Make a single-file torrent (what `hosting/pack/make-hostpack.py` writes too), for tests and tools.
pub fn make(name: &str, data: &[u8], piece_length: u64, web_seeds: &[&str]) -> Vec<u8> {
    use std::collections::BTreeMap;
    let pieces: Vec<u8> = data.chunks(piece_length as usize).flat_map(|c| sha1::digest(c)).collect();
    let mut info = BTreeMap::new();
    info.insert(b"length".to_vec(), Value::Int(data.len() as i64));
    info.insert(b"name".to_vec(), Value::Bytes(name.as_bytes().to_vec()));
    info.insert(b"piece length".to_vec(), Value::Int(piece_length as i64));
    info.insert(b"pieces".to_vec(), Value::Bytes(pieces));
    let mut top = BTreeMap::new();
    top.insert(b"info".to_vec(), Value::Dict(info));
    if !web_seeds.is_empty() {
        top.insert(b"url-list".to_vec(), Value::List(web_seeds.iter().map(|s| Value::Bytes(s.as_bytes().to_vec())).collect()));
    }
    bencode::encode(&Value::Dict(top))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn make_parse_verify() {
        let data: Vec<u8> = (0..100_000u32).map(|i| (i % 251) as u8).collect();
        let t = make("pack.zip", &data, 32 * 1024, &["https://play.openvanilla.app/x/pack.zip", "ftp://nope", "http://127.0.0.1:9/p.zip"]);
        let m = parse(&t).unwrap();
        assert_eq!((m.length, m.pieces.len(), m.name.as_str()), (100_000, 4, "pack.zip"));
        assert_eq!(m.web_seeds.len(), 2, "ftp dropped");
        assert!(m.magnet().starts_with(&format!("magnet:?xt=urn:btih:{}", m.info_hash_hex())));
        let d = tempfile::tempdir().unwrap();
        let f = d.path().join("pack.zip");
        fs::write(&f, &data).unwrap();
        assert!(verify(&m, &f).unwrap().is_empty());
        let mut broken = data.clone();
        broken[40_000] ^= 1;
        fs::write(&f, &broken).unwrap();
        assert_eq!(verify(&m, &f).unwrap(), vec![1]);
        fs::write(&f, &data[..10]).unwrap();
        assert!(verify(&m, &f).is_err());
    }

    #[test]
    fn info_hash_is_over_the_raw_info() {
        // A torrent made by a standard tool: d4:infod6:lengthi3e4:name3:a.b12:piece lengthi16384e6:pieces20:<sha1("abc")>ee
        let mut raw = b"d4:infod6:lengthi3e4:name3:a.b12:piece lengthi16384e6:pieces20:".to_vec();
        raw.extend_from_slice(&sha1::digest(b"abc"));
        raw.extend_from_slice(b"ee");
        let m = parse(&raw).unwrap();
        let info = &raw[7..raw.len() - 1];
        assert_eq!(m.info_hash, sha1::digest(info));
    }

    #[test]
    fn refuses_odd_torrents() {
        assert!(parse(b"d4:infod5:filesle4:name1:xee").unwrap_err().contains("single-file"));
        let t = make("../evil", b"abc", 16384, &[]);
        assert!(parse(&t).is_err());
        let t = make("x", b"abc", 1000, &[]);
        assert!(parse(&t).unwrap_err().contains("piece length"));
    }
}
