//! Hero Key sign-in to community realms (Beacons) from the launcher: docs/HERO-KEY-SSO.md.
//!
//! Behind the `herokey_sso` flag (`p2p::flags`, OFF by default). With it on, "Sign in with your Hero Key" on a realm
//! card does, in order:
//!
//! 1. asks the website for a ticket for that realm (`POST /wrath/api/social/herokey {realm}`, with the launcher's
//!    own revocable session token from the Leyline sign-in on Home, `crate::social`): a signed assertion for that realm and
//!    a one-time login (`HK...` + a random password) made for this sign-in only;
//! 2. posts the assertion to the realm's relay (`POST https://<relay>/api/realms/<id>/herokey`); the realm's agent
//!    checks the website's signature and sets that login on the player's account there (made on first use). The
//!    password never goes to the relay or the realm, only its SRP verifier inside the signed assertion;
//! 3. writes the account name into the client's `WTF/Config.wtf` (`SET accountName`), points the client at the
//!    realm and starts it. The 3.3.5a client has no way to take a password from outside, so the UI shows the
//!    one-time password for the player to type; it works for 10 minutes and is never saved here.

use serde::Serialize;
use serde_json::Value;
use std::path::Path;
use std::time::Duration;

pub const REDEEM_TIMEOUT: Duration = Duration::from_secs(10);

/// What the site hands back for one realm, checked.
#[derive(Debug, Clone, PartialEq)]
pub struct Ticket {
    pub realm: String,
    pub assertion: Value,
    pub sig: String,
    pub user: String,
    pub pass: String,
    pub redeem: String,
}

/// What the UI gets: the account and the one-time password to type at the login screen, and how long it works.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Login {
    pub realm: String,
    pub user: String,
    pub pass: String,
    pub valid_s: u64,
}

/// `HK` + 14 base32 letters (upper case): the realm's account for this player's pseudonym.
pub fn account_ok(s: &str) -> bool {
    s.len() == 16 && s.starts_with("HK") && s[2..].chars().all(|c| c.is_ascii_uppercase() || ('2'..='7').contains(&c))
}

fn pass_ok(s: &str) -> bool {
    (1..=16).contains(&s.len()) && s.bytes().all(|b| (0x21..=0x7e).contains(&b))
}

/// The redeem address: `https://<relay>/api/realms/<realm>/herokey` on a plain relay host name (or a local test
/// server when LEYLINE_SOCIAL_API points at one).
pub fn redeem_ok(url: &str, realm: &str) -> bool {
    let tail = format!("/api/realms/{realm}/herokey");
    let Some(host) = url.strip_suffix(&tail) else { return false };
    if let Some(h) = host.strip_prefix("https://") {
        return crate::realms::relay_ok(h);
    }
    let local = crate::social::base().starts_with("http://127.0.0.1:");
    local && host.strip_prefix("http://127.0.0.1:").is_some_and(|p| p.parse::<u16>().is_ok())
}

/// Check the site's answer for `realm`.
pub fn parse_ticket(v: &Value, realm: &str) -> Result<Ticket, String> {
    let bad = || "The server's answer didn't look right.".to_string();
    let s = |x: &Value, k: &str| x.get(k).and_then(Value::as_str).unwrap_or("").to_string();
    if v.get("ok").and_then(Value::as_bool) != Some(true) || s(v, "realm") != realm {
        return Err(bad());
    }
    let assertion = v.get("assertion").filter(|a| a.is_object()).cloned().ok_or_else(bad)?;
    let sig = s(v, "sig");
    let login = v.get("login").ok_or_else(bad)?;
    let (user, pass, redeem) = (s(login, "user"), s(login, "pass"), s(v, "redeem"));
    let sig_ok = sig.len() == 128 && sig.bytes().all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase());
    if s(&assertion, "aud") != realm || !sig_ok || !account_ok(&user) || !pass_ok(&pass) || !redeem_ok(&redeem, realm) {
        return Err(bad());
    }
    Ok(Ticket { realm: realm.into(), assertion, sig, user, pass, redeem })
}

/// Step 1: a ticket from the site, as the signed-in player ("signed_out" when the launcher isn't signed in).
pub fn request(app_dir: &Path, realm: &str) -> Result<Ticket, String> {
    if !crate::realms::realm_id_ok(realm) {
        return Err("That is not a realm id.".into());
    }
    let v = crate::social::call(app_dir, "herokey", &serde_json::json!({ "realm": realm }))?;
    parse_ticket(&v, realm)
}

/// Step 2: the realm takes the assertion and sets the one-time login. Returns how long it works, in seconds.
pub fn redeem(t: &Ticket) -> Result<u64, String> {
    let body = serde_json::json!({ "assertion": t.assertion, "sig": t.sig });
    let v = crate::net::post_json(&t.redeem, &body, REDEEM_TIMEOUT).map_err(|e| format!("The realm refused the sign-in: {e}"))?;
    if v.get("ok").and_then(Value::as_bool) != Some(true) || v.get("username").and_then(Value::as_str) != Some(t.user.as_str()) {
        return Err("The realm's answer didn't look right.".into());
    }
    Ok(v.get("valid_s").and_then(Value::as_u64).unwrap_or(0).min(900))
}

/// Steps 1 and 2.
pub fn sign_in(app_dir: &Path, realm: &str) -> Result<Login, String> {
    let t = request(app_dir, realm)?;
    let valid_s = redeem(&t)?;
    Ok(Login { realm: t.realm, user: t.user, pass: t.pass, valid_s })
}

/// Config.wtf with `SET accountName "<user>"` (the key keeps its spelling when the line is there; added when not).
pub fn config_wtf_with_account(text: &str, user: &str) -> String {
    let mut hit = false;
    let mut lines: Vec<String> = Vec::new();
    for l in text.lines() {
        let mut w = l.split_whitespace();
        match (w.next(), w.next()) {
            (Some(a), Some(b)) if a.eq_ignore_ascii_case("SET") && b.eq_ignore_ascii_case("accountName") => {
                if !hit {
                    lines.push(format!("SET {b} \"{user}\""));
                }
                hit = true;
            }
            _ => lines.push(l.to_string()),
        }
    }
    if !hit {
        lines.push(format!("SET accountName \"{user}\""));
    }
    lines.join("\r\n") + "\r\n"
}

/// Pre-fill the login screen's account name in the client's `WTF/Config.wtf`. Only an `HK...` name is written, and
/// only into a client that has a `WTF` folder. Returns whether it wrote.
pub fn set_account_name(client_root: &Path, user: &str) -> std::io::Result<bool> {
    if !account_ok(user) {
        return Ok(false);
    }
    let cfg = match crate::clients::find_rel(client_root, "WTF/Config.wtf") {
        Some(p) => p,
        None => match crate::clients::find_rel(client_root, "WTF") {
            Some(d) if d.is_dir() => d.join("Config.wtf"),
            _ => return Ok(false),
        },
    };
    let old = std::fs::read_to_string(&cfg).unwrap_or_default();
    crate::settings::write_atomic(&cfg, config_wtf_with_account(&old, user).as_bytes())?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::net::testserver::*;
    use serde_json::json;

    const RID: &str = "abcdefghijk2345a";

    fn answer(realm: &str, redeem: &str) -> Value {
        json!({"ok": true, "realm": realm, "assertion": {"aud": realm, "sub": "x"}, "sig": "ab".repeat(64),
               "login": {"user": "HKABCDEFGHIJKLMN", "pass": "Q7W8E9R2T3Y4U5I6"}, "redeem": redeem})
    }

    #[test]
    fn the_ticket_is_checked() {
        let good = answer(RID, &format!("https://relay.openvanilla.app/api/realms/{RID}/herokey"));
        let t = parse_ticket(&good, RID).unwrap();
        assert_eq!((t.user.as_str(), t.pass.as_str()), ("HKABCDEFGHIJKLMN", "Q7W8E9R2T3Y4U5I6"));
        // another realm, another realm's redeem address, a relay that isn't a plain host, a login that isn't an HK
        // account, a bad signature field: refused
        assert!(parse_ticket(&good, "qrstuvwxyz234567").is_err());
        assert!(parse_ticket(&answer(RID, "https://relay.openvanilla.app/api/realms/qrstuvwxyz234567/herokey"), RID).is_err());
        assert!(parse_ticket(&answer(RID, &format!("https://evil.example:8443/api/realms/{RID}/herokey")), RID).is_err());
        assert!(parse_ticket(&answer(RID, &format!("http://relay.openvanilla.app/api/realms/{RID}/herokey")), RID).is_err());
        let mut v = good.clone();
        v["login"]["user"] = json!("WR000123");
        assert!(parse_ticket(&v, RID).is_err());
        let mut v = good.clone();
        v["assertion"]["aud"] = json!("qrstuvwxyz234567");
        assert!(parse_ticket(&v, RID).is_err());
        let mut v = good.clone();
        v["sig"] = json!("zz");
        assert!(parse_ticket(&v, RID).is_err());
        let mut v = good;
        v["ok"] = json!(false);
        assert!(parse_ticket(&v, RID).is_err());
        assert!(account_ok("HKABCDEFGHIJ2345") && !account_ok("HKabcdefghij2345") && !account_ok("HK1"));
    }

    #[test]
    fn redeem_posts_the_assertion_only() {
        let base = serve_routes(vec![(
            "/api/realms/abcdefghijk2345a/herokey",
            "200 OK",
            br#"{"ok":true,"username":"HKABCDEFGHIJKLMN","valid_s":600}"#.to_vec(),
        )]);
        let t = Ticket {
            realm: RID.into(),
            assertion: json!({"aud": RID}),
            sig: "ab".repeat(64),
            user: "HKABCDEFGHIJKLMN".into(),
            pass: "Q7W8E9R2T3Y4U5I6".into(),
            redeem: format!("{base}/api/realms/{RID}/herokey"),
        };
        assert_eq!(redeem(&t).unwrap(), 600);
        let wrong = Ticket { user: "HKZZZZZZZZZZZZZZ".into(), ..t.clone() };
        assert!(redeem(&wrong).is_err(), "the realm must have set this account's login");
        let refused = serve_routes(vec![]);
        let t2 = Ticket { redeem: format!("{refused}/api/realms/{RID}/herokey"), ..t };
        assert!(redeem(&t2).unwrap_err().contains("refused"));
    }

    #[test]
    fn signed_out_and_bad_ids() {
        let d = tempfile::tempdir().unwrap();
        assert_eq!(request(d.path(), RID).unwrap_err(), "signed_out");
        assert!(request(d.path(), "../x").is_err());
    }

    #[test]
    fn account_name_in_config_wtf() {
        assert_eq!(config_wtf_with_account("", "HKABCDEFGHIJKLMN"), "SET accountName \"HKABCDEFGHIJKLMN\"\r\n");
        assert_eq!(
            config_wtf_with_account("SET gxApi \"d3d9\"\r\nSET accountName \"OLD\"\r\nSET accountname \"DUP\"\r\n", "HKABCDEFGHIJKLMN"),
            "SET gxApi \"d3d9\"\r\nSET accountName \"HKABCDEFGHIJKLMN\"\r\n"
        );
        let d = tempfile::tempdir().unwrap();
        assert!(!set_account_name(d.path(), "HKABCDEFGHIJKLMN").unwrap(), "no WTF folder: nothing written");
        std::fs::create_dir(d.path().join("WTF")).unwrap();
        assert!(!set_account_name(d.path(), "evil\" x").unwrap(), "only an HK account name");
        assert!(set_account_name(d.path(), "HKABCDEFGHIJKLMN").unwrap());
        let text = std::fs::read_to_string(d.path().join("WTF/Config.wtf")).unwrap();
        assert!(text.contains("SET accountName \"HKABCDEFGHIJKLMN\"") && !text.contains("Q7W8"), "never a password");
    }
}
