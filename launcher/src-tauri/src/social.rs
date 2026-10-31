//! The Leyline sign-in in the launcher (Home's profile, `ui/social.js`): the name it shows, mod ratings and Hero Key
//! sign-in to community realms use it. The friends and messages actions below are no longer used by the UI (the
//! friends area went on 2026-10-30, in favour of the Discord and the forum); the server still answers them.
//!
//! The server is the Wrath portal's `/wrath/api/social` (`stream/social.py`); docs/SOCIAL.md has the whole picture.
//! Sign-in is the website's own, in the player's browser: the launcher asks for a device code, opens
//! `https://play.openvanilla.app/wrath/link?code=XXXX-XXXX`, the player approves it there (signed in with Google or
//! their Hero Key), and the launcher's next poll gets a session token. Only that token is kept, in
//! `<app data>/social-session.json` (0600 on Mac/Linux): never a password. It is revocable on the link page, and
//! "Sign out" here revokes it on the server too.
//!
//! The UI never names a URL: it names an action from `ACTIONS`, and only the parameters listed for that action are
//! sent. Each call gives up after 8 seconds, except the long poll for live updates (35 s).

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::path::{Path, PathBuf};
#[cfg(feature = "app")]
use std::sync::Mutex;
use std::time::{Duration, Instant};

/// The official server's social API.
pub const API_BASE: &str = "https://play.openvanilla.app/wrath/api/social";
/// Where the session token lives, in the app data folder.
pub const SESSION_FILE: &str = "social-session.json";
pub const TIMEOUT: Duration = Duration::from_secs(8);
pub const LONG_POLL: Duration = Duration::from_secs(35);

/// What the UI may call: (action, method, path, the parameters it may send).
pub const ACTIONS: &[(&str, &str, &str, &[&str])] = &[
    ("me", "GET", "me", &[]),
    ("state", "GET", "state", &[]),
    ("events", "GET", "events", &["since"]),
    ("thread", "GET", "thread", &["with", "before"]),
    ("profile", "POST", "profile", &["name", "main", "show_main", "offline"]),
    ("request", "POST", "request", &["to"]),
    ("accept", "POST", "accept", &["pid"]),
    ("decline", "POST", "decline", &["pid"]),
    ("remove", "POST", "remove", &["pid"]),
    ("block", "POST", "block", &["pid", "to"]),
    ("unblock", "POST", "unblock", &["pid"]),
    ("send", "POST", "send", &["to", "text"]),
    ("read", "POST", "read", &["with"]),
    ("report", "POST", "report", &["pid", "reason", "note"]),
    // Hero Key sign-in to a community realm (crate::herokey, docs/HERO-KEY-SSO.md)
    ("herokey", "POST", "herokey", &["realm"]),
];

/// The API base: the official one, or LEYLINE_SOCIAL_API for a test server (https, or http on this PC only).
pub fn base() -> String {
    match std::env::var("LEYLINE_SOCIAL_API") {
        Ok(b) if b.starts_with("https://") || b.starts_with("http://127.0.0.1:") || b.starts_with("http://localhost:") => {
            b.trim_end_matches('/').to_string()
        }
        _ => API_BASE.to_string(),
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
struct Saved {
    token: String,
    base: String,
}

fn session_path(dir: &Path) -> PathBuf {
    dir.join(SESSION_FILE)
}

fn token_ok(t: &str) -> bool {
    t.len() == 43 && t.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

/// The saved token for this API base, if any.
pub fn load_token(dir: &Path) -> Option<String> {
    let s: Saved = serde_json::from_slice(&std::fs::read(session_path(dir)).ok()?).ok()?;
    (s.base == base() && token_ok(&s.token)).then_some(s.token)
}

/// Keep the token (atomically; readable by this user only on Mac/Linux).
pub fn save_token(dir: &Path, token: &str) -> Result<(), String> {
    if !token_ok(token) {
        return Err("The server sent a bad sign-in.".into());
    }
    let bytes = serde_json::to_vec(&Saved { token: token.into(), base: base() }).map_err(|e| e.to_string())?;
    let path = session_path(dir);
    crate::settings::write_atomic(&path, &bytes).map_err(|e| format!("Could not save the sign-in: {e}"))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600));
    }
    Ok(())
}

pub fn forget(dir: &Path) {
    let _ = std::fs::remove_file(session_path(dir));
}

fn agent(read: Duration) -> ureq::Agent {
    ureq::AgentBuilder::new()
        .timeout_connect(TIMEOUT)
        .timeout_read(read)
        .timeout_write(TIMEOUT)
        .user_agent(concat!("Leyline/", env!("CARGO_PKG_VERSION")))
        .build()
}

/// POST a JSON body (ureq here is built without its json feature).
fn post_json(req: ureq::Request, body: &Value) -> Result<ureq::Response, ureq::Error> {
    req.set("Content-Type", "application/json").send_string(&body.to_string())
}

fn read_json(r: ureq::Response) -> Result<Value, String> {
    let body = r.into_string().map_err(|e| e.to_string())?;
    serde_json::from_str(&body).map_err(|_| "The server's answer didn't look right.".to_string())
}

/// Why a call failed: "signed_out" (the token is gone or revoked) or the server's own words.
fn failure(e: ureq::Error) -> String {
    match e {
        ureq::Error::Status(401, _) => "signed_out".into(),
        ureq::Error::Status(code, resp) => resp
            .into_string()
            .ok()
            .and_then(|b| serde_json::from_str::<Value>(&b).ok())
            .and_then(|v| v.get("error").and_then(Value::as_str).map(|s| s.chars().take(200).collect()))
            .unwrap_or_else(|| format!("The server answered {code}.")),
        ureq::Error::Transport(_) => "Can't reach the Leyline server. Check your connection.".into(),
    }
}

/// A device sign-in waiting for the player's approval in the browser.
#[derive(Debug, Clone)]
pub struct Pending {
    pub device_code: String,
    pub user_code: String,
    pub verify_url: String,
    pub interval: u64,
    pub until: Instant,
}

/// What the UI sees of a sign-in in progress.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct SignIn {
    /// "pending", "signed_in", "denied", "expired", "signed_out"
    pub state: String,
    pub user_code: String,
    pub verify_url: String,
}

/// The approval page address the server gave, if it is the one we expect (our server's /wrath/link with a code).
pub fn verify_url_ok(url: &str, user_code: &str) -> bool {
    let b = base();
    let site = b.trim_end_matches("/api/social");
    url == format!("{site}/link?code={user_code}") && code_ok(user_code)
}

fn code_ok(c: &str) -> bool {
    let ok = |s: &str| s.len() == 4 && s.bytes().all(|b| b"BCDFGHJKLMNPQRSTVWXZ".contains(&b));
    matches!(c.split_once('-'), Some((a, b)) if ok(a) && ok(b))
}

/// Ask the server for a device code.
pub fn start() -> Result<Pending, String> {
    let v = read_json(post_json(agent(TIMEOUT).post(&format!("{}/device/start", base())), &serde_json::json!({})).map_err(failure)?)?;
    let s = |k: &str| v.get(k).and_then(Value::as_str).unwrap_or("").to_string();
    let p = Pending {
        device_code: s("device_code"),
        user_code: s("user_code"),
        verify_url: s("verify_url"),
        interval: v.get("interval").and_then(Value::as_u64).unwrap_or(5).clamp(2, 30),
        until: Instant::now() + Duration::from_secs(v.get("expires_in").and_then(Value::as_u64).unwrap_or(600).min(1800)),
    };
    if !token_ok(&p.device_code) || !verify_url_ok(&p.verify_url, &p.user_code) {
        return Err("The server's answer didn't look right.".into());
    }
    Ok(p)
}

/// One poll: "pending", "slow_down", "denied", "expired", or "signed_in" (the token is saved).
pub fn poll(dir: &Path, p: &Pending) -> Result<String, String> {
    if Instant::now() > p.until {
        return Ok("expired".into());
    }
    let req = agent(TIMEOUT).post(&format!("{}/device/poll", base()));
    let v = read_json(post_json(req, &serde_json::json!({ "device_code": p.device_code })).map_err(failure)?)?;
    match v.get("status").and_then(Value::as_str).unwrap_or("") {
        "ok" => {
            save_token(dir, v.get("token").and_then(Value::as_str).unwrap_or(""))?;
            Ok("signed_in".into())
        }
        s @ ("pending" | "slow_down" | "denied" | "expired") => Ok(s.into()),
        _ => Err("The server's answer didn't look right.".into()),
    }
}

/// The request for an action: (method, path with query, JSON body for a POST). Unknown actions and parameters are
/// refused or dropped; GET parameters must be plain (letters, digits, - and _).
pub fn request_for(action: &str, args: &Value) -> Result<(&'static str, String, Option<Value>), String> {
    let (_, method, path, keys) = ACTIONS.iter().find(|a| a.0 == action).ok_or("Unknown action.")?;
    let empty = Map::new();
    let obj = args.as_object().unwrap_or(&empty);
    if *method == "GET" {
        let mut q = Vec::new();
        for k in keys.iter() {
            if let Some(v) = obj.get(*k) {
                let s = match v {
                    Value::String(s) => s.clone(),
                    Value::Number(n) => n.to_string(),
                    _ => continue,
                };
                if s.is_empty() || s.len() > 40 || !s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_') {
                    return Err("Bad parameter.".into());
                }
                q.push(format!("{k}={s}"));
            }
        }
        let p = if q.is_empty() { path.to_string() } else { format!("{path}?{}", q.join("&")) };
        return Ok(("GET", p, None));
    }
    let body: Map<String, Value> = keys.iter().filter_map(|k| obj.get(*k).map(|v| (k.to_string(), v.clone()))).collect();
    Ok(("POST", path.to_string(), Some(Value::Object(body))))
}

/// Call the API as the signed-in player. A 401 forgets the token and answers "signed_out".
pub fn call(dir: &Path, action: &str, args: &Value) -> Result<Value, String> {
    let token = load_token(dir).ok_or("signed_out")?;
    let (method, path, body) = request_for(action, args)?;
    let a = agent(if action == "events" { LONG_POLL } else { TIMEOUT });
    let url = format!("{}/{path}", base());
    let auth = format!("Bearer {token}");
    let res = if method == "GET" {
        a.get(&url).set("Authorization", &auth).call()
    } else {
        post_json(a.post(&url).set("Authorization", &auth), &body.unwrap_or(Value::Null))
    };
    match res {
        Ok(r) => read_json(r),
        Err(e) => {
            let msg = failure(e);
            if msg == "signed_out" {
                forget(dir);
            }
            Err(msg)
        }
    }
}

/// Sign out: revoke the token on the server (best effort) and forget it here.
pub fn sign_out(dir: &Path) {
    if let Some(token) = load_token(dir) {
        let req = agent(TIMEOUT).post(&format!("{}/token/revoke", base())).set("Authorization", &format!("Bearer {token}"));
        let _ = post_json(req, &serde_json::json!({}));
    }
    forget(dir);
}

#[cfg(feature = "app")]
pub mod commands {
    use super::*;

    static PENDING: Mutex<Option<Pending>> = Mutex::new(None);
    use tauri::AppHandle;
    use tauri_plugin_opener::OpenerExt;

    fn dir() -> PathBuf {
        crate::settings::app_dir()
    }

    async fn blocking<T: Send + 'static>(f: impl FnOnce() -> Result<T, String> + Send + 'static) -> Result<T, String> {
        tauri::async_runtime::spawn_blocking(f).await.map_err(|e| e.to_string())?
    }

    /// Signed in or not (no network).
    #[tauri::command]
    pub fn social_status() -> bool {
        load_token(&dir()).is_some()
    }

    /// Start a sign-in: get a code and open the approval page in the player's browser.
    #[tauri::command]
    pub async fn social_signin_start(app: AppHandle) -> Result<SignIn, String> {
        let p = blocking(start).await?;
        app.opener().open_url(p.verify_url.clone(), None::<&str>).map_err(|e| e.to_string())?;
        let out = SignIn { state: "pending".into(), user_code: p.user_code.clone(), verify_url: p.verify_url.clone() };
        *PENDING.lock().map_err(|_| "lock")? = Some(p);
        Ok(out)
    }

    /// Open the approval page again (the same code).
    #[tauri::command]
    pub fn social_signin_reopen(app: AppHandle) -> Result<(), String> {
        let url = PENDING.lock().map_err(|_| "lock")?.as_ref().map(|p| p.verify_url.clone()).ok_or("No sign-in in progress.")?;
        app.opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
    }

    /// Poll the sign-in in progress (the UI calls this every few seconds while the page waits).
    #[tauri::command]
    pub async fn social_signin_poll() -> Result<SignIn, String> {
        let p = PENDING.lock().map_err(|_| "lock")?.clone();
        let Some(p) = p else { return Ok(SignIn { state: "signed_out".into(), user_code: String::new(), verify_url: String::new() }) };
        let pc = p.clone();
        let state = blocking(move || poll(&dir(), &pc)).await?;
        if state != "pending" && state != "slow_down" {
            *PENDING.lock().map_err(|_| "lock")? = None;
        }
        let state = if state == "slow_down" { "pending".to_string() } else { state };
        Ok(SignIn { state, user_code: p.user_code, verify_url: p.verify_url })
    }

    /// Cancel a sign-in in progress.
    #[tauri::command]
    pub fn social_signin_cancel() {
        if let Ok(mut p) = PENDING.lock() {
            *p = None;
        }
    }

    /// One API call by action name (see ACTIONS).
    #[tauri::command]
    pub async fn social_call(action: String, args: Option<Value>) -> Result<Value, String> {
        blocking(move || call(&dir(), &action, &args.unwrap_or(Value::Null))).await
    }

    #[tauri::command]
    pub async fn social_signout() -> Result<(), String> {
        blocking(|| {
            sign_out(&dir());
            Ok(())
        })
        .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn token_saved_read_and_forgotten() {
        let d = tempfile::tempdir().unwrap();
        assert_eq!(load_token(d.path()), None);
        assert!(save_token(d.path(), "short").is_err());
        let t = "a".repeat(43);
        save_token(d.path(), &t).unwrap();
        assert_eq!(load_token(d.path()), Some(t.clone()));
        let raw = std::fs::read_to_string(d.path().join(SESSION_FILE)).unwrap();
        assert!(raw.contains(API_BASE) && !raw.to_lowercase().contains("password"));
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(d.path().join(SESSION_FILE)).unwrap().permissions().mode();
            assert_eq!(mode & 0o077, 0, "only this user may read the session");
        }
        forget(d.path());
        assert_eq!(load_token(d.path()), None);
    }

    #[test]
    fn a_token_for_another_server_is_not_used() {
        let d = tempfile::tempdir().unwrap();
        let s = Saved { token: "b".repeat(43), base: "https://elsewhere.example/api".into() };
        std::fs::write(d.path().join(SESSION_FILE), serde_json::to_vec(&s).unwrap()).unwrap();
        assert_eq!(load_token(d.path()), None);
    }

    #[test]
    fn only_listed_actions_and_parameters() {
        assert!(request_for("https://evil.example", &json!({})).is_err());
        assert!(request_for("token/revoke", &json!({})).is_err());
        let (m, p, b) = request_for("send", &json!({"to": "abcdefghij", "text": "hi", "url": "x", "token": "y"})).unwrap();
        assert_eq!((m, p.as_str()), ("POST", "send"));
        assert_eq!(b.unwrap(), json!({"to": "abcdefghij", "text": "hi"}));
        let (m, p, b) = request_for("thread", &json!({"with": "abcdefghij", "before": 42, "x": 1})).unwrap();
        assert_eq!((m, p.as_str(), b), ("GET", "thread?with=abcdefghij&before=42", None));
        assert!(request_for("events", &json!({"since": "1&x=2"})).is_err());
        assert_eq!(request_for("state", &Value::Null).unwrap().1, "state");
    }

    #[test]
    fn the_approval_page_must_be_ours() {
        assert!(verify_url_ok("https://play.openvanilla.app/wrath/link?code=BCDF-GHJK", "BCDF-GHJK"));
        assert!(!verify_url_ok("https://evil.example/wrath/link?code=BCDF-GHJK", "BCDF-GHJK"));
        assert!(!verify_url_ok("https://play.openvanilla.app/wrath/link?code=BCDF-GHJK&x=1", "BCDF-GHJK"));
        assert!(!verify_url_ok("https://play.openvanilla.app/wrath/link?code=ABCD-EFGH", "ABCD-EFGH"));
    }

    #[test]
    fn signed_out_without_a_token() {
        let d = tempfile::tempdir().unwrap();
        assert_eq!(call(d.path(), "state", &Value::Null).unwrap_err(), "signed_out");
    }
}
