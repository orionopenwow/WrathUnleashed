//! The Workshop catalog: `/wrath/mods/all.json` from the site (mods/all-json.md), cached for offline use.
//!
//! One list of every project: packaged mods (a zip the site hosts, with its sha256) and community links (a
//! repo only, nothing hosted). Every value is checked again here: text is trimmed, links must be plain https,
//! downloads must come from the catalog's own site, and anything malformed is dropped rather than shown.

use crate::clients::Build;
use crate::net;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::{Path, PathBuf};

pub const URL: &str = "https://play.openvanilla.app/wrath/mods/all.json";
pub const MAX_PROJECTS: usize = 2000;

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Category {
    pub id: String,
    pub name: String,
    pub line: String,
    pub icon: String,
}

/// One Workshop project, as all.json gives it (unknown fields are ignored, missing ones take defaults).
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Project {
    /// `mod:<mod id>` or `link:<12 hex>`.
    pub id: String,
    /// `packaged` or `community`.
    pub source: String,
    pub name: String,
    pub description: String,
    pub category: String,
    /// `1.12`, `2.4.3`, `3.3.5a`, `4.3.4`, `5.4.8`, `any` (other spellings such as `1.12.1` or `12340` are
    /// read and written back in these words).
    pub builds: Vec<String>,
    pub author: String,
    pub author_url: String,
    pub licence: String,
    pub repo: String,
    pub page: String,
    pub credits: String,
    pub stars: Option<u64>,
    pub last_push: String,
    pub version: Option<String>,
    pub kind: Option<String>,
    pub permissions: Option<Vec<String>>,
    pub on_wrath: Option<bool>,
    pub download: Option<String>,
    pub sha256: Option<String>,
    /// The zip's size in bytes, when the catalog says (catalog.json does; all.json may later).
    pub size: Option<u64>,
}

impl Project {
    /// The mod id of a packaged mod (`mod:pings` -> `pings`).
    pub fn mod_id(&self) -> Option<&str> {
        self.id.strip_prefix("mod:")
    }
    /// Made for this client build (`any` fits every known build; a project with no builds listed is taken as
    /// `any`). Nothing fits a build Leyline does not know.
    pub fn fits(&self, build: Build) -> bool {
        build != Build::Other
            && (self.builds.is_empty() || self.builds.iter().any(|b| b == "any" || Build::from_tag(b) == Some(build)))
    }
    /// Leyline can download and install it (a packaged mod with a zip on the site).
    pub fn installable(&self) -> bool {
        self.source == "packaged" && self.download.is_some()
    }
}

/// The catalog as the UI sees it.
#[derive(Debug, Clone, Serialize)]
pub struct Catalog {
    pub categories: Vec<Category>,
    pub projects: Vec<Project>,
    pub from_cache: bool,
    pub saved_at: Option<u64>,
    pub error: Option<String>,
}

fn text(s: &str, n: usize) -> String {
    let one: String = s.chars().filter(|c| !c.is_control() || *c == '\n').collect();
    one.trim().chars().take(n).collect()
}

fn link(s: &str) -> String {
    if net::plain_https(s) {
        s.to_string()
    } else {
        String::new()
    }
}

/// A catalog id: `mod:<mod id>` (wu-mod.py's id rule) or `link:<12 hex>`.
pub fn id_ok(id: &str) -> bool {
    let slug = |s: &str| {
        (3..=32).contains(&s.len())
            && s.starts_with(|c: char| c.is_ascii_lowercase())
            && s.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
            && !s.contains("--")
            && !s.ends_with('-')
    };
    match id.split_once(':') {
        Some(("mod", m)) => slug(m),
        Some(("link", h)) => h.len() == 12 && h.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()),
        _ => false,
    }
}

/// One project made safe to show, or None when it is not a real entry. `origin` is the catalog's own site
/// (`https://play.openvanilla.app`): a download anywhere else is dropped.
pub fn clean(p: Project, origin: &str) -> Option<Project> {
    clean_in(p, origin, crate::clients::all_clients())
}

/// `clean`; a project made only for builds that are not offered now (4.3.4, 5.4.8: `clients::MAX_OFFERED_BUILD`)
/// is hidden unless `all`.
pub fn clean_in(mut p: Project, origin: &str, all: bool) -> Option<Project> {
    if !id_ok(&p.id) {
        return None;
    }
    p.source = if p.source == "packaged" && p.id.starts_with("mod:") { "packaged".into() } else { "community".into() };
    p.name = text(&p.name, 64);
    if p.name.is_empty() {
        p.name = p.id.split(':').nth(1).unwrap_or_default().to_string();
    }
    p.description = text(&p.description, 400);
    p.category = text(&p.category, 32);
    p.builds = p
        .builds
        .into_iter()
        .filter_map(|b| if b == "any" { Some(b) } else { Build::from_tag(&b).map(|x| x.catalog_tag().to_string()) })
        .collect::<Vec<_>>();
    let known = !p.builds.is_empty();
    p.builds = p
        .builds
        .into_iter()
        .filter(|b| b == "any" || Build::from_tag(b).is_some_and(|x| x.offered_in(all)))
        .fold(Vec::new(), |mut v, b| {
            if !v.contains(&b) {
                v.push(b);
            }
            v
        })
        .into_iter()
        .take(8)
        .collect();
    if known && p.builds.is_empty() {
        return None;
    }
    p.author = text(&p.author, 80);
    p.author_url = link(&p.author_url);
    p.licence = text(&p.licence, 80);
    p.repo = link(&p.repo);
    p.page = link(&p.page);
    p.credits = text(&p.credits, 200);
    p.last_push = text(&p.last_push, 25);
    p.version = p.version.map(|v| text(&v, 40)).filter(|v| !v.is_empty());
    p.kind = p.kind.filter(|k| matches!(k.as_str(), "ui" | "realm" | "both"));
    p.permissions = p.permissions.map(|v| v.into_iter().map(|x| text(&x, 16)).take(8).collect());
    p.sha256 = p.sha256.map(|s| s.to_ascii_lowercase()).filter(|s| s.len() == 64 && s.chars().all(|c| c.is_ascii_hexdigit()));
    p.download = p.download.filter(|d| {
        p.source == "packaged"
            && d.len() <= 400
            && !d.chars().any(|c| c.is_whitespace() || c.is_control())
            && net::origin(d).as_deref() == Some(origin)
            && d[origin.len()..].starts_with('/')
    });
    Some(p)
}

/// The categories and projects of an all.json document.
pub fn parse(v: &Value, origin: &str) -> Result<(Vec<Category>, Vec<Project>), String> {
    parse_in(v, origin, crate::clients::all_clients())
}

/// `parse`, with every known build offered when `all`.
pub fn parse_in(v: &Value, origin: &str, all: bool) -> Result<(Vec<Category>, Vec<Project>), String> {
    let items = v.get("projects").and_then(Value::as_array).ok_or("no \"projects\" list in the catalog")?;
    let projects = items
        .iter()
        .take(MAX_PROJECTS)
        .filter_map(|i| serde_json::from_value::<Project>(i.clone()).ok())
        .filter_map(|p| clean_in(p, origin, all))
        .collect();
    let categories = v
        .get("categories")
        .and_then(Value::as_array)
        .map(|a| {
            a.iter()
                .filter_map(|c| serde_json::from_value::<Category>(c.clone()).ok())
                .filter(|c| !c.id.is_empty() && c.id.len() <= 32)
                .map(|c| Category { id: c.id, name: text(&c.name, 48), line: text(&c.line, 200), icon: text(&c.icon, 16) })
                .take(40)
                .collect()
        })
        .unwrap_or_default();
    Ok((categories, projects))
}

pub fn cache_path(app_dir: &Path) -> PathBuf {
    app_dir.join("cache").join("all.json")
}

pub fn fetch(app_dir: &Path) -> Result<Catalog, String> {
    fetch_from(URL, app_dir)
}

pub fn fetch_from(url: &str, app_dir: &Path) -> Result<Catalog, String> {
    let origin = net::origin(url).ok_or("bad catalog address")?;
    let f = net::fetch_json(url, &cache_path(app_dir), net::TIMEOUT, |v| parse(v, &origin).map(|_| ()))?;
    let (categories, projects) = parse(&f.value, &origin)?;
    Ok(Catalog { categories, projects, from_cache: f.from_cache, saved_at: f.saved_at, error: f.error })
}

/// The catalog as last fetched (the cache), without the network: what installs and update checks work from.
pub fn cached(app_dir: &Path, url: &str) -> Option<Vec<Project>> {
    let origin = net::origin(url)?;
    let (v, _) = net::read_cache(&cache_path(app_dir))?;
    parse(&v, &origin).ok().map(|(_, p)| p)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::net::testserver::*;

    const DOC: &str = r#"{"format":1,"generated_at":"2026-10-25T12:00:00Z",
      "categories":[{"id":"addons","name":"Addons and UI","line":"Interfaces.","icon":"interface"},{"id":"maps","name":"Custom maps"}],
      "builds":["3.3.5a","1.12","any"],
      "projects":[
        {"id":"mod:pings","source":"packaged","name":"Pings","description":"Alt-click the map.","category":"addons",
         "builds":["3.3.5a"],"author":"WrathUnleashed","author_url":"","licence":"MIT",
         "repo":"https://github.com/orionopenwow/WrathUnleashed/tree/main/mods/catalog/pings",
         "page":"https://play.openvanilla.app/wrath/mods/pings","credits":"Pings by WrathUnleashed · MIT · github.com",
         "stars":null,"last_push":"","version":"0.1.0","kind":"both","permissions":["chat","timers"],"on_wrath":true,
         "download":"https://play.openvanilla.app/wrath/mods/pings/download","sha256":"AB12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12","new_field":5},
        {"id":"link:3f9a0c12bd47","source":"community","name":"frame-kit","description":"Unit frames.","category":"addons",
         "builds":["3.3.5a","1.12"],"author":"alice","author_url":"https://github.com/alice","licence":"",
         "repo":"https://github.com/alice/frame-kit","page":"https://play.openvanilla.app/wrath/mods/p/3f9a0c12bd47",
         "credits":"frame-kit by alice","stars":42,"version":null,"kind":null,"download":null,"sha256":null},
        {"id":"link:evil","name":"bad id"},
        {"id":"mod:sneaky","source":"packaged","name":"Sneaky","builds":["1.12"],
         "repo":"javascript:alert(1)","download":"https://evil.example.com/x.zip","sha256":"nothex"},
        {"id":"mod:typed","stars":"many"}
      ]}"#;

    #[test]
    fn parses_cleans_and_checks_every_field() {
        let v: Value = serde_json::from_str(DOC).unwrap();
        let (cats, ps) = parse(&v, "https://play.openvanilla.app").unwrap();
        assert_eq!(cats.len(), 2);
        assert_eq!(cats[0].name, "Addons and UI");
        let ids: Vec<&str> = ps.iter().map(|p| p.id.as_str()).collect();
        assert_eq!(ids, vec!["mod:pings", "link:3f9a0c12bd47", "mod:sneaky"], "bad ids and wrong types are dropped");
        let pings = &ps[0];
        assert!(pings.installable() && pings.fits(Build::V335a) && !pings.fits(Build::V1121));
        assert_eq!(pings.mod_id(), Some("pings"));
        assert_eq!(pings.sha256.as_deref().map(|s| s.starts_with("ab12")), Some(true), "lower-cased");
        let link = &ps[1];
        assert!(!link.installable() && link.fits(Build::V1121) && link.fits(Build::V335a));
        assert_eq!(link.stars, Some(42));
        let sneaky = &ps[2];
        assert_eq!(sneaky.repo, "", "only https links");
        assert_eq!(sneaky.download, None, "downloads only from the catalog's own site");
        assert_eq!(sneaky.sha256, None);
        assert!(!sneaky.installable());
    }

    #[test]
    fn filters_by_every_build() {
        let doc = r#"{"projects":[
          {"id":"mod:tbc-bars","source":"packaged","builds":["2.4.3","8606"]},
          {"id":"mod:cata-map","source":"packaged","builds":["4.3.4","5.4.8","9.9.9"]},
          {"id":"mod:vanilla-x","source":"packaged","builds":["1.12.1"]},
          {"id":"mod:any-thing","source":"packaged","builds":["any"]}]}"#;
        // Not offered for now (owner, 2026-10-30): a project made only for 4.3.4/5.4.8 is hidden; the override shows it.
        let capped = parse_in(&serde_json::from_str(doc).unwrap(), "https://play.openvanilla.app", false).unwrap().1;
        assert_eq!(capped.iter().map(|p| p.id.as_str()).collect::<Vec<_>>(), ["mod:tbc-bars", "mod:vanilla-x", "mod:any-thing"]);
        let (_, ps) = parse_in(&serde_json::from_str(doc).unwrap(), "https://play.openvanilla.app", true).unwrap();
        assert_eq!(ps[0].builds, vec!["2.4.3"], "spellings fold into one tag");
        assert_eq!(ps[1].builds, vec!["4.3.4", "5.4.8"], "unknown builds are dropped");
        assert_eq!(ps[2].builds, vec!["1.12"]);
        let fits = |i: usize| Build::KNOWN.into_iter().filter(|b| ps[i].fits(*b)).collect::<Vec<_>>();
        assert_eq!(fits(0), vec![Build::V243]);
        assert_eq!(fits(1), vec![Build::V434, Build::V548]);
        assert_eq!(fits(2), vec![Build::V1121]);
        assert_eq!(fits(3), Build::KNOWN.to_vec());
        assert!(!ps[3].fits(Build::Other), "nothing is offered for an unknown build");
    }

    #[test]
    fn fetches_caches_and_falls_back() {
        let d = tempfile::tempdir().unwrap();
        let base = serve_routes(vec![("/wrath/mods/all.json", "200 OK", DOC.as_bytes().to_vec())]);
        let c = fetch_from(&format!("{base}/wrath/mods/all.json"), d.path()).unwrap();
        assert!(!c.from_cache);
        // The local server's own origin is the catalog site here, so evil.example.com is still refused.
        assert_eq!(c.projects.len(), 3);
        assert!(cache_path(d.path()).exists());
        let off = fetch_from(&format!("{}/wrath/mods/all.json", dead_url().trim_end_matches("/x.json")), d.path()).unwrap();
        assert!(off.from_cache && off.error.is_some());
        assert_eq!(cached(d.path(), &format!("{base}/wrath/mods/all.json")).unwrap().len(), 3);
        // A reply that is not a catalog does not replace the cache.
        let bad = serve_routes(vec![("/wrath/mods/all.json", "200 OK", br#"{"mods":[]}"#.to_vec())]);
        assert!(fetch_from(&format!("{bad}/wrath/mods/all.json"), d.path()).unwrap().from_cache);
    }

    #[test]
    fn the_url_is_https() {
        assert!(URL.starts_with("https://") && URL.ends_with("/wrath/mods/all.json"));
    }
}
