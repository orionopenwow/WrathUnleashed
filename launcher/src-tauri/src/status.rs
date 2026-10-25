//! The chosen realm's live status for the Home page: a TCP ping to its login port and, for the official realm,
//! its own status file (`/wrath/status.json`, openvanilla-status-1: `{online, players, bots, ...}`).
//!
//! Read-only like the listings: a plain connect and a plain GET, nothing sent about the player.

use serde::Serialize;
use serde_json::Value;
use std::net::{TcpStream, ToSocketAddrs};
use std::time::{Duration, Instant};

/// The official realm's status file.
pub const OFFICIAL_STATUS_URL: &str = "https://play.openvanilla.app/wrath/status.json";
/// The login port when an address names none.
pub const DEFAULT_PORT: u16 = 3724;
pub const PING_TIMEOUT: Duration = Duration::from_secs(3);
pub const STATUS_TIMEOUT: Duration = Duration::from_secs(5);

/// What the Home page shows for a realm.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RealmStatus {
    /// "online", "partial" (login answers, world down), "offline", or "unknown" (nothing answered,
    /// which may be this PC's network rather than the realm).
    pub state: &'static str,
    pub ping_ms: Option<u32>,
    pub players: Option<u64>,
    pub bots: Option<u64>,
}

/// "host" or "host:port" to (host, port).
pub fn host_port(realm: &str) -> (String, u16) {
    let r = realm.trim();
    if let Some((h, p)) = r.rsplit_once(':') {
        if let Ok(p) = p.parse::<u16>() {
            return (h.to_string(), p);
        }
    }
    (r.to_string(), DEFAULT_PORT)
}

/// Milliseconds to open a TCP connection to the login port, or None.
pub fn ping(host: &str, port: u16, timeout: Duration) -> Option<u32> {
    let addrs = (host, port).to_socket_addrs().ok()?;
    for addr in addrs {
        let t0 = Instant::now();
        if TcpStream::connect_timeout(&addr, timeout).is_ok() {
            return Some(t0.elapsed().as_millis().min(u32::MAX as u128) as u32);
        }
    }
    None
}

/// (online, players, bots) from a status file, or None when it isn't one.
pub fn parse_status(v: &Value) -> Option<(bool, Option<u64>, Option<u64>)> {
    let online = v.get("online")?.as_bool()?;
    Some((online, v.get("players").and_then(Value::as_u64), v.get("bots").and_then(Value::as_u64)))
}

/// Put the ping and the status file together the way the Open Vanilla launcher did.
pub fn combine(ping_ms: Option<u32>, file: Option<(bool, Option<u64>, Option<u64>)>) -> RealmStatus {
    match file {
        Some((true, players, bots)) => RealmStatus { state: "online", ping_ms, players, bots },
        Some((false, _, _)) => {
            RealmStatus { state: if ping_ms.is_some() { "partial" } else { "offline" }, ping_ms, players: None, bots: None }
        }
        None => RealmStatus { state: if ping_ms.is_some() { "online" } else { "unknown" }, ping_ms, players: None, bots: None },
    }
}

/// The status of `realm`. `status_url` is the realm's own status file, when it has one.
pub fn check(realm: &str, status_url: Option<&str>) -> RealmStatus {
    let (host, port) = host_port(realm);
    let ping_ms = ping(&host, port, PING_TIMEOUT);
    let file = status_url.and_then(|u| crate::net::get(u, STATUS_TIMEOUT).ok()).and_then(|body| {
        serde_json::from_str::<Value>(&body).ok().and_then(|v| parse_status(&v))
    });
    combine(ping_ms, file)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    #[test]
    fn addresses_split_with_the_default_port() {
        assert_eq!(host_port("play.openvanilla.app"), ("play.openvanilla.app".into(), 3724));
        assert_eq!(host_port(" 1.2.3.4:8085 "), ("1.2.3.4".into(), 8085));
        assert_eq!(host_port("odd:name"), ("odd:name".into(), 3724));
    }

    #[test]
    fn ping_measures_a_listening_port_and_misses_a_closed_one() {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        assert!(ping("127.0.0.1", port, PING_TIMEOUT).is_some());
        drop(l);
        assert!(ping("127.0.0.1", port, Duration::from_millis(500)).is_none());
    }

    #[test]
    fn status_files_and_pings_combine() {
        let v: Value = serde_json::from_str(r#"{"online":true,"players":1,"bots":60,"uptime_s":5}"#).unwrap();
        let f = parse_status(&v);
        assert_eq!(f, Some((true, Some(1), Some(60))));
        assert_eq!(combine(Some(38), f), RealmStatus { state: "online", ping_ms: Some(38), players: Some(1), bots: Some(60) });
        assert_eq!(combine(Some(40), Some((false, None, None))).state, "partial");
        assert_eq!(combine(None, Some((false, None, None))).state, "offline");
        assert_eq!(combine(Some(12), None).state, "online");
        assert_eq!(combine(None, None).state, "unknown");
        assert!(parse_status(&serde_json::from_str::<Value>(r#"{"players":3}"#).unwrap()).is_none());
    }

    #[test]
    fn a_status_file_over_http_is_read() {
        let url = crate::net::testserver::serve_once("200 OK", r#"{"online":true,"players":2,"bots":5}"#);
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let realm = format!("127.0.0.1:{}", l.local_addr().unwrap().port());
        let s = check(&realm, Some(&url));
        assert_eq!((s.state, s.players, s.bots), ("online", Some(2), Some(5)));
        assert!(s.ping_ms.is_some());
    }
}
