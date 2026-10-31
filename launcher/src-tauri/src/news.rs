//! The News page (`ui/app.js` renderNews): the website's news feed, `https://play.openvanilla.app/wrath/leyline/news.json`
//! (the admin console publishes it: `stream/admin.py` feed, `{"format": 1, "updated_at", "posts": [{id, date, tag, title,
//! items[]}]}`).
//!
//! Read only, no sign-in, one fixed address: the UI names no URL, so the window's CSP needs no `connect-src` for it.
//! Cached like the other listings; with no network and no cache the UI keeps the posts built into it. Every post is
//! cut to plain short text here (the UI shows it with textContent anyway); a post without a title is left out.

use crate::net;
use serde::Serialize;
use serde_json::Value;
use std::path::Path;
use std::time::Duration;

/// The site's news feed.
pub const URL: &str = "https://play.openvanilla.app/wrath/leyline/news.json";
pub const CACHE_FILE: &str = "news-cache.json";
pub const TIMEOUT: Duration = Duration::from_secs(8);
/// At most this many posts, and this many points a post.
const MAX_POSTS: usize = 20;
const MAX_ITEMS: usize = 8;

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Post {
    pub tag: String,
    pub title: String,
    pub date: String,
    pub items: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct NewsList {
    pub posts: Vec<Post>,
    pub from_cache: bool,
}

/// One line of plain text: control characters dropped, spaces folded, at most `max` characters.
fn line(v: Option<&Value>, max: usize) -> String {
    let s = v.and_then(Value::as_str).unwrap_or("");
    let t: String = s.chars().map(|c| if c.is_control() { ' ' } else { c }).collect();
    t.split_whitespace().collect::<Vec<_>>().join(" ").chars().take(max).collect()
}

/// The posts in a feed document, checked and cut to size.
pub fn posts(v: &Value) -> Vec<Post> {
    let Some(list) = v.get("posts").and_then(Value::as_array) else { return Vec::new() };
    list.iter()
        .filter_map(|p| {
            let title = line(p.get("title"), 120);
            if title.is_empty() {
                return None;
            }
            let date = line(p.get("date"), 10);
            let date_ok = date.len() == 10 && date.bytes().enumerate().all(|(i, b)| if i == 4 || i == 7 { b == b'-' } else { b.is_ascii_digit() });
            let items = p
                .get("items")
                .and_then(Value::as_array)
                .map(|a| a.iter().map(|x| line(Some(x), 200)).filter(|x| !x.is_empty()).take(MAX_ITEMS).collect())
                .unwrap_or_default();
            Some(Post { tag: line(p.get("tag"), 60), title, date: if date_ok { date } else { String::new() }, items })
        })
        .take(MAX_POSTS)
        .collect()
}

fn check(v: &Value) -> Result<(), String> {
    v.get("posts").and_then(Value::as_array).map(|_| ()).ok_or_else(|| "no \"posts\" list in the reply".to_string())
}

/// The feed, or the cached copy offline. Empty when there is neither (the UI then keeps its built-in posts).
pub fn fetch(dir: &Path) -> NewsList {
    match net::fetch_json(URL, &dir.join(CACHE_FILE), TIMEOUT, check) {
        Ok(f) => NewsList { posts: posts(&f.value), from_cache: f.from_cache },
        Err(e) => {
            eprintln!("news: {e}");
            NewsList { posts: Vec::new(), from_cache: false }
        }
    }
}

#[cfg(feature = "app")]
pub mod commands {
    use super::*;

    /// The News page's posts (read only; the address is fixed here).
    #[tauri::command]
    pub async fn news_list() -> Result<NewsList, String> {
        tauri::async_runtime::spawn_blocking(|| fetch(&crate::settings::app_dir())).await.map_err(|e| e.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn the_feed_is_the_sites_own() {
        assert_eq!(URL, "https://play.openvanilla.app/wrath/leyline/news.json");
    }

    #[test]
    fn posts_are_plain_short_text() {
        let v = json!({"format": 1, "posts": [
            {"id": "a", "date": "2026-10-30", "tag": "LAUNCHER", "title": "  New\nthings  ", "items": ["one", "", 7, "two\u{0007}x"]},
            {"id": "b", "title": ""},
            {"id": "c", "date": "30/10/2026", "title": "x".repeat(300), "items": "not a list"}
        ]});
        let p = posts(&v);
        assert_eq!(p.len(), 2);
        assert_eq!(p[0], Post { tag: "LAUNCHER".into(), title: "New things".into(), date: "2026-10-30".into(), items: vec!["one".into(), "two x".into()] });
        assert_eq!(p[1].title.chars().count(), 120);
        assert_eq!(p[1].date, "");
        assert!(p[1].items.is_empty());
        assert!(posts(&json!({"nope": 1})).is_empty());
        assert!(check(&json!({"posts": []})).is_ok());
        assert!(check(&json!({"post": []})).is_err());
    }

    #[test]
    fn at_most_twenty_posts() {
        let many: Vec<Value> = (0..30).map(|i| json!({"title": format!("t{i}")})).collect();
        assert_eq!(posts(&json!({"posts": many})).len(), MAX_POSTS);
    }
}
