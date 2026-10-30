//! P2P and torrent plumbing, built and tested but OFF until the flags say otherwise (`flags`).
//!
//! * `flags`: the site's flags file (sha256-checked) plus this PC's overrides. Everything defaults to off.
//! * `transfer`: one download path for Leyline's own packages (mods, theme packs, the Host pack, launcher
//!   updates): HTTPS, or a torrent's swarm / web seeds when `torrent_downloads` is on. Every result passes the
//!   refusal list (`checker`: never game data, never a client) and a sha256 check.
//! * `torrent`, `bencode`, `sha1`: single-file `.torrent` metainfo, web seeds and the piece check.
//! * `nat`, `direct`: the NAT check (STUN) and the rule for when a direct connection to a hosted realm may
//!   replace the relay (`p2p_hosting`).
//!
//! See docs/P2P-AND-TORRENT.md.

pub mod bencode;
pub mod checker;
pub mod direct;
pub mod flags;
pub mod nat;
pub mod sha1;
pub mod torrent;
pub mod transfer;

#[cfg(feature = "app")]
pub mod cmds;
