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
pub mod status;

#[cfg(feature = "app")]
mod app;
#[cfg(feature = "app")]
pub use app::run;

/// The official realm address the WrathUnleashed player kit uses (`players/README.txt`).
pub const OFFICIAL_REALM: &str = "play.openvanilla.app";
/// The browser client.
pub const BROWSER_PLAY_URL: &str = "https://play.openvanilla.app/wrath";

/// The only pages the launcher opens in the player's browser, by name. The UI names one; it can never pass a URL.
pub const LINKS: &[(&str, &str)] = &[
    ("play", BROWSER_PLAY_URL),
    ("account", "https://play.openvanilla.app/wrath"),
    ("news", "https://play.openvanilla.app/wrath/leyline"),
    ("docs", "https://play.openvanilla.app/wrath/docs"),
    ("mods", "https://play.openvanilla.app/wrath/mods"),
    ("discord", "https://discord.gg/hVeUxYwbkr"),
    ("support", "https://ko-fi.com/orionvanilla"),
    ("github", "https://github.com/orionopenwow/Leyline"),
];

/// The address for a named link, if it is one of `LINKS`.
pub fn link(name: &str) -> Option<&'static str> {
    LINKS.iter().find(|(n, _)| *n == name).map(|(_, u)| *u)
}

#[cfg(test)]
mod link_tests {
    #[test]
    fn only_listed_links_open() {
        assert_eq!(super::link("discord"), Some("https://discord.gg/hVeUxYwbkr"));
        assert!(super::link("https://example.com").is_none());
        assert!(super::LINKS.iter().all(|(_, u)| u.starts_with("https://")));
    }
}
