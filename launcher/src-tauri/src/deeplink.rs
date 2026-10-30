//! `leyline://` links: a hub page's "Install with Leyline" button opens `leyline://install/<catalog id>`.
//!
//! The scheme is registered by the installer (tauri.conf.json `plugins.deep-link.desktop.schemes`). On Windows and
//! Linux the OS starts Leyline with the link as an argument; `from_args` finds it. A link never installs anything
//! by itself: the UI shows the project and the player clicks INSTALL (a web page can open a link, so the click is
//! the consent). Only `install/<id>` with a well-formed catalog id is understood; anything else is ignored.

/// What a link asks for.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(tag = "action", content = "id", rename_all = "lowercase")]
pub enum Link {
    /// Show this catalog project with its INSTALL button.
    Install(String),
}

pub const SCHEME: &str = "leyline";

/// A catalog id the link may name: `mod:<id>`, `link:<12 hex>` (catalog.rs id_ok) or `theme:<id>`.
fn id_ok(id: &str) -> bool {
    if let Some(t) = id.strip_prefix("theme:") {
        return (2..=32).contains(&t.len())
            && t.starts_with(|c: char| c.is_ascii_lowercase())
            && t.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-');
    }
    crate::catalog::id_ok(id)
}

/// Parse `leyline://install/<id>` (the id's `:` may come percent-encoded as `%3A`; a trailing `/` is fine).
pub fn parse(url: &str) -> Option<Link> {
    let url = url.trim();
    if url.len() > 200 || url.chars().any(|c| c.is_control() || c.is_whitespace()) {
        return None;
    }
    let (scheme, rest) = url.split_once("://")?;
    if !scheme.eq_ignore_ascii_case(SCHEME) {
        return None;
    }
    let rest = rest.split(['?', '#']).next()?.trim_end_matches('/');
    let (action, id) = rest.split_once('/')?;
    let id = id.replace("%3A", ":").replace("%3a", ":");
    match action {
        "install" if id_ok(&id) => Some(Link::Install(id)),
        _ => None,
    }
}

/// The first `leyline://` link among the program's arguments (how Windows and Linux hand it over).
pub fn from_args<I: IntoIterator<Item = String>>(args: I) -> Option<Link> {
    args.into_iter().skip(1).take(8).find_map(|a| parse(&a))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_install_links() {
        assert_eq!(parse("leyline://install/mod:pings"), Some(Link::Install("mod:pings".into())));
        assert_eq!(parse("LEYLINE://install/mod%3Apings/"), Some(Link::Install("mod:pings".into())));
        assert_eq!(parse("leyline://install/link:0123456789ab?from=hub"), Some(Link::Install("link:0123456789ab".into())));
        assert_eq!(parse("leyline://install/theme:night-sky"), Some(Link::Install("theme:night-sky".into())));
    }

    #[test]
    fn refuses_everything_else() {
        for bad in [
            "https://install/mod:pings",
            "leyline://install/",
            "leyline://install/mod:../../x",
            "leyline://install/mod:Pings",
            "leyline://install/link:xyz",
            "leyline://run/mod:pings",
            "leyline://install/mod:pings evil",
            "leyline:install/mod:pings",
            "leyline://install/theme:../x",
            &format!("leyline://install/mod:{}", "a".repeat(300)),
        ] {
            assert_eq!(parse(bad), None, "{bad}");
        }
    }

    #[test]
    fn finds_the_link_in_the_arguments() {
        let args = |v: &[&str]| v.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        assert_eq!(from_args(args(&["leyline.exe", "leyline://install/mod:pings"])), Some(Link::Install("mod:pings".into())));
        assert_eq!(from_args(args(&["leyline.exe", "--flag", "leyline://install/mod:pings"])), Some(Link::Install("mod:pings".into())));
        assert_eq!(from_args(args(&["leyline://install/mod:pings"])), None, "the program name is not an argument");
        assert_eq!(from_args(args(&["leyline.exe"])), None);
        let json = serde_json::to_value(Link::Install("mod:pings".into())).unwrap();
        assert_eq!(json, serde_json::json!({"action": "install", "id": "mod:pings"}));
    }
}
