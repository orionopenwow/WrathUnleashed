//! "Is there a newer Leyline?": the GitHub releases of the repo, tags `launcher-v*`. Only a check and a link to
//! the release page: Leyline never downloads or installs itself. One plain GET, cached for offline use.

use crate::mods::newer;
use crate::net;
use serde::Serialize;
use serde_json::Value;
use std::path::Path;

pub const URL: &str = "https://api.github.com/repos/orionopenwow/Leyline/releases?per_page=30";
pub const RELEASES_PAGE: &str = "https://github.com/orionopenwow/Leyline/releases";
pub const TAG_PREFIX: &str = "launcher-v";

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct UpdateInfo {
    pub current: String,
    /// The newest launcher release, when one was found.
    pub latest: Option<String>,
    pub newer: bool,
    /// Its release page (only ever a page under RELEASES_PAGE).
    pub url: Option<String>,
    pub from_cache: bool,
    pub error: Option<String>,
}

/// The newest `launcher-v*` release in a GitHub releases list: (version, page).
pub fn latest(v: &Value) -> Option<(String, String)> {
    v.as_array()?
        .iter()
        .filter(|r| !r.get("draft").and_then(Value::as_bool).unwrap_or(false))
        .filter_map(|r| {
            let tag = r.get("tag_name")?.as_str()?;
            let ver = tag.strip_prefix(TAG_PREFIX)?;
            crate::mods::version_tuple(ver)?;
            let page = r.get("html_url").and_then(Value::as_str).filter(|u| u.starts_with(&format!("{RELEASES_PAGE}/")) && net::plain_https(u))?;
            Some((ver.chars().take(32).collect::<String>(), page.to_string()))
        })
        .max_by_key(|(v, _)| crate::mods::version_tuple(v))
}

pub fn check(app_dir: &Path, current: &str) -> UpdateInfo {
    check_from(URL, app_dir, current)
}

pub fn check_from(url: &str, app_dir: &Path, current: &str) -> UpdateInfo {
    let cache = app_dir.join("cache").join("releases.json");
    let mut out = UpdateInfo { current: current.into(), ..Default::default() };
    match net::fetch_json(url, &cache, net::TIMEOUT, |v| v.as_array().map(|_| ()).ok_or_else(|| "not a release list".into())) {
        Ok(f) => {
            out.from_cache = f.from_cache;
            out.error = f.error;
            if let Some((ver, page)) = latest(&f.value) {
                out.newer = newer(&ver, current);
                out.latest = Some(ver);
                out.url = Some(page);
            }
        }
        Err(e) => out.error = Some(e),
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::net::testserver::*;

    const LIST: &str = r#"[
      {"tag_name":"launcher-v0.3.0","draft":true,"html_url":"https://github.com/orionopenwow/Leyline/releases/tag/launcher-v0.3.0"},
      {"tag_name":"launcher-v0.2.0","draft":false,"prerelease":true,"html_url":"https://github.com/orionopenwow/Leyline/releases/tag/launcher-v0.2.0"},
      {"tag_name":"v9.0.0","draft":false,"html_url":"https://github.com/orionopenwow/Leyline/releases/tag/v9.0.0"},
      {"tag_name":"launcher-v0.1.0","draft":false,"html_url":"https://github.com/orionopenwow/Leyline/releases/tag/launcher-v0.1.0"},
      {"tag_name":"launcher-v5.0.0","draft":false,"html_url":"https://evil.example.com/x"}
    ]"#;

    #[test]
    fn finds_the_newest_launcher_release() {
        let v: Value = serde_json::from_str(LIST).unwrap();
        let (ver, page) = latest(&v).unwrap();
        assert_eq!(ver, "0.2.0", "drafts, other tags and other sites are left out");
        assert!(page.ends_with("/tag/launcher-v0.2.0"));
    }

    #[test]
    fn says_newer_or_not_and_works_offline() {
        let d = tempfile::tempdir().unwrap();
        let base = serve_routes(vec![("/releases", "200 OK", LIST.as_bytes().to_vec())]);
        let u = check_from(&format!("{base}/releases"), d.path(), "0.1.0");
        assert!(u.newer && u.latest.as_deref() == Some("0.2.0") && !u.from_cache);
        assert!(!check_from(&format!("{base}/releases"), d.path(), "0.2.0").newer);
        let off = check_from(&dead_url(), d.path(), "0.1.0");
        assert!(off.newer && off.from_cache);
        let none = check_from(&dead_url(), tempfile::tempdir().unwrap().path(), "0.1.0");
        assert!(!none.newer && none.error.is_some());
    }
}
