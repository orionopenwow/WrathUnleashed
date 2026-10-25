//! Read-only JSON listings fetched over HTTPS with a timeout and kept in a local cache.
//!
//! A listing that downloads and parses replaces the cache; when the network is down (or the reply is broken)
//! the last good copy is used and marked as such, so Leyline works offline. Nothing is ever sent but a plain
//! GET with a `Leyline/<version>` user agent: no ids, no telemetry.

use serde::Serialize;
use serde_json::Value;
use std::fs;
use std::path::Path;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub const TIMEOUT: Duration = Duration::from_secs(8);

/// A listing as the UI sees it.
#[derive(Debug, Clone, Serialize)]
pub struct Listing {
    pub count: usize,
    /// Display names of the first entries (at most 100), for the list on the page.
    pub names: Vec<String>,
    /// True when the network failed and this came from the cache.
    pub from_cache: bool,
    /// When the copy in use was saved (unix seconds), if known.
    pub saved_at: Option<u64>,
    /// Why the network fetch failed, when it did.
    pub error: Option<String>,
}

/// The entries under `key` (or the top level, when it is an array).
pub fn entries<'a>(v: &'a Value, key: &str) -> Option<&'a Vec<Value>> {
    v.get(key).and_then(Value::as_array).or_else(|| v.as_array())
}

fn names(items: &[Value]) -> Vec<String> {
    items
        .iter()
        .take(100)
        .filter_map(|i| i.get("name").and_then(Value::as_str))
        .map(|s| s.chars().take(80).collect())
        .collect()
}

fn now() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn mtime(p: &Path) -> Option<u64> {
    fs::metadata(p).ok()?.modified().ok()?.duration_since(UNIX_EPOCH).ok().map(|d| d.as_secs())
}

/// GET `url` as text, failing after `timeout`.
pub fn get(url: &str, timeout: Duration) -> Result<String, String> {
    let agent = ureq::AgentBuilder::new().timeout(timeout).user_agent(concat!("Leyline/", env!("CARGO_PKG_VERSION"))).build();
    agent.get(url).call().map_err(|e| e.to_string())?.into_string().map_err(|e| e.to_string())
}

/// Fetch the listing at `url` (entries under `key`), falling back to `cache`.
pub fn fetch_listing(url: &str, key: &str, cache: &Path, timeout: Duration) -> Result<Listing, String> {
    let fresh = get(url, timeout).and_then(|body| {
        let v: Value = serde_json::from_str(&body).map_err(|e| format!("not JSON: {e}"))?;
        let items = entries(&v, key).ok_or_else(|| format!("no \"{key}\" list in the reply"))?;
        Ok((body.clone(), items.len(), names(items)))
    });
    match fresh {
        Ok((body, count, names)) => {
            // A cache that cannot be written is not worth failing over.
            let _ = crate::settings::write_atomic(cache, body.as_bytes());
            Ok(Listing { count, names, from_cache: false, saved_at: Some(now()), error: None })
        }
        Err(err) => {
            let cached = fs::read_to_string(cache)
                .ok()
                .and_then(|t| serde_json::from_str::<Value>(&t).ok())
                .and_then(|v| entries(&v, key).map(|i| (i.len(), names(i))));
            match cached {
                Some((count, names)) => {
                    Ok(Listing { count, names, from_cache: true, saved_at: mtime(cache), error: Some(err) })
                }
                None => Err(format!("Offline and nothing cached yet ({err}).")),
            }
        }
    }
}

#[cfg(test)]
pub mod testserver {
    use std::io::{Read, Write};
    use std::net::TcpListener;

    /// Serve `body` once on a local port; returns the URL.
    pub fn serve_once(status: &'static str, body: &'static str) -> String {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        std::thread::spawn(move || {
            if let Ok((mut s, _)) = l.accept() {
                let mut buf = [0u8; 2048];
                let _ = s.read(&mut buf);
                let _ = write!(
                    s,
                    "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
            }
        });
        format!("http://127.0.0.1:{port}/x.json")
    }

    /// A URL nothing listens on.
    pub fn dead_url() -> String {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        drop(l);
        format!("http://127.0.0.1:{port}/x.json")
    }
}

#[cfg(test)]
mod tests {
    use super::testserver::*;
    use super::*;

    const T: Duration = Duration::from_secs(3);

    #[test]
    fn fresh_then_offline_from_cache() {
        let d = tempfile::tempdir().unwrap();
        let cache = d.path().join("cache/l.json");
        let url = serve_once("200 OK", r#"{"format":1,"mods":[{"name":"A"},{"name":"B"},{"id":"c"}]}"#);
        let l = fetch_listing(&url, "mods", &cache, T).unwrap();
        assert_eq!((l.count, l.from_cache), (3, false));
        assert_eq!(l.names, vec!["A", "B"]);
        assert!(cache.exists());

        let off = fetch_listing(&dead_url(), "mods", &cache, T).unwrap();
        assert_eq!((off.count, off.from_cache), (3, true));
        assert!(off.error.is_some() && off.saved_at.is_some());
    }

    #[test]
    fn offline_with_no_cache_is_an_error() {
        let d = tempfile::tempdir().unwrap();
        assert!(fetch_listing(&dead_url(), "mods", &d.path().join("none.json"), T).unwrap_err().contains("Offline"));
    }

    #[test]
    fn a_broken_reply_does_not_replace_the_cache() {
        let d = tempfile::tempdir().unwrap();
        let cache = d.path().join("l.json");
        fs::write(&cache, r#"{"realms":[{"name":"R"}]}"#).unwrap();
        let l = fetch_listing(&serve_once("200 OK", "<html>oops</html>"), "realms", &cache, T).unwrap();
        assert!(l.from_cache);
        assert_eq!(l.count, 1);
        let l = fetch_listing(&serve_once("500 Internal Server Error", "{}"), "realms", &cache, T).unwrap();
        assert!(l.from_cache);
        assert!(fs::read_to_string(&cache).unwrap().contains("\"R\""));
    }

    #[test]
    fn a_top_level_array_counts() {
        let v: Value = serde_json::from_str(r#"[1,2]"#).unwrap();
        assert_eq!(entries(&v, "mods").unwrap().len(), 2);
    }
}
