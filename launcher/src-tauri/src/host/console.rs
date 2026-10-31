//! The host console: the launcher's Host page once a realm is set up on this PC ("Your realm console" on the
//! website, stream/hub.py host_showcase). Everything here runs the host kit's own pieces on this PC, with fixed
//! arguments; nothing from the UI reaches a command line except checked words, names and hex-encoded text.
//!
//! * Health: the realm's containers (`docker ps`, by the kit's container names, every core), the agent's
//!   `state/relay-state.json`, the world server's uptime.
//! * GM controls: the in-game Your realm window's actions (realm/custom/lua_scripts/ov_hostctl.lua: announce, message
//!   of the day, kick, ban / unban, the allow list, restart with five minutes' warning). The kit has no SOAP, so the
//!   console adds one row to `ov_host_queue` in the realm's own characters database (`docker exec` into its database
//!   container, which only this PC's owner can reach) and ov_hostctl.lua runs it as the console within seconds, with
//!   the same checks and limits, and writes its answer back. A restart can only be the five-minute one: the console
//!   sends no delay. AzerothCore realms only (the other cores have no realm scripts).
//! * Health check: the kit's Check my realm (`wuhost.selfcheck`), its lines sorted into the five checks.
//! * Realm tools: public / private, who may sign up, the Hero Key claim, house rules (`wuhost.setup`). Accounts for
//!   friends are the kit's invite link and join page: Leyline never makes an account or touches a password.

use super::docker::{self, Runner};
use super::profiles;
use serde::Serialize;
use serde_json::Value;
use std::fs;
use std::path::Path;
use std::time::Duration;

/// The realm's database container (AzerothCore, the kit's default compose file).
pub const DB_CONTAINER: &str = "wu-host-database";

const SHORT: Duration = Duration::from_secs(20);
const LONG: Duration = Duration::from_secs(180);

// ------------------------------------------------------------------------------------------------ health

/// One row of `docker ps --format '{{json .}}'`.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Row {
    pub name: String,
    pub state: String,
    pub status: String,
}

pub fn parse_ps(out: &str) -> Vec<Row> {
    out.lines()
        .filter_map(|l| serde_json::from_str::<Value>(l.trim()).ok())
        .map(|v| {
            let g = |k: &str| v.get(k).and_then(Value::as_str).unwrap_or("").to_string();
            let status = g("Status");
            let mut state = g("State").to_lowercase();
            if state.is_empty() {
                state = if status.starts_with("Up") { "running".into() } else { "exited".into() };
            }
            let name = g("Names").split(',').next().unwrap_or("").trim().trim_start_matches('/').to_string();
            Row { name, state, status }
        })
        .filter(|r| !r.name.is_empty())
        .collect()
}

/// The kit's container names for each part, every core (docker-compose.host.yml and profiles/*/docker-compose.*.yml;
/// `leyline link` runs only the agent, as wu-link-agent).
pub const ROLES: &[(&str, &[&str])] = &[
    ("database", &["wu-host-database", "wu-host-realm-db"]),
    ("login", &["wu-host-authserver", "wu-host-realm-logon"]),
    ("world", &["wu-host-worldserver", "wu-host-realm-world"]),
    ("agent", &["wu-host-agent", "wu-link-agent"]),
];

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Service {
    pub role: &'static str,
    /// `ok`, `starting`, `bad`, `off`, or `own` (a linked server's own part, not run by the kit).
    pub state: &'static str,
    pub text: String,
}

fn service(role: &'static str, row: Option<&Row>) -> Service {
    let (state, text) = match row {
        None => ("off", "not started"),
        Some(r) if r.state == "restarting" => ("bad", "restarting"),
        Some(r) if r.state != "running" => ("off", "stopped"),
        Some(r) if r.status.contains("(unhealthy)") => ("bad", "not answering"),
        Some(r) if r.status.contains("health: starting") => ("starting", "starting"),
        Some(_) => ("ok", "ready"),
    };
    Service { role, state, text: text.into() }
}

/// "Up 3 days (healthy)" -> "3 days"; None when it is not up.
pub fn uptime(status: &str) -> Option<String> {
    let rest = status.strip_prefix("Up ")?;
    let rest = rest.split(" (").next().unwrap_or(rest).trim();
    if rest.is_empty() {
        return None;
    }
    let mut c = rest.chars();
    let first = c.next()?;
    Some(first.to_lowercase().chain(c).collect::<String>().chars().take(40).collect())
}

/// What the console shows about the realm on this PC.
#[derive(Debug, Clone, Default, Serialize)]
pub struct Console {
    /// The kit has a realm (`state/host.json`).
    pub set_up: bool,
    /// `leyline link`: a server the host already runs, only the agent here.
    pub linked: bool,
    pub name: String,
    pub realm_id: String,
    pub profile: String,
    /// `azerothcore`, `cmangos`, `trinitycore`, or `own` for a linked server.
    pub core: String,
    pub visibility: String,
    pub signup: String,
    pub herokey: bool,
    /// Browser players: Warden off so the browser client can join (setup.py `browser`; AzerothCore rulesets).
    pub browser: bool,
    /// The most players at once (setup.py `listing --max-players`: the server's cap and the list's); 0 = not set.
    pub max_players: u32,
    /// A claim token was given (`leyline claim`); the listing says when it is claimed.
    pub claim_sent: bool,
    pub relay: String,
    pub relay_connected: bool,
    pub relay_error: Option<String>,
    /// Docker answered.
    pub docker: bool,
    pub services: Vec<Service>,
    pub uptime: Option<String>,
    /// The GM controls work now (an AzerothCore realm whose world server runs).
    pub gm: bool,
    pub gm_note: Option<String>,
    pub invite: Option<String>,
}

fn read_json(p: &Path) -> Option<Value> {
    let t = fs::read_to_string(p).ok()?;
    serde_json::from_str(t.trim_start_matches('\u{feff}')).ok().filter(Value::is_object)
}

fn realm_doc(kit: &Path) -> Option<Value> {
    read_json(&kit.join("state").join("host.json"))
}

fn short(v: &Value, k: &str, n: usize) -> String {
    v.get(k).and_then(Value::as_str).unwrap_or("").chars().filter(|c| !c.is_control()).take(n).collect()
}

/// The core a realm runs: a linked server's is its own; the kit's profiles say theirs (profiles.rs).
fn core_of(doc: &Value) -> String {
    if doc.get("linked").and_then(Value::as_bool) == Some(true) {
        return "own".into();
    }
    let p = short(doc, "profile", 32);
    profiles::find(&p).map(|k| k.core).unwrap_or("azerothcore").into()
}

fn find_role<'a>(rows: &'a [Row], role: &str) -> Option<&'a Row> {
    let names: &[&str] = ROLES.iter().find(|(r, _)| *r == role).map(|(_, n)| *n).unwrap_or(&[]);
    rows.iter().find(|r| names.contains(&r.name.as_str()))
}

/// The console from the kit's state files and `docker ps` output (None: Docker did not answer).
pub fn read(kit: &Path, ps: Option<&str>) -> Console {
    let mut c = Console { docker: ps.is_some(), ..Default::default() };
    let rows = ps.map(parse_ps).unwrap_or_default();
    let doc = realm_doc(kit);
    if let Some(d) = &doc {
        c.realm_id = Some(short(d, "realm_id", 32)).filter(|r| crate::realms::realm_id_ok(r)).unwrap_or_default();
        c.set_up = !c.realm_id.is_empty();
        c.linked = d.get("linked").and_then(Value::as_bool) == Some(true);
        c.name = short(d, "name", 64);
        c.profile = short(d, "profile", 32);
        c.core = core_of(d);
        c.visibility = Some(short(d, "visibility", 8)).filter(|v| v == "public" || v == "private").unwrap_or_default();
        c.signup = Some(short(d, "signup", 8)).filter(|v| ["invite", "open", "off"].contains(&v.as_str())).unwrap_or_default();
        c.herokey = d.get("herokey").and_then(Value::as_bool) == Some(true);
        c.browser = d.get("warden").and_then(Value::as_bool) == Some(false);
        c.max_players = d.get("player_limit").and_then(Value::as_u64).filter(|n| (1..=10000).contains(n)).unwrap_or(0) as u32;
        c.claim_sent = !short(d, "claim", 64).is_empty();
        c.relay = Some(short(d, "relay", 128)).filter(|r| crate::realms::relay_ok(r)).unwrap_or_else(|| crate::realms::RELAY.into());
    }
    if let Some(rs) = read_json(&kit.join("state").join("relay-state.json")) {
        c.relay_connected = rs.get("connected").and_then(Value::as_bool) == Some(true);
        c.relay_error = Some(short(&rs, "last_error", 160)).filter(|e| !e.is_empty());
    }
    let find = |role: &str| find_role(&rows, role);
    for &(role, _) in ROLES {
        let s = if c.linked && role != "agent" {
            Service { role, state: "own", text: "your own".into() }
        } else if !c.docker {
            Service { role, state: "off", text: "Docker is off".into() }
        } else {
            service(role, find(role))
        };
        c.services.push(s);
    }
    if let Some(agent) = c.services.iter_mut().find(|s| s.role == "agent") {
        if agent.state == "ok" {
            agent.text = if c.relay_connected { "connected" } else { "connecting" }.into();
            if !c.relay_connected {
                agent.state = "starting";
            }
        }
    }
    c.uptime = find(if c.linked { "agent" } else { "world" }).filter(|r| r.state == "running").and_then(|r| uptime(&r.status));
    let world_up = c.services.iter().any(|s| s.role == "world" && s.state == "ok");
    c.gm_note = if !c.set_up {
        None
    } else if c.linked {
        Some("Your server keeps its own GM tools: use its console.".into())
    } else if c.core != "azerothcore" {
        Some("GM controls come with AzerothCore realms. On this core, use the world server's console.".into())
    } else if !world_up {
        Some("Start your realm to use these.".into())
    } else {
        None
    };
    c.gm = c.set_up && c.gm_note.is_none();
    c.invite = super::invite(kit);
    c
}

/// The console for the kit on this PC.
pub fn console(kit: &Path) -> Console {
    let out = match docker::run_docker(&ps_args(), None, SHORT) {
        Some((0, out)) => Some(out),
        _ => None,
    };
    read(kit, out.as_deref())
}

pub fn ps_args() -> Vec<&'static str> {
    vec!["ps", "-a", "--filter", "name=wu-host-", "--filter", "name=wu-link-agent", "--format", "{{json .}}"]
}

// ------------------------------------------------------------------------------------------------ GM controls

/// The actions ov_hostctl.lua runs (its ACTIONS, plus status).
pub const GM_ACTIONS: &[&str] = &["status", "announce", "motd", "kick", "ban", "unban", "allow", "restart", "cancel"];

/// Text for everyone: no control characters or pipes (colour codes), one line, at most 200 characters. The realm
/// script cleans it again (and takes out the game's brand names).
pub fn clean_text(s: &str) -> Option<String> {
    let t: String = s.chars().map(|c| if c.is_control() || c == '|' { ' ' } else { c }).collect();
    let t = t.split_whitespace().collect::<Vec<_>>().join(" ");
    let t: String = t.chars().take(200).collect();
    Some(t).filter(|t| !t.is_empty())
}

/// A character name: letters only, 2 to 12, as the realm writes it (Grumpy).
pub fn clean_name(s: &str) -> Option<String> {
    let s = s.trim();
    let n = s.chars().count();
    if !(2..=12).contains(&n) || !s.chars().all(|c| c.is_ascii_alphabetic()) {
        return None;
    }
    let lower = s.to_ascii_lowercase();
    Some(lower[..1].to_ascii_uppercase() + &lower[1..])
}

/// The checked data for an action, as ov_hostctl.lua reads it. A restart never carries a delay: it is always the
/// script's five minutes.
pub fn gm_data(action: &str, data: &str) -> Result<String, String> {
    const NAME: &str = "A character name: letters only.";
    match action {
        "status" | "restart" | "cancel" => Ok(String::new()),
        "announce" | "motd" => clean_text(data).ok_or_else(|| "Write the message first.".into()),
        "kick" | "unban" => clean_name(data).ok_or_else(|| NAME.into()),
        "ban" => {
            let mut it = data.split(|c: char| c == '\t' || c == ' ').filter(|x| !x.is_empty());
            let name = it.next().and_then(clean_name).ok_or(NAME)?;
            let hours: u32 = it.next().and_then(|h| h.parse().ok()).filter(|h| (1..=720).contains(h)).ok_or("Ban for 1 to 720 hours.")?;
            Ok(format!("{name}\t{hours}"))
        }
        "allow" => match data.trim() {
            "on" | "off" => Ok(data.trim().into()),
            d => {
                let (verb, who) = d.split_once(|c: char| c == '\t' || c == ' ').ok_or(NAME)?;
                let name = clean_name(who).ok_or(NAME)?;
                if verb != "add" && verb != "del" {
                    return Err(NAME.into());
                }
                Ok(format!("{verb}\t{name}"))
            }
        },
        _ => Err("That is not a GM control.".into()),
    }
}

pub fn hex(s: &str) -> String {
    s.bytes().map(|b| format!("{b:02X}")).collect()
}

pub fn unhex(h: &str) -> Option<String> {
    let h = h.trim();
    if h.len() % 2 != 0 {
        return None;
    }
    let bytes: Option<Vec<u8>> = (0..h.len()).step_by(2).map(|i| u8::from_str_radix(h.get(i..i + 2)?, 16).ok()).collect();
    Some(String::from_utf8_lossy(&bytes?).to_string())
}

/// The queue, as ov_hostctl.lua makes it too.
pub const QUEUE_TABLE: &str = "CREATE TABLE IF NOT EXISTS ov_host_queue (id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, \
action VARCHAR(16) NOT NULL, data VARBINARY(255) NOT NULL, at INT UNSIGNED NOT NULL, done TINYINT NOT NULL DEFAULT 0, \
result VARBINARY(1024) NULL) ENGINE=InnoDB";

/// The statements that queue one action: only a word from GM_ACTIONS and hex digits reach the SQL.
pub fn queue_sql(action: &str, data: &str) -> Result<String, String> {
    if !GM_ACTIONS.contains(&action) {
        return Err("That is not a GM control.".into());
    }
    let d = gm_data(action, data)?;
    Ok(format!(
        "{QUEUE_TABLE}; INSERT INTO ov_host_queue (action, data, at) VALUES ('{action}', UNHEX('{}'), UNIX_TIMESTAMP()); SELECT LAST_INSERT_ID();",
        hex(&d)
    ))
}

/// `docker exec` into the realm's database with one SQL text (passed as an argument, never through a shell).
pub fn mysql_args(sql: &str) -> Vec<String> {
    vec![
        "exec".into(),
        DB_CONTAINER.into(),
        "sh".into(),
        "-c".into(),
        "MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\" exec mysql -uroot -N -B acore_characters -e \"$1\"".into(),
        "leyline".into(),
        sql.into(),
    ]
}

/// How many times the console looks for the realm's answer (the script looks at the queue every 3 seconds).
pub const POLLS: u32 = 15;

/// Queue an action and wait for the realm's answer. `wait` sleeps between looks (a second in the app).
pub fn gm_with(run: Runner, wait: &dyn Fn(), action: &str, data: &str) -> Result<String, String> {
    let sql = queue_sql(action, data)?;
    let call = |sql: &str| {
        let a = mysql_args(sql);
        let r: Vec<&str> = a.iter().map(String::as_str).collect();
        run(&r)
    };
    let id: u64 = match call(&sql) {
        None => return Err("Docker is not installed (or not on PATH).".into()),
        Some((0, out)) => out.lines().rev().find_map(|l| l.trim().parse().ok()).ok_or("The realm's database gave no answer.")?,
        Some((_, _)) => return Err("The realm's database is not answering: start your realm first.".into()),
    };
    for _ in 0..POLLS {
        wait();
        if let Some((0, out)) = call(&format!("SELECT done, HEX(result) FROM ov_host_queue WHERE id = {id}")) {
            let line = out.lines().find(|l| !l.trim().is_empty()).unwrap_or("");
            let mut it = line.split('\t');
            if it.next().map(str::trim) == Some("1") {
                let text = unhex(it.next().unwrap_or("")).unwrap_or_default();
                return match text.split_once(':') {
                    Some(("ok", t)) | Some(("status", t)) => Ok(t.to_string()),
                    Some((_, t)) if !t.is_empty() => Err(t.to_string()),
                    _ => Err("The realm said no.".into()),
                };
            }
        }
    }
    // never done late: the script skips a row that is not waiting any more
    let _ = call(&format!("UPDATE ov_host_queue SET done = 2 WHERE id = {id} AND done = 0"));
    Err("The realm did not answer in time. Is the world server running? An older Host pack can't take these from the launcher: update it.".into())
}

/// A GM control for the realm on this PC.
pub fn gm(kit: &Path, action: &str, data: &str) -> Result<String, String> {
    let doc = realm_doc(kit).ok_or("Set up your realm first.")?;
    if doc.get("linked").and_then(Value::as_bool) == Some(true) {
        return Err("Your server keeps its own GM tools: use its console.".into());
    }
    if core_of(&doc) != "azerothcore" {
        return Err("GM controls come with AzerothCore realms.".into());
    }
    gm_with(&|a| docker::run_docker(a, None, SHORT), &|| std::thread::sleep(Duration::from_secs(1)), action, data)
}

// ------------------------------------------------------------------------------------------------ health check

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CheckLine {
    /// `ok`, `bad` or `note`.
    pub kind: &'static str,
    pub text: String,
    pub fix: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CheckRow {
    /// `pc`, `tunnel`, `login`, `invite`, `list` (the website's five checks, in its order).
    pub id: &'static str,
    /// `ok`, `bad`, `warn`, or `skip` (not tested this time).
    pub state: &'static str,
    pub lines: Vec<CheckLine>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CheckReport {
    pub ok: bool,
    pub rows: Vec<CheckRow>,
    pub summary: String,
}

pub const CHECKS: &[&str] = &["pc", "tunnel", "login", "invite", "list"];

/// Which check a selfcheck line belongs to (hosting/kit/tools/wuhost/selfcheck.py's wording).
fn check_of(text: &str) -> &'static str {
    let t = text.to_lowercase();
    if t.contains("through the relay") && !t.contains("realm list sends") {
        "login"
    } else if t.contains("connected to the relay") || t.contains("realm list sends") || t.contains("realm list does not point") {
        "tunnel"
    } else if t.contains("beacons") || t.contains("not listed anywhere") || t.contains("listed") {
        "list"
    } else if t.contains("invite link") || t.contains("join page") || t.contains("relay's website") {
        "invite"
    } else {
        "pc"
    }
}

/// Sort Check my realm's output into the five checks.
pub fn parse_check(out: &str) -> CheckReport {
    let mut rows: Vec<CheckRow> = CHECKS.iter().map(|&id| CheckRow { id, state: "skip", lines: Vec::new() }).collect();
    let mut last: Option<usize> = None;
    let mut summary = String::new();
    for raw in docker::plain(out).lines() {
        // the kit indents its lines by two spaces; match the word itself so the indent never matters
        let t = raw.trim_start();
        let (kind, rest) = if let Some(r) = t.strip_prefix("OK ") {
            ("ok", r)
        } else if let Some(r) = t.strip_prefix("PROBLEM ") {
            ("bad", r)
        } else if let Some(r) = t.strip_prefix("NOTE ") {
            ("note", r)
        } else {
            let l = raw.trim();
            if let Some(fix) = l.strip_prefix("-> ") {
                if let Some(i) = last {
                    if let Some(x) = rows[i].lines.last_mut() {
                        x.fix = Some(fix.chars().take(240).collect());
                    }
                }
            } else if l.starts_with("All good") || l.contains("problem(s) found") {
                summary = l.chars().take(160).collect();
            }
            continue;
        };
        let text: String = rest.trim().chars().take(240).collect();
        if text.is_empty() {
            continue;
        }
        let i = CHECKS.iter().position(|c| *c == check_of(&text)).unwrap_or(0);
        rows[i].lines.push(CheckLine { kind, text, fix: None });
        last = Some(i);
    }
    for r in &mut rows {
        r.state = if r.lines.iter().any(|l| l.kind == "bad") {
            "bad"
        } else if r.lines.iter().any(|l| l.kind == "note") {
            "warn"
        } else if r.lines.is_empty() {
            "skip"
        } else {
            "ok"
        };
    }
    let ok = rows.iter().all(|r| r.state != "bad") && rows.iter().any(|r| r.state == "ok");
    CheckReport { ok, rows, summary }
}

/// A linked server: the agent's own view (the kit's check needs the realm's own servers).
fn linked_check(kit: &Path) -> CheckReport {
    let c = read(kit, None);
    let mut rows: Vec<CheckRow> = CHECKS.iter().map(|&id| CheckRow { id, state: "skip", lines: Vec::new() }).collect();
    rows[1] = CheckRow {
        id: "tunnel",
        state: if c.relay_connected { "ok" } else { "bad" },
        lines: vec![CheckLine {
            kind: if c.relay_connected { "ok" } else { "bad" },
            text: if c.relay_connected { "The relay agent is connected.".into() } else { format!("The relay agent is not connected ({}).", c.relay_error.as_deref().unwrap_or("no connection yet")) },
            fix: (!c.relay_connected).then(|| "Run Link my server again; check this PC is online.".into()),
        }],
    };
    CheckReport { ok: c.relay_connected, rows, summary: String::new() }
}

/// Run Check my realm (the kit's self-check, in its tools image on the realm's network).
pub fn check(kit: &Path) -> Result<CheckReport, String> {
    super::need_kit(kit)?;
    let doc = realm_doc(kit).ok_or("Set up your realm first.")?;
    if doc.get("linked").and_then(Value::as_bool) == Some(true) {
        return Ok(linked_check(kit));
    }
    let args = docker::compose_args(kit, &["run", "--rm", "--no-deps", "wu-agent", "python", "-m", "wuhost.selfcheck", "--state", "/state"]);
    let a: Vec<&str> = args.iter().map(String::as_str).collect();
    match docker::run_docker(&a, Some(kit), LONG) {
        None => Err("Docker is not installed (or not on PATH).".into()),
        Some((-2, _)) => Err("The check took too long.".into()),
        Some((_, out)) => {
            let r = parse_check(&out);
            if r.rows.iter().all(|x| x.lines.is_empty()) {
                let last = docker::plain(&out).lines().rev().find(|l| !l.trim().is_empty()).unwrap_or("no output").trim().to_string();
                return Err(format!("The check did not run: {last}"));
            }
            Ok(r)
        }
    }
}

// ------------------------------------------------------------------------------------------------ realm tools

/// The kit's setup command for a tool name; only these words go to it.
pub fn tool_cmd(name: &str, arg: Option<&str>) -> Result<(Vec<String>, String), String> {
    let v = |a: &[&str]| a.iter().map(|s| s.to_string()).collect::<Vec<_>>();
    Ok(match name {
        "public" => (v(&["visibility", "public"]), "Public: on the Leyline realm list within a minute.".into()),
        "private" => (v(&["visibility", "private"]), "Private: only people with your invite link can join.".into()),
        "signup-invite" => (v(&["signup", "invite"]), "Accounts: only people with your invite link.".into()),
        "signup-open" => (v(&["signup", "open"]), "Accounts: anyone can make one on your join page.".into()),
        "signup-off" => (v(&["signup", "off"]), "Accounts: nobody new for now.".into()),
        "browser-on" => (v(&["browser", "on"]), "Browser players on: the anti-cheat is off. Restart the realm to apply it.".into()),
        "browser-off" => (v(&["browser", "off"]), "Browser players off: desktop clients only. Restart the realm to apply it.".into()),
        "max" => {
            let t = arg.map(str::trim).unwrap_or("");
            let n: u32 = match t.parse() {
                Ok(n) if t.len() <= 5 && t.chars().all(|c| c.is_ascii_digit()) && n <= 10000 => n,
                _ => return Err("Max players: a number from 0 to 10000 (0 = the ruleset's own).".into()),
            };
            let done = if n == 0 { "Max players: the ruleset's own.".to_string() } else { format!("Max players: {n}. The server's cap applies at the next start.") };
            (vec!["listing".into(), "--max-players".into(), n.to_string()], done)
        }
        "claim" => {
            let t = arg.map(str::trim).unwrap_or("");
            let ok = (16..=64).contains(&t.len()) && t.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-');
            if !ok {
                return Err("That doesn't look like a claim token: copy it from the website.".into());
            }
            (vec!["claim".into(), t.into()], "Sent. The website sees your claim within a minute.".into())
        }
        _ => return Err("That is not a realm tool.".into()),
    })
}

pub fn tool(kit: &Path, name: &str, arg: Option<&str>) -> Result<String, String> {
    super::need_kit(kit)?;
    let (cmd, done) = tool_cmd(name, arg)?;
    if realm_doc(kit).is_none() {
        return Err("Set up your realm first.".into());
    }
    let c: Vec<&str> = cmd.iter().map(String::as_str).collect();
    super::docker_in(kit, docker::tools_args(kit, &c), SHORT)?;
    Ok(done)
}

/// The house rules in `state/rules.txt` (setup.py read_rules: up to 10 lines of 120 characters, `#` lines skipped).
pub fn rules(kit: &Path) -> Vec<String> {
    let t = fs::read_to_string(kit.join("state").join("rules.txt")).unwrap_or_default();
    t.trim_start_matches('\u{feff}')
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
        .map(|l| l.chars().take(120).collect())
        .take(10)
        .collect()
}

pub fn write_rules(kit: &Path, lines: &[String]) -> Result<(), String> {
    let lines: Vec<String> = lines.iter().map(|l| l.trim().to_string()).filter(|l| !l.is_empty()).collect();
    if lines.len() > 10 {
        return Err("Up to 10 rules.".into());
    }
    if lines.iter().any(|l| l.chars().count() > 120) {
        return Err("Each rule: up to 120 characters.".into());
    }
    if lines.iter().any(|l| l.starts_with('#') || l.chars().any(char::is_control)) {
        return Err("A rule can't start with # or hold control characters.".into());
    }
    let mut text = String::from("# House rules: one per line, up to 10, 120 characters each. Lines starting with # are skipped.\n");
    for l in &lines {
        text.push_str(l);
        text.push('\n');
    }
    crate::settings::write_atomic(&kit.join("state").join("rules.txt"), text.as_bytes()).map_err(|e| format!("Could not write state/rules.txt: {e}"))
}

/// Save the rules, then the kit's `rules` re-reads them (the realm list shows them within a minute).
pub fn set_rules(kit: &Path, lines: &[String]) -> Result<String, String> {
    super::need_kit(kit)?;
    write_rules(kit, lines)?;
    if realm_doc(kit).is_none() {
        return Ok("Saved. They show once your realm has started.".into());
    }
    match super::docker_in(kit, docker::tools_args(kit, &["rules"]), SHORT) {
        Ok(_) => Ok("Saved. The realm list shows them within a minute.".into()),
        Err(e) => Ok(format!("Saved. They show from the next start ({e}).")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::clients::testutil::touch;
    use std::cell::RefCell;

    const RID: &str = "abcdefghijk2345a";

    fn kit_with(host: &str) -> tempfile::TempDir {
        let d = tempfile::tempdir().unwrap();
        touch(d.path(), "docker-compose.host.yml", b"services: {}");
        touch(d.path(), "state/host.json", host.as_bytes());
        d
    }

    fn ps(rows: &[(&str, &str, &str)]) -> String {
        rows.iter().map(|(n, s, st)| format!(r#"{{"Names":"{n}","State":"{s}","Status":"{st}","Image":"x"}}"#)).collect::<Vec<_>>().join("\n")
    }

    #[test]
    fn services_from_docker_ps() {
        let k = kit_with(&format!(r#"{{"realm_id":"{RID}","name":"Frost Haven","profile":"vanillaplus","visibility":"public","signup":"invite","relay":"relay.openvanilla.app","claim":"tok"}}"#));
        touch(k.path(), "state/relay-state.json", br#"{"connected":true}"#);
        let out = ps(&[
            ("wu-host-database", "running", "Up 3 days (healthy)"),
            ("wu-host-authserver", "running", "Up 3 days (healthy)"),
            ("wu-host-worldserver", "running", "Up 3 days (healthy)"),
            ("wu-host-agent", "running", "Up 3 days"),
            ("wu-host-db-import", "exited", "Exited (0) 3 days ago"),
        ]);
        let c = read(k.path(), Some(&out));
        assert!(c.set_up && !c.linked && c.docker && c.claim_sent);
        assert_eq!((c.name.as_str(), c.core.as_str(), c.signup.as_str()), ("Frost Haven", "azerothcore", "invite"));
        let st: Vec<(&str, &str, &str)> = c.services.iter().map(|s| (s.role, s.state, s.text.as_str())).collect();
        assert_eq!(st, vec![("database", "ok", "ready"), ("login", "ok", "ready"), ("world", "ok", "ready"), ("agent", "ok", "connected")]);
        assert_eq!(c.uptime.as_deref(), Some("3 days"));
        assert!(c.gm && c.gm_note.is_none());

        // the world server still importing, the agent not connected, the login server crash-looping
        touch(k.path(), "state/relay-state.json", br#"{"connected":false,"last_error":"timed out"}"#);
        let out = ps(&[
            ("wu-host-database", "running", "Up 2 minutes (healthy)"),
            ("wu-host-authserver", "restarting", "Restarting (1) 5 seconds ago"),
            ("wu-host-worldserver", "running", "Up 2 minutes (health: starting)"),
            ("wu-host-agent", "running", "Up 2 minutes"),
        ]);
        let c = read(k.path(), Some(&out));
        let st: Vec<&str> = c.services.iter().map(|s| s.state).collect();
        assert_eq!(st, vec!["ok", "bad", "starting", "starting"]);
        assert_eq!(c.relay_error.as_deref(), Some("timed out"));
        assert!(!c.gm && c.gm_note.as_deref() == Some("Start your realm to use these."));

        // stopped, and Docker not answering
        let c = read(k.path(), Some(""));
        assert!(c.services.iter().all(|s| s.state == "off" && s.text == "not started") && c.uptime.is_none());
        let c = read(k.path(), None);
        assert!(!c.docker && c.services.iter().all(|s| s.text == "Docker is off"));
    }

    #[test]
    fn other_cores_and_linked_servers() {
        let k = kit_with(&format!(r#"{{"realm_id":"{RID}","name":"Old World","profile":"cmangos-1.12.1","visibility":"private"}}"#));
        let out = ps(&[("wu-host-realm-db", "running", "Up 1 hour (healthy)"), ("wu-host-realm-world", "running", "Up About an hour (healthy)")]);
        let c = read(k.path(), Some(&out));
        assert_eq!(c.core, "cmangos");
        assert_eq!(c.services[0].state, "ok");
        assert_eq!(c.services[1].state, "off", "no logon container");
        assert_eq!(c.uptime.as_deref(), Some("about an hour"));
        assert!(!c.gm && c.gm_note.unwrap().contains("AzerothCore"));
        assert!(gm(k.path(), "announce", "hi").unwrap_err().contains("AzerothCore"));

        let l = kit_with(&format!(r#"{{"realm_id":"{RID}","name":"My Server","profile":"linked","linked":true,"visibility":"public"}}"#));
        touch(l.path(), "state/relay-state.json", br#"{"connected":true}"#);
        let c = read(l.path(), Some(&ps(&[("wu-link-agent", "running", "Up 5 hours")])));
        assert!(c.linked && c.core == "own");
        let st: Vec<(&str, &str)> = c.services.iter().map(|s| (s.role, s.state)).collect();
        assert_eq!(st, vec![("database", "own"), ("login", "own"), ("world", "own"), ("agent", "ok")]);
        assert_eq!(c.uptime.as_deref(), Some("5 hours"));
        assert!(!c.gm);
        let r = check(l.path()).unwrap();
        assert!(r.ok && r.rows[1].state == "ok" && r.rows[0].state == "skip");

        // nothing set up
        let none = tempfile::tempdir().unwrap();
        let c = read(none.path(), Some(""));
        assert!(!c.set_up && c.gm_note.is_none() && !c.gm);
        let bad = kit_with(r#"{"realm_id":"../../x"}"#);
        assert!(!read(bad.path(), None).set_up, "a broken realm id is not a realm");
    }

    #[test]
    fn gm_data_is_checked() {
        assert_eq!(gm_data("announce", "  Hello\n|cffff0000all|r  ").unwrap(), "Hello cffff0000all r");
        assert!(gm_data("announce", " \t ").is_err());
        assert_eq!(gm_data("announce", &"x".repeat(500)).unwrap().len(), 200);
        assert_eq!(gm_data("kick", "grumpy").unwrap(), "Grumpy");
        assert!(gm_data("kick", "Rob'); DROP").is_err());
        assert!(gm_data("kick", "A").is_err());
        assert_eq!(gm_data("ban", "grumpy 24").unwrap(), "Grumpy\t24");
        assert_eq!(gm_data("ban", "Grumpy\t720").unwrap(), "Grumpy\t720");
        assert!(gm_data("ban", "Grumpy 0").is_err() && gm_data("ban", "Grumpy 721").is_err() && gm_data("ban", "Grumpy").is_err());
        assert_eq!(gm_data("allow", "on").unwrap(), "on");
        assert_eq!(gm_data("allow", "add friendly").unwrap(), "add\tFriendly");
        assert!(gm_data("allow", "drop Friendly").is_err());
        assert_eq!(gm_data("restart", "1").unwrap(), "", "the console can't pick the delay");
        assert!(gm_data("server", "shutdown").is_err());
        assert_eq!(unhex(&hex("Grumpy\t24 é")).unwrap(), "Grumpy\t24 é");
        assert!(unhex("4").is_none() && unhex("zz").is_none());
    }

    #[test]
    fn the_queue_sql_carries_only_words_and_hex() {
        let s = queue_sql("announce", "Hi'); DROP TABLE account; --").unwrap();
        assert!(s.starts_with(QUEUE_TABLE));
        assert!(s.contains(&format!("VALUES ('announce', UNHEX('{}'), UNIX_TIMESTAMP())", hex("Hi'); DROP TABLE account; --"))));
        assert_eq!(s.matches('\'').count(), 4, "the only quotes are around the word and the hex");
        assert!(queue_sql("restart", "").unwrap().contains("VALUES ('restart', UNHEX(''),"));
        assert!(queue_sql("shutdown", "").is_err() && queue_sql("restart'--", "").is_err());
        let a = mysql_args(&s);
        assert_eq!((a[0].as_str(), a[1].as_str(), a[2].as_str()), ("exec", DB_CONTAINER, "sh"));
        assert!(a[4].contains("\"$1\"") && a[6] == s, "the SQL is an argument, never part of the shell text");
    }

    #[test]
    fn gm_waits_for_the_realms_answer() {
        let seen: RefCell<Vec<String>> = RefCell::new(Vec::new());
        let answer = RefCell::new(0u32);
        let run = |a: &[&str]| -> Option<(i32, String)> {
            let sql = a.last().unwrap().to_string();
            seen.borrow_mut().push(sql.clone());
            if sql.contains("INSERT") {
                return Some((0, "41\n".into()));
            }
            *answer.borrow_mut() += 1;
            if *answer.borrow() < 3 {
                Some((0, "0\tNULL\n".into()))
            } else {
                Some((0, format!("1\t{}\n", hex("ok:Restart in 5 minutes. Everyone online was told."))))
            }
        };
        let r = gm_with(&run, &|| {}, "restart", "").unwrap();
        assert_eq!(r, "Restart in 5 minutes. Everyone online was told.");
        assert!(seen.borrow()[1].ends_with("WHERE id = 41") && seen.borrow().len() == 4);

        let refused = |a: &[&str]| -> Option<(i32, String)> {
            Some((0, if a.last().unwrap().contains("INSERT") { "7".into() } else { format!("1\t{}", hex("err:Grumpy isn't online.")) }))
        };
        assert_eq!(gm_with(&refused, &|| {}, "kick", "Grumpy").unwrap_err(), "Grumpy isn't online.");

        let silent_calls = RefCell::new(Vec::new());
        let silent = |a: &[&str]| -> Option<(i32, String)> {
            silent_calls.borrow_mut().push(a.last().unwrap().to_string());
            Some((0, if a.last().unwrap().contains("INSERT") { "9".into() } else { String::new() }))
        };
        assert!(gm_with(&silent, &|| {}, "announce", "hi").unwrap_err().contains("did not answer"));
        assert!(silent_calls.borrow().last().unwrap().starts_with("UPDATE ov_host_queue SET done = 2 WHERE id = 9 AND done = 0"), "never done late");

        assert!(gm_with(&|_| None, &|| {}, "status", "").unwrap_err().contains("Docker"));
        assert!(gm_with(&|_| Some((1, "Error: No such container".into())), &|| {}, "status", "").unwrap_err().contains("start your realm"));
        assert!(gm_with(&|_| panic!("no call for a refused action"), &|| {}, "kick", "x").is_err());
    }

    #[test]
    fn check_my_realms_lines_in_five_checks() {
        let out = "Checking your Leyline realm...\n\n\
  OK      Realm settings found: \"Frost Haven\" (main, private).\n\
  OK      The database answers (2 players and 40 bots online).\n\
  OK      The login server is running.\n\
  PROBLEM The world server is not up yet.\n\
            -> It can take 5-15 minutes on the first start (it builds the bots).\n\
  OK      Your realm is connected to the relay (relay.openvanilla.app). Your home address stays hidden.\n\
  OK      The realm list sends players back through the relay (port 40003).\n\
  OK      Your invite link works.\n\
  OK      Players can reach your login server through the relay (relay.openvanilla.app:40002).\n\
  PROBLEM The world server is not reachable through the relay.\n\
  OK      Private realm: it is not listed anywhere; only people with your invite link can join.\n\n\
2 problem(s) found. Players can't join until they're fixed.\n";
        let r = parse_check(out);
        let st: Vec<(&str, &str, usize)> = r.rows.iter().map(|x| (x.id, x.state, x.lines.len())).collect();
        assert_eq!(st, vec![("pc", "bad", 4), ("tunnel", "ok", 2), ("login", "bad", 2), ("invite", "ok", 1), ("list", "ok", 1)]);
        assert_eq!(r.rows[0].lines[3].fix.as_deref(), Some("It can take 5-15 minutes on the first start (it builds the bots)."));
        assert!(!r.ok && r.summary.starts_with("2 problem(s)"));
        let good = parse_check("  OK      The login server is running.\n  NOTE    Your realm is not in the Beacons list yet.\n            -> It appears within a minute.\nAll good. Send your friends the invite link:\n");
        assert!(good.ok && good.rows[4].state == "warn" && good.rows[1].state == "skip" && good.summary.starts_with("All good"));
        assert!(!parse_check("docker: Error response from daemon").ok);
    }

    #[test]
    fn tools_and_house_rules() {
        assert_eq!(tool_cmd("public", None).unwrap().0, vec!["visibility", "public"]);
        assert_eq!(tool_cmd("signup-open", None).unwrap().0, vec!["signup", "open"]);
        assert_eq!(tool_cmd("claim", Some(" abcdefghijklmnop-_12 ")).unwrap().0, vec!["claim", "abcdefghijklmnop-_12"]);
        assert!(tool_cmd("claim", Some("short")).is_err() && tool_cmd("claim", Some("abcdefghijklmnop; rm")).is_err());
        assert!(tool_cmd("friend", Some("BOB")).is_err(), "never an account or a password");
        assert!(tool_cmd("visibility", Some("public")).is_err());
        assert_eq!(tool_cmd("browser-off", None).unwrap().0, vec!["browser", "off"]);
        assert_eq!(tool_cmd("max", Some(" 25 ")).unwrap().0, vec!["listing", "--max-players", "25"]);
        assert!(tool_cmd("max", Some("-1")).is_err() && tool_cmd("max", Some("10001")).is_err() && tool_cmd("max", Some("5; rm")).is_err());

        let none = tempfile::tempdir().unwrap();
        assert!(tool(none.path(), "public", None).unwrap_err().contains("docker-compose.host.yml"));
        let k = tempfile::tempdir().unwrap();
        touch(k.path(), "docker-compose.host.yml", b"services: {}");
        assert!(tool(k.path(), "public", None).unwrap_err().contains("Set up your realm"));
        assert!(rules(k.path()).is_empty());
        let want = vec!["Be kind.".to_string(), "  No gold selling ".into(), "".into()];
        assert!(set_rules(k.path(), &want).unwrap().contains("once your realm has started"));
        assert_eq!(rules(k.path()), vec!["Be kind.", "No gold selling"]);
        assert!(write_rules(k.path(), &vec!["x".to_string(); 11]).is_err());
        assert!(write_rules(k.path(), &["y".repeat(121)]).is_err());
        assert!(write_rules(k.path(), &["# not a rule".to_string()]).is_err());
        assert!(write_rules(k.path(), &["a\u{7}b".to_string()]).is_err());
        assert_eq!(rules(k.path()).len(), 2, "a refused change writes nothing");
        assert!(gm(k.path(), "status", "").unwrap_err().contains("Set up"));
    }

    #[test]
    fn uptime_words() {
        assert_eq!(uptime("Up 3 days (healthy)").as_deref(), Some("3 days"));
        assert_eq!(uptime("Up Less than a second").as_deref(), Some("less than a second"));
        assert_eq!(uptime("Exited (0) 2 hours ago"), None);
        assert_eq!(parse_ps("not json\n{\"Names\":\"/wu-host-agent\",\"Status\":\"Up 2 hours\"}")[0],
            Row { name: "wu-host-agent".into(), state: "running".into(), status: "Up 2 hours".into() });
    }
}
