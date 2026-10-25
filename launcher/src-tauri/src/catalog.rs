//! The mod catalog (read-only in L0): `{"format": 1, "mods": [...]}` from the site, cached for offline use.

use crate::net::{self, Listing};
use std::path::{Path, PathBuf};

pub const URL: &str = "https://play.openvanilla.app/wrath/mods/catalog.json";

pub fn cache_path(app_dir: &Path) -> PathBuf {
    app_dir.join("cache").join("catalog.json")
}

pub fn fetch(app_dir: &Path) -> Result<Listing, String> {
    fetch_from(URL, app_dir)
}

pub fn fetch_from(url: &str, app_dir: &Path) -> Result<Listing, String> {
    net::fetch_listing(url, "mods", &cache_path(app_dir), net::TIMEOUT)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::net::testserver::*;

    #[test]
    fn counts_mods_and_caches_under_the_app_dir() {
        let d = tempfile::tempdir().unwrap();
        let url = serve_once("200 OK", r#"{"format":1,"mods":[{"id":"a","name":"Alpha"}]}"#);
        let l = fetch_from(&url, d.path()).unwrap();
        assert_eq!(l.count, 1);
        assert!(cache_path(d.path()).exists());
        assert!(fetch_from(&dead_url(), d.path()).unwrap().from_cache);
    }

    #[test]
    fn the_url_is_https() {
        assert!(URL.starts_with("https://"));
    }
}
