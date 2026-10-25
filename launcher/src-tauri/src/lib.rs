//! Leyline's core: game clients, launching, settings, the mod catalog and the realm list.
//!
//! Everything here is plain Rust with no webview, so `cargo test --no-default-features` runs it anywhere.
//! The desktop app (`app` feature) wraps these modules in Tauri commands; see `app.rs`.
//!
//! Leyline never downloads game files: a client is the player's own folder. It sends no telemetry; the only
//! network calls are the two read-only listings in `catalog` and `realms`.

pub mod catalog;
pub mod clients;
pub mod launch;
pub mod net;
pub mod pe_version;
pub mod realms;
pub mod settings;

#[cfg(feature = "app")]
mod app;
#[cfg(feature = "app")]
pub use app::run;

/// The official realm address the WrathUnleashed player kit uses (`players/README.txt`).
pub const OFFICIAL_REALM: &str = "play.openvanilla.app";
/// The browser client.
pub const BROWSER_PLAY_URL: &str = "https://play.openvanilla.app/wrath";
