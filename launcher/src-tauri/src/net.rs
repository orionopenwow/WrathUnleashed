//! The network: JSON listings fetched over HTTPS with a timeout and kept in a local cache, mod downloads with a
//! size cap, and the two small relay calls (a realm lookup, an invite knock).
//!
//! A listing that downloads and parses replaces the cache; when the network is down (or the reply is broken)
//! the last good copy is used and marked as such, so Leyline works offline. Requests carry only a
//! `Leyline/<version>` user agent and what the request itself needs: no ids, no telemetry.

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

/// A JSON document fetched with a cache fallback.
#[derive(Debug, Clone)]
pub struct Fetched {
    pub value: Value,
    /// True when the network failed and this came from the cache.
    pub from_cache: bool,
    pub saved_at: Option<u64>,
    pub error: Option<String>,
}

/// GET `url` as JSON; `check` says whether the reply is the document we want. A good reply replaces `cache`;
/// otherwise the last good copy in `cache` is used (and marked), so the launcher works offline.
pub fn fetch_json(
    url: &str,
    cache: &Path,
    timeout: Duration,
    check: impl Fn(&Value) -> Result<(), String>,
) -> Result<Fetched, String> {
    let fresh = get(url, timeout).and_then(|body| {
        let v: Value = serde_json::from_str(&body).map_err(|e| format!("not JSON: {e}"))?;
        check(&v)?;
        Ok((body, v))
    });
    match fresh {
        Ok((body, value)) => {
            // A cache that cannot be written is not worth failing over.
            let _ = crate::settings::write_atomic(cache, body.as_bytes());
            Ok(Fetched { value, from_cache: false, saved_at: Some(now()), error: None })
        }
        Err(err) => match read_cache(cache).filter(|(v, _)| check(v).is_ok()) {
            Some((value, saved_at)) => Ok(Fetched { value, from_cache: true, saved_at, error: Some(err) }),
            None => Err(format!("Offline and nothing cached yet ({err}).")),
        },
    }
}

/// The cached copy of a listing, with when it was saved.
pub fn read_cache(cache: &Path) -> Option<(Value, Option<u64>)> {
    let v = fs::read_to_string(cache).ok().and_then(|t| serde_json::from_str::<Value>(&t).ok())?;
    Some((v, mtime(cache)))
}

/// Fetch the listing at `url` (entries under `key`), falling back to `cache`.
pub fn fetch_listing(url: &str, key: &str, cache: &Path, timeout: Duration) -> Result<Listing, String> {
    let f = fetch_json(url, cache, timeout, |v| {
        entries(v, key).map(|_| ()).ok_or_else(|| format!("no \"{key}\" list in the reply"))
    })?;
    let items = entries(&f.value, key).map(|v| v.as_slice()).unwrap_or(&[]);
    Ok(Listing { count: items.len(), names: names(items), from_cache: f.from_cache, saved_at: f.saved_at, error: f.error })
}

fn agent(connect: Duration, read: Duration) -> ureq::Agent {
    ureq::AgentBuilder::new()
        .timeout_connect(connect)
        .timeout_read(read)
        .timeout_write(read)
        .user_agent(concat!("Leyline/", env!("CARGO_PKG_VERSION")))
        .build()
}

/// The error text a JSON API put in its reply (`{"error": "..."}`), or the HTTP status.
fn api_error(e: ureq::Error) -> String {
    match e {
        ureq::Error::Status(code, resp) => {
            let msg = resp
                .into_string()
                .ok()
                .and_then(|b| serde_json::from_str::<Value>(&b).ok())
                .and_then(|v| v.get("error").and_then(Value::as_str).map(|s| s.chars().take(200).collect::<String>()));
            msg.unwrap_or_else(|| format!("the server answered {code}"))
        }
        other => other.to_string(),
    }
}

/// GET `url` as JSON (no cache): for small live lookups such as a relay realm.
pub fn get_json(url: &str, timeout: Duration) -> Result<Value, String> {
    let body = agent(timeout, timeout).get(url).call().map_err(api_error)?.into_string().map_err(|e| e.to_string())?;
    serde_json::from_str(&body).map_err(|e| format!("not JSON: {e}"))
}

/// POST a JSON body and read a JSON reply.
pub fn post_json(url: &str, body: &Value, timeout: Duration) -> Result<Value, String> {
    let reply = agent(timeout, timeout)
        .post(url)
        .set("Content-Type", "application/json")
        .send_string(&body.to_string())
        .map_err(api_error)?
        .into_string()
        .map_err(|e| e.to_string())?;
    serde_json::from_str(&reply).map_err(|e| format!("not JSON: {e}"))
}

/// Download `url` into `dest`, at most `max` bytes. Returns (bytes, sha256 hex). A reply that says or turns out
/// to be bigger than `max` is refused and nothing is left at `dest`.
pub fn download(url: &str, dest: &Path, max: u64, connect: Duration, read: Duration) -> Result<(u64, String), String> {
    use sha2::{Digest, Sha256};
    use std::io::{Read, Write};
    let resp = agent(connect, read).get(url).call().map_err(api_error)?;
    if let Some(n) = resp.header("Content-Length").and_then(|v| v.trim().parse::<u64>().ok()) {
        if n > max {
            return Err(format!("the download is {} MB, more than the {} MB limit", n / 1_048_576, max / 1_048_576));
        }
    }
    let result = (|| {
        if let Some(d) = dest.parent() {
            fs::create_dir_all(d).map_err(|e| e.to_string())?;
        }
        let mut f = fs::File::create(dest).map_err(|e| e.to_string())?;
        let mut r = resp.into_reader().take(max + 1);
        let mut h = Sha256::new();
        let mut buf = vec![0u8; 64 * 1024];
        let mut total = 0u64;
        loop {
            let n = r.read(&mut buf).map_err(|e| format!("the download broke off: {e}"))?;
            if n == 0 {
                break;
            }
            total += n as u64;
            if total > max {
                return Err(format!("the download is more than the {} MB limit", max / 1_048_576));
            }
            h.update(&buf[..n]);
            f.write_all(&buf[..n]).map_err(|e| e.to_string())?;
        }
        f.sync_all().map_err(|e| e.to_string())?;
        Ok((total, hex(&h.finalize())))
    })();
    if result.is_err() {
        let _ = fs::remove_file(dest);
    }
    result
}

/// Lower-case hex.
pub fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

/// The sha256 of a file, as lower-case hex.
pub fn sha256_file(p: &Path) -> std::io::Result<String> {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    let mut f = fs::File::open(p)?;
    let mut h = Sha256::new();
    let mut buf = vec![0u8; 64 * 1024];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(hex(&h.finalize()))
}

/// "scheme://host[:port]" of a URL, lower-cased, or None.
pub fn origin(url: &str) -> Option<String> {
    let (scheme, rest) = url.split_once("://")?;
    let host = rest.split(['/', '?', '#']).next()?;
    if host.is_empty() || host.contains('@') {
        return None;
    }
    Some(format!("{}://{}", scheme.to_ascii_lowercase(), host.to_ascii_lowercase()))
}

/// A plain https URL with a normal host name and nothing odd in it: what the UI may be handed to open.
pub fn plain_https(url: &str) -> bool {
    if url.len() > 400 || !url.starts_with("https://") || url.chars().any(|c| c.is_whitespace() || c.is_control()) {
        return false;
    }
    let Some(o) = origin(url) else { return false };
    let host = &o["https://".len()..];
    let parts: Vec<&str> = host.split('.').collect();
    parts.len() >= 2
        && parts.iter().all(|p| !p.is_empty() && p.len() <= 63 && p.chars().all(|c| c.is_ascii_alphanumeric() || c == '-'))
        && parts.last().is_some_and(|t| t.chars().all(|c| c.is_ascii_alphabetic()) && t.len() >= 2)
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

    /// Serve `body` (any bytes, any content type) to every request on a local port, for as long as the test
    /// runs; returns the base URL (http://127.0.0.1:port). Requests are answered by path: `routes` maps a path
    /// to (status, body); anything else is a 404.
    pub fn serve_routes(routes: Vec<(&'static str, &'static str, Vec<u8>)>) -> String {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        std::thread::spawn(move || {
            for s in l.incoming() {
                let Ok(mut s) = s else { continue };
                let mut buf = Vec::new();
                let mut chunk = [0u8; 4096];
                // Read the request head (and a small body, if any).
                while !buf.windows(4).any(|w| w == b"\r\n\r\n") {
                    match s.read(&mut chunk) {
                        Ok(0) | Err(_) => break,
                        Ok(n) => buf.extend_from_slice(&chunk[..n]),
                    }
                }
                let head = String::from_utf8_lossy(&buf).to_string();
                let want = head
                    .lines()
                    .find_map(|l| l.to_ascii_lowercase().strip_prefix("content-length:").map(|v| v.trim().to_string()))
                    .and_then(|v| v.parse::<usize>().ok())
                    .unwrap_or(0);
                let have = buf.windows(4).position(|w| w == b"\r\n\r\n").map(|i| buf.len() - i - 4).unwrap_or(0);
                let mut left = want.saturating_sub(have);
                while left > 0 {
                    match s.read(&mut chunk) {
                        Ok(0) | Err(_) => break,
                        Ok(n) => left = left.saturating_sub(n),
                    }
                }
                let path = head.split_whitespace().nth(1).unwrap_or("/").to_string();
                let (status, body): (&str, &[u8]) = routes
                    .iter()
                    .find(|(p, _, _)| *p == path)
                    .map(|(_, st, b)| (*st, b.as_slice()))
                    .unwrap_or(("404 Not Found", b"{\"error\":\"not found\"}"));
                let _ = write!(s, "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", body.len());
                let _ = s.write_all(body);
            }
        });
        format!("http://127.0.0.1:{port}")
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
