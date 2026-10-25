//! The community realm list (read-only in L0): `{"schema": 1, "realms": [...]}` from the relay, cached.

use crate::net::{self, Listing};
use std::path::{Path, PathBuf};

pub const URL: &str = "https://relay.openvanilla.app/api/listing/realms.json";

pub fn cache_path(app_dir: &Path) -> PathBuf {
    app_dir.join("cache").join("realms.json")
}

pub fn fetch(app_dir: &Path) -> Result<Listing, String> {
    fetch_from(URL, app_dir)
}

pub fn fetch_from(url: &str, app_dir: &Path) -> Result<Listing, String> {
    net::fetch_listing(url, "realms", &cache_path(app_dir), net::TIMEOUT)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::net::testserver::*;

    #[test]
    fn counts_realms() {
        let d = tempfile::tempdir().unwrap();
        let url = serve_once("200 OK", r#"{"schema":1,"kind":"community","realms":[{"name":"One"},{"name":"Two"}]}"#);
        let l = fetch_from(&url, d.path()).unwrap();
        assert_eq!(l.count, 2);
        assert_eq!(l.names, vec!["One", "Two"]);
        assert!(cache_path(d.path()).exists());
    }
}
