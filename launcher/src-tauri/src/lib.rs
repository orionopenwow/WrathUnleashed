//! Leyline's core: game clients, launching, settings, the mod catalog and mod manager, the realm list,
//! hosting through the host kit, and the launcher's own update check.
//!
//! Everything here is plain Rust with no webview, so `cargo test --no-default-features` runs it anywhere.
//! The desktop app (`app` feature) wraps these modules in Tauri commands; see `app.rs`.
//!
//! Leyline never downloads game files: a client is the player's own folder. It sends no telemetry: the one count
//! it sends is an anonymous "this mod was installed" (a mod id, a build and a fresh random id per install, never
//! an account or machine id; Settings turns it off: `rankings`). Its network
//! calls: the Workshop catalog and mod zips (`catalog`, `mods`), the hub's rankings (`rankings`), the relay's realm list, realm lookup and
//! invite knock (`realms`, `host`), the official realm's status file (`status`) and GitHub's release list
//! (`update`). Each has an 8 second timeout; the listings fall back to a cached copy.

pub mod catalog;
pub mod clients;
pub mod deeplink; // leyline://install/<id> (hub rankings agent)
pub mod herokey; // Hero Key sign-in to community realms (docs/HERO-KEY-SSO.md; the herokey_sso flag)
pub mod host;
pub mod launch;
pub mod modes; // the Modes page: game modes one click away (modes agent)
pub mod mods;
pub mod net;
pub mod p2p;
pub mod pe_version;
pub mod rankings; // Discover's sort tabs, install counts and ratings (hub rankings agent)
pub mod realms;
pub mod settings;
pub mod social;
pub mod status;
pub mod themes; // theme packs (themes agent)
pub mod update;

#[cfg(feature = "app")]
mod app;
#[cfg(feature = "app")]
pub use app::run;

/// The official realm address the player kit uses (`labs/players/README.txt`).
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
    ("host", host::HOST_PAGE),
    ("hostguide", "https://github.com/orionopenwow/Leyline/blob/main/hosting/INSTALL-OPERATE.md"),
    ("hostdocs", "https://play.openvanilla.app/wrath/docs/hosting"), // the host console's guide (host/console.rs)
    ("alwayson", "https://play.openvanilla.app/wrath/docs/always-on"),
    ("themes", "https://github.com/orionopenwow/WrathUnleashed/blob/main/docs/THEMES.md"), // themes agent
    ("modders", "https://github.com/orionopenwow/WrathUnleashed/blob/main/mods/README-modders.md"),
    ("releases", update::RELEASES_PAGE),
    ("docker", host::docker::DESKTOP_URL),
    ("dockerengine", host::docker::ENGINE_URL),
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

    #[test]
    fn the_host_guide_links_to_the_site_docs() {
        assert_eq!(super::link("hostdocs"), Some("https://play.openvanilla.app/wrath/docs/hosting"));
        assert_eq!(super::link("alwayson"), Some("https://play.openvanilla.app/wrath/docs/always-on"));
        let mut names: Vec<&str> = super::LINKS.iter().map(|(n, _)| *n).collect();
        names.sort();
        names.dedup();
        assert_eq!(names.len(), super::LINKS.len(), "every name once");
    }
}
