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
    /// The official realm's game data killswitch (`"gamedata_streaming"` in its status file): `Some(false)` when
    /// its server streams no game data, so browser play needs the player's own game folder. None: not said.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub gamedata_streaming: Option<bool>,
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

/// `"gamedata_streaming"` from a status file: false = the realm's server streams no game data (browser play needs
/// the player's own game folder), true = it streams; None when the file doesn't say.
pub fn gamedata_streaming(v: &Value) -> Option<bool> {
    v.get("gamedata_streaming").and_then(Value::as_bool)
}

/// Put the ping and the status file together the way the older Python launcher (Leyline Launcher) did.
pub fn combine(ping_ms: Option<u32>, file: Option<(bool, Option<u64>, Option<u64>)>) -> RealmStatus {
    match file {
        Some((true, players, bots)) => RealmStatus { state: "online", ping_ms, players, bots, gamedata_streaming: None },
        Some((false, _, _)) => {
            RealmStatus { state: if ping_ms.is_some() { "partial" } else { "offline" }, ping_ms, players: None, bots: None, gamedata_streaming: None }
        }
        None => RealmStatus { state: if ping_ms.is_some() { "online" } else { "unknown" }, ping_ms, players: None, bots: None, gamedata_streaming: None },
    }
}

/// The status of `realm`. `status_url` is the realm's own status file, when it has one.
pub fn check(realm: &str, status_url: Option<&str>) -> RealmStatus {
    let (host, port) = host_port(realm);
    let ping_ms = ping(&host, port, PING_TIMEOUT);
    let doc = status_url
        .and_then(|u| crate::net::get(u, STATUS_TIMEOUT).ok())
        .and_then(|body| serde_json::from_str::<Value>(&body).ok());
    let mut s = combine(ping_ms, doc.as_ref().and_then(parse_status));
    s.gamedata_streaming = doc.as_ref().and_then(gamedata_streaming);
    s
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
        assert_eq!(combine(Some(38), f), RealmStatus { state: "online", ping_ms: Some(38), players: Some(1), bots: Some(60), gamedata_streaming: None });
        assert_eq!(combine(Some(40), Some((false, None, None))).state, "partial");
        assert_eq!(combine(None, Some((false, None, None))).state, "offline");
        assert_eq!(combine(Some(12), None).state, "online");
        assert_eq!(combine(None, None).state, "unknown");
        assert!(parse_status(&serde_json::from_str::<Value>(r#"{"players":3}"#).unwrap()).is_none());
    }

    #[test]
    fn the_game_data_killswitch_is_read() {
        let off: Value = serde_json::from_str(r#"{"online":true,"players":1,"gamedata_streaming":false,"gamedata_since":"2026-10-29T18:04:00Z"}"#).unwrap();
        assert_eq!(gamedata_streaming(&off), Some(false));
        assert_eq!(gamedata_streaming(&serde_json::from_str::<Value>(r#"{"online":true,"gamedata_streaming":true}"#).unwrap()), Some(true));
        assert_eq!(gamedata_streaming(&serde_json::from_str::<Value>(r#"{"online":true}"#).unwrap()), None);
        assert_eq!(gamedata_streaming(&serde_json::from_str::<Value>(r#"{"gamedata_streaming":"no"}"#).unwrap()), None);
        // the page gets the field only when the realm says it
        let s = combine(None, None);
        assert!(!serde_json::to_string(&s).unwrap().contains("gamedata"));
        let url = crate::net::testserver::serve_once("200 OK", r#"{"online":true,"players":2,"bots":5,"gamedata_streaming":false}"#);
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let realm = format!("127.0.0.1:{}", l.local_addr().unwrap().port());
        let s = check(&realm, Some(&url));
        assert_eq!((s.state, s.gamedata_streaming), ("online", Some(false)));
        assert!(serde_json::to_string(&s).unwrap().contains(r#""gamedata_streaming":false"#));
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
