//! Rankings for the Discover page: the hub's install counts, ratings and scores (`/wrath/leyline/mods.json`,
//! stream/hub_rank.py), the sort tabs (Hot, Rising, Top rated, Most installed, New, Recently updated), the kind
//! filter, the anonymous install count after a catalog install, and the player's own rating.
//!
//! The order is worked out here from the numbers in mods.json, with the same rules as the server
//! (docs/HUB-RANKINGS.md), so it works offline from the cached copy and for every project of the Workshop catalog.
//!
//! The install count: after a catalog install succeeds, Leyline posts `{id, iid, build, via: "launcher"}` once,
//! where `iid` is a fresh random id made for that one install (so a retry is not counted twice). No account, no
//! machine id, nothing else. Settings › "Count my installs" turns it off.

use crate::catalog::Project;
use crate::clients::Build;
use crate::net;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

pub const SITE: &str = "https://play.openvanilla.app";
pub const FEED_PATH: &str = "/wrath/leyline/mods.json?sort=hot&limit=1000";
pub const INSTALL_PATH: &str = "/wrath/api/hub/install";
pub const RATE_PATH: &str = "/wrath/api/hub/rate";
pub const ME_PATH: &str = "/wrath/api/hub/me";
pub const TIMEOUT: Duration = Duration::from_secs(8);

/// The site, or LEYLINE_HUB_SITE for a test server (https, or http on this PC only).
pub fn site() -> String {
    match std::env::var("LEYLINE_HUB_SITE") {
        Ok(b) if b.starts_with("https://") || b.starts_with("http://127.0.0.1:") || b.starts_with("http://localhost:") => {
            b.trim_end_matches('/').to_string()
        }
        _ => SITE.to_string(),
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Sort {
    Hot,
    Rising,
    Top,
    Installs,
    Installs30,
    New,
    Updated,
    /// A to Z (no numbers needed).
    Name,
}

impl Sort {
    pub fn parse(s: &str) -> Sort {
        match s {
            "rising" => Sort::Rising,
            "top" => Sort::Top,
            "installs" => Sort::Installs,
            "installs30" => Sort::Installs30,
            "new" => Sort::New,
            "updated" => Sort::Updated,
            "name" => Sort::Name,
            _ => Sort::Hot,
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Installs {
    pub all: u64,
    pub d30: u64,
    pub d7: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Rating {
    pub avg: Option<f64>,
    pub n: u64,
    /// The Bayesian score Top rated sorts by.
    pub score: Option<f64>,
}

/// What mods.json says about one project.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Metric {
    pub id: String,
    pub kind: String,
    pub installs: Installs,
    pub rating: Rating,
    pub hot: f64,
    pub rising: Option<f64>,
    /// First seen (YYYY-MM-DD), "" when unknown.
    pub new: String,
    /// Last update (YYYY-MM-DD), "" when unknown.
    pub updated: String,
}

/// mods.json's items by id. Malformed items are dropped.
pub fn parse(v: &Value) -> Result<HashMap<String, Metric>, String> {
    let items = v.get("items").and_then(Value::as_array).ok_or("no \"items\" list in the rankings")?;
    Ok(items
        .iter()
        .take(5000)
        .filter_map(|i| serde_json::from_value::<Metric>(i.clone()).ok())
        .filter(|m| crate::catalog::id_ok(&m.id) || m.id.starts_with("theme:"))
        .map(|mut m| {
            m.new = date(&m.new);
            m.updated = date(&m.updated);
            m.kind = if matches!(m.kind.as_str(), "addon" | "mod" | "mode" | "theme") { m.kind } else { String::new() };
            if !m.hot.is_finite() {
                m.hot = 0.0;
            }
            m.rising = m.rising.filter(|r| r.is_finite());
            (m.id.clone(), m)
        })
        .collect())
}

fn date(s: &str) -> String {
    let ok = s.len() >= 10 && s.as_bytes()[..10].iter().enumerate().all(|(i, c)| if i == 4 || i == 7 { *c == b'-' } else { c.is_ascii_digit() });
    if ok {
        s[..10].to_string()
    } else {
        String::new()
    }
}

/// The kind of a catalog project, for the kind filter: what mods.json says, else from the catalog's own fields.
pub fn kind_of(p: &Project, m: Option<&Metric>) -> &'static str {
    if let Some(k) = m.map(|m| m.kind.as_str()) {
        match k {
            "addon" => return "addon",
            "mod" => return "mod",
            "mode" => return "mode",
            "theme" => return "theme",
            _ => {}
        }
    }
    if p.category == "sandbox" {
        "mode"
    } else if p.kind.as_deref() == Some("ui") || p.category == "addons" {
        "addon"
    } else {
        "mod"
    }
}

fn day_num(d: &str) -> i64 {
    // YYYY-MM-DD as a sortable number (the order is all that matters).
    d.replace('-', "").parse::<i64>().unwrap_or(0)
}

/// The project ids in the order of `sort`, filtered by kind ("" = every kind) and by the client build (None = any).
/// Projects mods.json doesn't know yet sort after those it knows, by name.
pub fn rank(projects: &[Project], metrics: &HashMap<String, Metric>, sort: Sort, kind: &str, build: Option<Build>) -> Vec<String> {
    let none = Metric::default();
    let mut rows: Vec<(&Project, &Metric, bool)> = projects
        .iter()
        .filter(|p| build.map(|b| p.fits(b)).unwrap_or(true))
        .filter(|p| kind.is_empty() || kind_of(p, metrics.get(&p.id)) == kind)
        .map(|p| match metrics.get(&p.id) {
            Some(m) => (p, m, true),
            None => (p, &none, false),
        })
        .collect();
    let f = |x: f64| -x;
    rows.sort_by(|a, b| {
        use std::cmp::Ordering as O;
        let (pa, ma, ka) = *a;
        let (pb, mb, kb) = *b;
        let name = || pa.name.to_lowercase().cmp(&pb.name.to_lowercase()).then_with(|| pa.id.cmp(&pb.id));
        let fcmp = |x: f64, y: f64| f(x).partial_cmp(&f(y)).unwrap_or(O::Equal);
        let known = kb.cmp(&ka); // known first
        let by = match sort {
            Sort::Name => O::Equal,
            Sort::Hot => known.then(fcmp(ma.hot, mb.hot)),
            Sort::Rising => ma
                .rising
                .is_none()
                .cmp(&mb.rising.is_none())
                .then(fcmp(ma.rising.unwrap_or(0.0), mb.rising.unwrap_or(0.0)))
                .then(mb.installs.d7.cmp(&ma.installs.d7)),
            Sort::Top => ma
                .rating
                .score
                .is_none()
                .cmp(&mb.rating.score.is_none())
                .then(fcmp(ma.rating.score.unwrap_or(0.0), mb.rating.score.unwrap_or(0.0)))
                .then(mb.rating.n.cmp(&ma.rating.n)),
            Sort::Installs => known.then(mb.installs.all.cmp(&ma.installs.all)).then(fcmp(ma.hot, mb.hot)),
            Sort::Installs30 => known.then(mb.installs.d30.cmp(&ma.installs.d30)).then(fcmp(ma.hot, mb.hot)),
            Sort::New => ma.new.is_empty().cmp(&mb.new.is_empty()).then(day_num(&mb.new).cmp(&day_num(&ma.new))),
            Sort::Updated => {
                let ua = if ma.updated.is_empty() { pa.last_push.get(..10).map(date).unwrap_or_default() } else { ma.updated.clone() };
                let ub = if mb.updated.is_empty() { pb.last_push.get(..10).map(date).unwrap_or_default() } else { mb.updated.clone() };
                ua.is_empty().cmp(&ub.is_empty()).then(day_num(&ub).cmp(&day_num(&ua)))
            }
        };
        by.then_with(name)
    });
    rows.into_iter().map(|(p, _, _)| p.id.clone()).collect()
}

pub fn cache_path(app_dir: &Path) -> PathBuf {
    app_dir.join("cache").join("mods-rank.json")
}

/// The rankings as the UI sees them.
#[derive(Debug, Clone, Serialize)]
pub struct Ranked {
    pub ids: Vec<String>,
    pub metrics: HashMap<String, Metric>,
    pub from_cache: bool,
    pub error: Option<String>,
}

/// mods.json from the site (or the cache when offline). Never an error: no rankings is an empty map.
pub fn fetch(app_dir: &Path, base: &str) -> (HashMap<String, Metric>, bool, Option<String>) {
    let url = format!("{base}{FEED_PATH}");
    match net::fetch_json(&url, &cache_path(app_dir), TIMEOUT, |v| parse(v).map(|_| ())) {
        Ok(f) => (parse(&f.value).unwrap_or_default(), f.from_cache, f.error),
        Err(e) => (HashMap::new(), false, Some(e)),
    }
}

/// The cached rankings, without the network.
pub fn cached(app_dir: &Path) -> HashMap<String, Metric> {
    net::read_cache(&cache_path(app_dir)).and_then(|(v, _)| parse(&v).ok()).unwrap_or_default()
}

// ------------------------------------------------------------------------------------------------ the install count

static SEQ: AtomicU64 = AtomicU64::new(0);

/// A fresh random id for one install: 24 url-safe characters from the clock, the process, a counter and the
/// stack's address, hashed. Not tied to the player or the machine (a new one every time).
pub fn install_id() -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    let t = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
    let local = 0u8;
    h.update(t.to_le_bytes());
    h.update(std::process::id().to_le_bytes());
    h.update(SEQ.fetch_add(1, Ordering::Relaxed).to_le_bytes());
    h.update((&local as *const u8 as usize).to_le_bytes());
    h.update(format!("{:?}", std::thread::current().id()).as_bytes());
    const ABC: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    h.finalize().iter().take(24).map(|b| ABC[(*b & 63) as usize] as char).collect()
}

/// The ping's body. Exactly these four fields.
pub fn ping_body(project: &str, build: Build, iid: &str) -> Value {
    json!({"id": project, "iid": iid, "build": build.catalog_tag(), "via": "launcher"})
}

/// Count one install (best effort; the answer is whether the site counted it).
pub fn ping(base: &str, project: &str, build: Build) -> Result<bool, String> {
    let v = net::post_json(&format!("{base}{INSTALL_PATH}"), &ping_body(project, build, &install_id()), TIMEOUT)?;
    Ok(v.get("counted").and_then(Value::as_bool).unwrap_or(false))
}

// ------------------------------------------------------------------------------------------------ ratings

fn agent() -> ureq::Agent {
    ureq::AgentBuilder::new().timeout(TIMEOUT).user_agent(concat!("Leyline/", env!("CARGO_PKG_VERSION"))).build()
}

fn api_error(e: ureq::Error) -> String {
    match e {
        ureq::Error::Status(401, _) => "signed_out".into(),
        ureq::Error::Status(code, r) => r
            .into_string()
            .ok()
            .and_then(|b| serde_json::from_str::<Value>(&b).ok())
            .and_then(|v| v.get("error").and_then(Value::as_str).map(|s| s.chars().take(200).collect()))
            .unwrap_or_else(|| format!("The server answered {code}.")),
        ureq::Error::Transport(_) => "Can't reach the Leyline site. Check your connection.".into(),
    }
}

/// Stars must be 0 (take it back) to 5.
pub fn stars_ok(stars: u8) -> bool {
    stars <= 5
}

/// Rate a project as the player signed in to Leyline friends (the same sign-in: the token in social.rs).
/// Returns the server's {ok, mine, rating}. "signed_out" when there is no sign-in.
pub fn rate(app_dir: &Path, base: &str, project: &str, stars: u8) -> Result<Value, String> {
    if !stars_ok(stars) || !(crate::catalog::id_ok(project) || project.starts_with("theme:")) {
        return Err("Pick 1 to 5 stars.".into());
    }
    let token = crate::social::load_token(app_dir).ok_or("signed_out")?;
    let r = agent()
        .post(&format!("{base}{RATE_PATH}"))
        .set("Authorization", &format!("Bearer {token}"))
        .set("Content-Type", "application/json")
        .send_string(&json!({"id": project, "stars": stars}).to_string())
        .map_err(api_error)?;
    serde_json::from_str(&r.into_string().map_err(|e| e.to_string())?).map_err(|e| format!("not JSON: {e}"))
}

/// The player's own rating of a project (0 = none, or not signed in).
pub fn mine(app_dir: &Path, base: &str, project: &str) -> u8 {
    let Some(token) = crate::social::load_token(app_dir) else { return 0 };
    let url = format!("{base}{ME_PATH}?id={}", project.replace(':', "%3A"));
    agent()
        .get(&url)
        .set("Authorization", &format!("Bearer {token}"))
        .call()
        .ok()
        .and_then(|r| r.into_string().ok())
        .and_then(|b| serde_json::from_str::<Value>(&b).ok())
        .and_then(|v| v.get("mine").and_then(Value::as_u64))
        .map(|n| n.min(5) as u8)
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::net::testserver::*;

    fn p(id: &str, name: &str, builds: &[&str], category: &str, kind: Option<&str>) -> Project {
        Project {
            id: id.into(),
            source: "packaged".into(),
            name: name.into(),
            category: category.into(),
            builds: builds.iter().map(|s| s.to_string()).collect(),
            kind: kind.map(String::from),
            download: Some("https://play.openvanilla.app/x".into()),
            ..Default::default()
        }
    }

    const FEED: &str = r#"{"format":1,"items":[
      {"id":"mod:alpha","kind":"addon","installs":{"all":500,"d30":40,"d7":5},"rating":{"avg":4.0,"n":30,"score":3.9},
       "hot":1.2,"rising":null,"new":"2026-09-01","updated":"2026-10-01"},
      {"id":"mod:bravo","kind":"addon","installs":{"all":50,"d30":45,"d7":30},"rating":{"avg":5.0,"n":1,"score":3.75},
       "hot":2.5,"rising":1.8,"new":"2026-10-25","updated":"2026-10-28"},
      {"id":"mod:charlie","kind":"mode","installs":{"all":90,"d30":90,"d7":20},"rating":{"avg":null,"n":0,"score":null},
       "hot":1.9,"rising":0.4,"new":"2026-10-20","updated":"bad date"},
      {"id":"link:0123456789ab","kind":"mod","installs":{"all":0},"hot":"NaN"},
      {"id":"evil id","kind":"addon"},
      {"id":"mod:delta","kind":"weird","hot":0.5}
    ]}"#;

    fn setup() -> (Vec<Project>, HashMap<String, Metric>) {
        let ps = vec![
            p("mod:alpha", "Alpha", &["3.3.5a"], "addons", Some("ui")),
            p("mod:bravo", "Bravo", &["3.3.5a", "1.12"], "addons", Some("ui")),
            p("mod:charlie", "Charlie", &["any"], "sandbox", Some("both")),
            p("mod:echo", "Echo", &["1.12"], "tools", Some("realm")),
        ];
        (ps, parse(&serde_json::from_str(FEED).unwrap()).unwrap())
    }

    #[test]
    fn parses_and_drops_junk() {
        let (_, m) = setup();
        assert!(m.contains_key("mod:alpha") && m.contains_key("mod:bravo") && m.contains_key("mod:charlie"));
        assert!(!m.contains_key("evil id"), "bad ids are dropped");
        assert!(!m.contains_key("link:0123456789ab"), "a wrongly typed item is dropped");
        assert_eq!(m["mod:charlie"].updated, "", "bad dates are emptied");
        assert_eq!(m["mod:delta"].kind, "", "unknown kinds are emptied");
        assert!(m["mod:delta"].hot.is_finite());
        assert!(parse(&json!({"mods": []})).is_err());
    }

    #[test]
    fn every_sort() {
        let (ps, m) = setup();
        let r = |s: &str| rank(&ps, &m, Sort::parse(s), "", None);
        assert_eq!(r("hot"), ["mod:bravo", "mod:charlie", "mod:alpha", "mod:echo"], "unknown to mods.json last");
        assert_eq!(r("rising"), ["mod:bravo", "mod:charlie", "mod:alpha", "mod:echo"]);
        assert_eq!(r("top"), ["mod:alpha", "mod:bravo", "mod:charlie", "mod:echo"], "Bayesian: 30 at 4.0 beat one 5");
        assert_eq!(r("installs"), ["mod:alpha", "mod:charlie", "mod:bravo", "mod:echo"]);
        assert_eq!(r("installs30"), ["mod:charlie", "mod:bravo", "mod:alpha", "mod:echo"]);
        assert_eq!(r("new"), ["mod:bravo", "mod:charlie", "mod:alpha", "mod:echo"]);
        assert_eq!(r("updated"), ["mod:bravo", "mod:alpha", "mod:charlie", "mod:echo"]);
        assert_eq!(r("name"), ["mod:alpha", "mod:bravo", "mod:charlie", "mod:echo"]);
        assert_eq!(r("nonsense"), r("hot"));
    }

    #[test]
    fn filters_by_kind_and_client() {
        let (ps, m) = setup();
        assert_eq!(rank(&ps, &m, Sort::Hot, "addon", None), ["mod:bravo", "mod:alpha"]);
        assert_eq!(rank(&ps, &m, Sort::Hot, "mode", None), ["mod:charlie"]);
        assert_eq!(rank(&ps, &m, Sort::Hot, "mod", None), ["mod:echo"], "a realm mod without metrics, by its catalog kind");
        assert_eq!(rank(&ps, &m, Sort::Hot, "", Some(Build::V1121)), ["mod:bravo", "mod:charlie", "mod:echo"]);
        assert_eq!(rank(&ps, &m, Sort::Hot, "", Some(Build::Other)), Vec::<String>::new());
        assert_eq!(kind_of(&ps[3], None), "mod");
        assert_eq!(kind_of(&ps[0], None), "addon");
    }

    #[test]
    fn install_ids_are_fresh_and_well_formed() {
        let a = install_id();
        let b = install_id();
        assert_ne!(a, b);
        assert!(a.len() >= 22 && a.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_'), "{a}");
        let body = ping_body("mod:alpha", Build::V335a, &a);
        let keys: Vec<&String> = body.as_object().unwrap().keys().collect();
        assert_eq!(keys.len(), 4, "the ping carries only id, iid, build and via");
        assert_eq!(body["build"], "3.3.5a");
        assert_eq!(body["via"], "launcher");
    }

    #[test]
    fn pings_and_reads_the_answer() {
        let base = serve_routes(vec![(INSTALL_PATH, "200 OK", br#"{"ok":true,"counted":true}"#.to_vec())]);
        assert_eq!(ping(&base, "mod:alpha", Build::V335a), Ok(true));
        let down = dead_url();
        assert!(ping(down.trim_end_matches("/x.json"), "mod:alpha", Build::V335a).is_err());
    }

    #[test]
    fn fetches_and_falls_back_to_the_cache() {
        let d = tempfile::tempdir().unwrap();
        let base = serve_routes(vec![("/wrath/leyline/mods.json?sort=hot&limit=1000", "200 OK", FEED.as_bytes().to_vec())]);
        let (m, from_cache, err) = fetch(d.path(), &base);
        assert!(!from_cache && err.is_none() && m.len() == 4);
        assert_eq!(cached(d.path()).len(), 4);
        let dead = dead_url();
        let (m, from_cache, err) = fetch(d.path(), dead.trim_end_matches("/x.json"));
        assert!(from_cache && err.is_some() && m.len() == 4);
        let e = tempfile::tempdir().unwrap();
        let (m, _, err) = fetch(e.path(), dead.trim_end_matches("/x.json"));
        assert!(m.is_empty() && err.is_some(), "no rankings yet is empty, not a failure");
    }

    #[test]
    fn rating_needs_a_sign_in_and_sane_stars() {
        let d = tempfile::tempdir().unwrap();
        assert_eq!(rate(d.path(), "http://127.0.0.1:9", "mod:alpha", 4).unwrap_err(), "signed_out");
        assert!(rate(d.path(), "http://127.0.0.1:9", "mod:alpha", 6).is_err());
        assert!(rate(d.path(), "http://127.0.0.1:9", "not an id", 3).is_err());
        assert_eq!(mine(d.path(), "http://127.0.0.1:9", "mod:alpha"), 0);
    }
}
