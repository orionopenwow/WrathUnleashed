//! Theme packs: how the launcher looks. Two built-ins, Dark (the default) and Light, and packs the player
//! installs. A choice saved by an older Leyline (Leyline Classic, Dark/Light Rounded, Rounded Auto) is read as
//! Dark or Light (`migrate_id`).
//!
//! A pack is `theme.json`, one `theme.css` and optional images and fonts (png, webp, svg, woff2). Never any
//! JavaScript. Every pack is checked when it is installed and again every time it is loaded:
//!
//! - files: only those types, by name and by their first bytes; svg without scripts, event handlers, entities
//!   or outside links; at most 5 MB and 64 files; zip-slip, symlinks and odd packing are refused;
//! - css: parsed and rebuilt from an allowlist. Plain rules, `@media`, `@supports`, `@font-face` and
//!   `@keyframes` only (no `@import` or any other at-rule); custom properties plus a list of visual
//!   properties (no `display`, `position`, `visibility`, `z-index`, `pointer-events`, and `content` only
//!   empty); `url()` only to a file inside the pack; no `expression`, `javascript:`, backslash escapes, `<`.
//!
//! The UI gets the rebuilt CSS with the pack's files inlined as `data:` addresses, so nothing outside the app
//! is ever loaded (the window's CSP allows images and fonts from `self` and `data:` only).
//!
//! Packs live in `<app data>/themes/<id>/`; `themes/active.json` remembers the choice and
//! `themes/installed.json` where each pack came from. Catalog packs are the Workshop's category `themes`.

use crate::catalog::Project;
use crate::mods::safe_rel;
use crate::net;
use crate::settings::write_atomic;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const MIB: u64 = 1024 * 1024;
/// A whole pack, unpacked (and the download).
pub const MAX_PACK: u64 = 5 * MIB;
pub const MAX_CSS: usize = 512 * 1024;
pub const MAX_FILES: usize = 64;
pub const MAX_PREVIEW: usize = 1024 * 1024;
/// The Workshop category theme packs sit in.
pub const CATEGORY: &str = "themes";
pub const DEFAULT: &str = "dark";

/// id, name, kind, one line.
pub const BUILTINS: &[(&str, &str, &str, &str)] = &[
    ("dark", "Dark", "dark", "Navy and charcoal with a blue accent. The default."),
    ("light", "Light", "light", "Bright and clean with the same blue accent."),
];
/// What a pack builds on: the Dark or the Light look.
pub const KINDS: &[&str] = &["dark", "light"];
/// The built-ins of older Leylines and what a saved choice of one becomes. "Rounded Auto" followed the system's
/// setting, which the core cannot see: it reads as Dark here, and the UI (themes.js) moves it to Light when the
/// system is light. Packs may not take these ids either.
pub const LEGACY: &[(&str, &str)] =
    &[("leyline-classic", "dark"), ("dark-rounded", "dark"), ("light-rounded", "light"), ("rounded-system", "dark")];
/// Older pack kinds, read as today's.
const LEGACY_KINDS: &[(&str, &str)] = &[("classic", "dark"), ("rounded-dark", "dark"), ("rounded-light", "light")];

/// A saved theme id with an older built-in moved to Dark or Light; anything else as it is.
pub fn migrate_id(id: &str) -> &str {
    LEGACY.iter().find(|l| l.0 == id).map_or(id, |l| l.1)
}

fn is_builtin(id: &str) -> bool {
    BUILTINS.iter().any(|b| b.0 == id)
}

// ------------------------------------------------------------------------------------------------ theme.json

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ThemeMeta {
    pub id: String,
    pub name: String,
    pub author: String,
    pub version: String,
    pub licence: String,
    /// A png or webp inside the pack, or empty.
    pub preview: String,
    /// One of `KINDS`.
    pub kind: String,
    pub description: String,
}

fn text(s: &str, n: usize) -> String {
    let one: String = s.chars().filter(|c| !c.is_control()).collect();
    one.trim().chars().take(n).collect()
}

/// A pack id: like a mod id (3-32, lower-case letters, digits and single dashes, starting with a letter), and not
/// the name of a built-in.
pub fn id_ok(id: &str) -> bool {
    (3..=32).contains(&id.len())
        && id.starts_with(|c: char| c.is_ascii_lowercase())
        && id.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
        && !id.contains("--")
        && !id.ends_with('-')
        && !is_builtin(id)
        && !LEGACY.iter().any(|l| l.0 == id)
}

pub fn parse_meta(bytes: &[u8]) -> Result<ThemeMeta, String> {
    if bytes.len() > 16 * 1024 {
        return Err("theme.json is larger than 16 KB".into());
    }
    let v: serde_json::Value = serde_json::from_slice(bytes).map_err(|e| format!("theme.json is not valid JSON: {e}"))?;
    if !v.is_object() {
        return Err("theme.json must be an object".into());
    }
    let m: ThemeMeta = serde_json::from_value(v).map_err(|e| format!("theme.json: {e}"))?;
    if !id_ok(&m.id) {
        return Err(format!("theme.json: \"id\" {:?} must be 3-32 lower-case letters, digits and dashes, and not a built-in's", m.id));
    }
    let kind = m.kind.trim();
    let kind = LEGACY_KINDS.iter().find(|k| k.0 == kind).map_or(kind, |k| k.1).to_string();
    let m = ThemeMeta {
        name: text(&m.name, 48),
        author: text(&m.author, 80),
        version: text(&m.version, 24),
        licence: text(&m.licence, 80),
        preview: m.preview.trim().to_string(),
        kind,
        description: text(&m.description, 300),
        id: m.id,
    };
    for (f, v) in [("name", &m.name), ("author", &m.author), ("version", &m.version), ("licence", &m.licence)] {
        if v.is_empty() {
            return Err(format!("theme.json: \"{f}\" is needed"));
        }
    }
    if !KINDS.contains(&m.kind.as_str()) {
        return Err(format!("theme.json: \"kind\" must be one of {}", KINDS.join(", ")));
    }
    Ok(m)
}

// ------------------------------------------------------------------------------------------------ files

/// The pack files allowed: theme.json, theme.css, images and fonts, and readme / licence notes.
fn file_kind(rel: &str) -> Option<&'static str> {
    let lower = rel.to_ascii_lowercase();
    if rel == "theme.json" {
        return Some("json");
    }
    if rel == "theme.css" {
        return Some("css");
    }
    let name = lower.rsplit('/').next().unwrap_or(&lower);
    let stem = name.strip_suffix(".md").or_else(|| name.strip_suffix(".txt"));
    if !lower.contains('/') && stem.is_some_and(|s| matches!(s, "readme" | "license" | "licence" | "credits" | "ofl")) {
        return Some("note");
    }
    let ext = name.rsplit_once('.').map(|(_, e)| e)?;
    match ext {
        "png" => Some("png"),
        "webp" => Some("webp"),
        "svg" => Some("svg"),
        "woff2" => Some("woff2"),
        _ => None,
    }
}

fn mime(kind: &str) -> &'static str {
    match kind {
        "png" => "image/png",
        "webp" => "image/webp",
        "svg" => "image/svg+xml",
        "woff2" => "font/woff2",
        _ => "application/octet-stream",
    }
}

/// An svg with no way to run or load anything.
pub fn svg_ok(bytes: &[u8]) -> Result<(), String> {
    let s = std::str::from_utf8(bytes).map_err(|_| "is not text")?.to_ascii_lowercase();
    for bad in ["<script", "javascript:", "vbscript:", "<foreignobject", "<!entity", "<iframe", "<embed", "<object", "@import", "<?xml-stylesheet", "data:text"] {
        if s.contains(bad) {
            return Err(format!("contains {bad}"));
        }
    }
    // Event handlers: an attribute on... after whitespace.
    let b = s.as_bytes();
    for i in 1..b.len().saturating_sub(3) {
        if !(b[i - 1].is_ascii_alphanumeric() || matches!(b[i - 1], b'-' | b'_' | b':')) && b[i] == b'o' && b[i + 1] == b'n' && b[i + 2].is_ascii_lowercase() {
            let mut j = i + 2;
            while j < b.len() && (b[j].is_ascii_lowercase() || b[j] == b'-') {
                j += 1;
            }
            while j < b.len() && b[j].is_ascii_whitespace() {
                j += 1;
            }
            if j < b.len() && b[j] == b'=' {
                return Err("has an event handler (on...=)".into());
            }
        }
    }
    // Links only inside the file (href="#a"), and url() only to #ids.
    for key in ["href", "src="] {
        let mut from = 0;
        while let Some(p) = s[from..].find(key) {
            let at = from + p + key.len();
            let rest = s[at..].trim_start_matches(|c: char| c.is_ascii_whitespace() || c == '=').trim_start_matches(['"', '\'']);
            if !rest.starts_with('#') {
                return Err("links outside the file".into());
            }
            from = at;
        }
    }
    let mut from = 0;
    while let Some(p) = s[from..].find("url(") {
        let at = from + p + 4;
        if !s[at..].trim_start_matches(['"', '\'', ' ']).starts_with('#') {
            return Err("has a url() outside the file".into());
        }
        from = at;
    }
    Ok(())
}

fn check_bytes(rel: &str, kind: &str, b: &[u8]) -> Result<(), String> {
    let ok = match kind {
        "png" => b.starts_with(b"\x89PNG\r\n\x1a\n"),
        "webp" => b.len() > 12 && &b[0..4] == b"RIFF" && &b[8..12] == b"WEBP",
        "woff2" => b.starts_with(b"wOF2"),
        "svg" => return svg_ok(b).map_err(|e| format!("{rel}: the svg {e}")),
        "json" | "css" | "note" => std::str::from_utf8(b).is_ok() && !b.contains(&0),
        _ => false,
    };
    if ok {
        Ok(())
    } else {
        Err(format!("{rel} is not the file type its name says"))
    }
}

/// One checked pack, in memory.
#[derive(Debug, Clone)]
pub struct Pack {
    pub meta: ThemeMeta,
    /// The rebuilt, allowlisted CSS (relative `url("...")` to pack files).
    pub css: String,
    pub files: BTreeMap<String, Vec<u8>>,
    pub size: u64,
}

/// Check a set of files as a pack. A single top folder (as zipping a folder gives) is taken off first.
pub fn check_files(mut files: Vec<(String, Vec<u8>)>) -> Result<Pack, String> {
    if !files.iter().any(|(r, _)| r == "theme.json") {
        let tops: HashSet<&str> = files.iter().map(|(r, _)| r.split('/').next().unwrap_or("")).collect();
        if tops.len() == 1 && files.iter().all(|(r, _)| r.contains('/')) {
            let top = format!("{}/", tops.into_iter().next().unwrap_or(""));
            files = files.into_iter().map(|(r, b)| (r[top.len()..].to_string(), b)).collect();
        }
    }
    if files.len() > MAX_FILES {
        return Err(format!("a theme pack has at most {MAX_FILES} files"));
    }
    let mut size = 0u64;
    let mut map = BTreeMap::new();
    let mut seen = HashSet::new();
    for (rel, b) in files {
        let rel = safe_rel(&rel)?.ok_or("a folder entry where a file should be")?;
        if !seen.insert(rel.to_ascii_lowercase()) {
            return Err(format!("two files named {rel}"));
        }
        if rel.split('/').count() > 3 {
            return Err(format!("{rel} is too deep: keep files at most two folders down"));
        }
        let kind = file_kind(&rel).ok_or_else(|| format!("{rel}: a theme pack holds only theme.json, theme.css and png, webp, svg or woff2 files"))?;
        check_bytes(&rel, kind, &b)?;
        size += b.len() as u64;
        if size > MAX_PACK {
            return Err("the pack is larger than 5 MB".into());
        }
        map.insert(rel, b);
    }
    let meta = parse_meta(map.get("theme.json").ok_or("theme.json is missing")?)?;
    let css_bytes = map.get("theme.css").ok_or("theme.css is missing")?;
    if css_bytes.len() > MAX_CSS {
        return Err("theme.css is larger than 512 KB".into());
    }
    let assets: HashSet<String> = map.keys().filter(|k| matches!(file_kind(k), Some("png" | "webp" | "svg" | "woff2"))).cloned().collect();
    if !meta.preview.is_empty() {
        let p = &meta.preview;
        if !matches!(file_kind(p), Some("png" | "webp")) || !map.contains_key(p) {
            return Err(format!("theme.json: \"preview\" {p:?} must be a png or webp in the pack"));
        }
        if map[p].len() > MAX_PREVIEW {
            return Err("the preview image is larger than 1 MB".into());
        }
    }
    let css = sanitize_css(std::str::from_utf8(css_bytes).map_err(|_| "theme.css is not UTF-8")?, &assets).map_err(|e| format!("theme.css: {e}"))?;
    Ok(Pack { meta, css, files: map, size })
}

// ------------------------------------------------------------------------------------------------ css

/// Standard properties a pack may set (custom properties `--x` are always allowed).
const PROPS: &[&str] = &[
    "color", "opacity", "filter", "backdrop-filter", "-webkit-backdrop-filter", "box-shadow", "text-shadow", "accent-color",
    "caret-color", "mix-blend-mode", "isolation", "background", "background-color", "background-image", "background-size",
    "background-position", "background-repeat", "background-attachment", "background-origin", "background-clip",
    "background-blend-mode", "-webkit-background-clip", "-webkit-text-fill-color", "-webkit-text-stroke", "border",
    "border-top", "border-right", "border-bottom", "border-left", "border-color", "border-width", "border-style",
    "border-top-color", "border-right-color", "border-bottom-color", "border-left-color", "border-top-width",
    "border-right-width", "border-bottom-width", "border-left-width", "border-radius", "border-top-left-radius",
    "border-top-right-radius", "border-bottom-left-radius", "border-bottom-right-radius", "border-image",
    "border-image-source", "border-image-slice", "border-image-width", "border-image-repeat", "border-image-outset",
    "outline", "outline-color", "outline-width", "outline-style", "outline-offset", "font", "font-family", "font-size",
    "font-weight", "font-style", "font-variant", "font-stretch", "font-feature-settings", "letter-spacing", "line-height",
    "word-spacing", "text-transform", "text-decoration", "text-decoration-color", "text-underline-offset", "text-align",
    "text-overflow", "white-space", "padding", "padding-top", "padding-right", "padding-bottom", "padding-left", "margin",
    "margin-top", "margin-right", "margin-bottom", "margin-left", "gap", "row-gap", "column-gap", "width", "height",
    "min-width", "min-height", "max-width", "max-height", "aspect-ratio", "object-fit", "object-position",
    "grid-template-columns", "grid-template-rows", "align-items", "justify-content", "transform", "transition",
    "transition-duration", "transition-property", "animation", "animation-name", "animation-duration",
    "animation-timing-function", "animation-iteration-count", "animation-delay", "animation-direction",
    "animation-fill-mode", "cursor", "clip-path", "mask", "mask-image", "-webkit-mask", "-webkit-mask-image",
    "mask-size", "mask-position", "mask-repeat", "fill", "stroke", "stroke-width", "list-style", "scrollbar-color",
    "scrollbar-width", "appearance", "-webkit-appearance", "content", "color-scheme",
];
const FONT_FACE: &[&str] = &["font-family", "src", "font-weight", "font-style", "font-display", "unicode-range", "font-stretch"];
const BANNED: &[&str] = &[
    "expression", "javascript", "vbscript", "behavior", "binding", "image-set", "src(", "element(", "attr(", "@", "<", "\\",
    "data:", "http:", "https:", "//", "file:",
];

struct Css<'a> {
    s: &'a [u8],
    i: usize,
    assets: &'a HashSet<String>,
}

fn err<T>(m: impl Into<String>) -> Result<T, String> {
    Err(m.into())
}

impl Css<'_> {
    fn ws(&mut self) {
        while self.i < self.s.len() && self.s[self.i].is_ascii_whitespace() {
            self.i += 1;
        }
    }
    /// Read up to (not past) the first of `stops` outside strings and brackets.
    fn until(&mut self, stops: &[u8]) -> Result<String, String> {
        let start = self.i;
        let mut depth = 0i32;
        while self.i < self.s.len() {
            let c = self.s[self.i];
            match c {
                b'"' | b'\'' => {
                    self.i += 1;
                    while self.i < self.s.len() && self.s[self.i] != c {
                        if self.s[self.i] == b'\n' {
                            return err("a string runs over the end of a line");
                        }
                        self.i += 1;
                    }
                    if self.i >= self.s.len() {
                        return err("a string is not closed");
                    }
                }
                b'(' | b'[' => depth += 1,
                b')' | b']' => {
                    depth -= 1;
                    if depth < 0 {
                        return err("a bracket is closed that was never opened");
                    }
                }
                _ if depth == 0 && stops.contains(&c) => break,
                _ => {}
            }
            self.i += 1;
        }
        if depth != 0 {
            return err("a bracket is not closed");
        }
        Ok(String::from_utf8_lossy(&self.s[start..self.i]).trim().to_string())
    }

    fn rules(&mut self, nested: bool, depth: u32, out: &mut String) -> Result<(), String> {
        if depth > 3 {
            return err("rules are nested too deep");
        }
        loop {
            self.ws();
            if self.i >= self.s.len() {
                return if nested { err("a { is not closed") } else { Ok(()) };
            }
            if self.s[self.i] == b'}' {
                if nested {
                    self.i += 1;
                    return Ok(());
                }
                return err("a } with no {");
            }
            let prelude = self.until(b"{;}")?;
            if self.i >= self.s.len() || self.s[self.i] != b'{' {
                return err(format!("{:?} is not a rule (only rules with {{ }} are allowed; no @import)", short(&prelude)));
            }
            self.i += 1;
            if let Some(at) = prelude.strip_prefix('@') {
                let name: String = at.chars().take_while(|c| c.is_ascii_alphanumeric() || *c == '-').collect::<String>().to_ascii_lowercase();
                let rest = at[name.len()..].trim();
                match name.as_str() {
                    "media" | "supports" => {
                        if rest.is_empty()
                            || rest.to_ascii_lowercase().contains("url")
                            || !rest.chars().all(|c| c.is_ascii_alphanumeric() || " ():-,.%/".contains(c))
                        {
                            return err(format!("@{name} {:?}: only plain conditions", short(rest)));
                        }
                        out.push_str(&format!("@{name} {rest}{{"));
                        self.rules(true, depth + 1, out)?;
                        out.push('}');
                    }
                    "font-face" if rest.is_empty() => {
                        out.push_str("@font-face{");
                        self.decls(FONT_FACE, out)?;
                        out.push('}');
                    }
                    "keyframes" | "-webkit-keyframes" => {
                        if !ident(rest) {
                            return err("@keyframes needs a plain name");
                        }
                        out.push_str(&format!("@keyframes {rest}{{"));
                        loop {
                            self.ws();
                            if self.i < self.s.len() && self.s[self.i] == b'}' {
                                self.i += 1;
                                break;
                            }
                            let sel = self.until(b"{;}")?;
                            if self.i >= self.s.len() || self.s[self.i] != b'{' {
                                return err("@keyframes: a step is not closed");
                            }
                            self.i += 1;
                            if sel.is_empty() || !sel.split(',').all(|p| {
                                let p = p.trim();
                                p == "from" || p == "to" || (p.ends_with('%') && p[..p.len() - 1].parse::<f32>().is_ok())
                            }) {
                                return err(format!("@keyframes step {:?}", short(&sel)));
                            }
                            out.push_str(&sel);
                            out.push('{');
                            self.decls(PROPS, out)?;
                            out.push('}');
                        }
                        out.push('}');
                    }
                    _ => return err(format!("@{name} is not allowed (only @media, @supports, @font-face, @keyframes)")),
                }
            } else {
                if prelude.is_empty() || prelude.len() > 2000 {
                    return err("a rule with no selector");
                }
                let low = prelude.to_ascii_lowercase();
                if BANNED.iter().any(|b| low.contains(b)) || low.contains("url(") {
                    return err(format!("selector {:?}", short(&prelude)));
                }
                out.push_str(&prelude);
                out.push('{');
                self.decls(PROPS, out)?;
                out.push('}');
            }
        }
    }

    /// Declarations up to and past the closing }.
    fn decls(&mut self, allowed: &[&str], out: &mut String) -> Result<(), String> {
        loop {
            self.ws();
            if self.i >= self.s.len() {
                return err("a { is not closed");
            }
            match self.s[self.i] {
                b'}' => {
                    self.i += 1;
                    return Ok(());
                }
                b';' => {
                    self.i += 1;
                    continue;
                }
                b'{' => return err("a { inside a rule (nesting is not allowed)"),
                _ => {}
            }
            let d = self.until(b";{}")?;
            if self.i < self.s.len() && self.s[self.i] == b'{' {
                return err("a { inside a rule (nesting is not allowed)");
            }
            let (name, value) = d.split_once(':').ok_or_else(|| format!("{:?} is not name: value", short(&d)))?;
            let name = name.trim().to_ascii_lowercase();
            let value = value.trim();
            let custom = name.len() > 2 && name.starts_with("--") && name[2..].chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_');
            if !custom && !allowed.contains(&name.as_str()) {
                return err(format!("the property {name:?} is not allowed in theme packs"));
            }
            let v = self.value(&name, value)?;
            out.push_str(&format!("{name}:{v};"));
        }
    }

    fn value(&self, name: &str, v: &str) -> Result<String, String> {
        if v.is_empty() && !name.starts_with("--") {
            return err(format!("{name} has no value"));
        }
        if v.len() > 4000 {
            return err(format!("{name}: the value is too long"));
        }
        if name == "content" && !matches!(v, "\"\"" | "''" | "none" | "normal") {
            return err("content may only be empty (\"\"), none or normal: themes cannot add words");
        }
        // Take url(...) out first, check each, put back a clean one.
        let mut out = String::new();
        let mut rest = v;
        loop {
            let low = rest.to_ascii_lowercase();
            let Some(p) = low.find("url(") else {
                out.push_str(rest);
                break;
            };
            out.push_str(&rest[..p]);
            let after = &rest[p + 4..];
            let close = after.find(')').ok_or("url( is not closed")?;
            let arg = after[..close].trim();
            let arg = arg.strip_prefix('"').and_then(|a| a.strip_suffix('"')).or_else(|| arg.strip_prefix('\'').and_then(|a| a.strip_suffix('\''))).unwrap_or(arg);
            let arg = arg.strip_prefix("./").unwrap_or(arg);
            if !self.assets.contains(arg) {
                return err(format!("url({arg:?}): url() may only name an image or font inside the pack"));
            }
            if name == "src" && !arg.ends_with(".woff2") {
                return err("@font-face src must be a .woff2 in the pack");
            }
            out.push_str(&format!("url(\"{arg}\")"));
            rest = &after[close + 1..];
        }
        let low = out.to_ascii_lowercase();
        // The urls are clean now; look at everything else (their names are pack paths, already checked).
        let mut scan = low.clone();
        for a in self.assets {
            scan = scan.replace(&format!("url(\"{}\")", a.to_ascii_lowercase()), "url()");
        }
        if let Some(b) = BANNED.iter().find(|b| scan.contains(**b)) {
            return err(format!("{name}: {b:?} is not allowed in a value"));
        }
        Ok(out)
    }
}

fn ident(s: &str) -> bool {
    !s.is_empty() && s.len() <= 64 && s.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

fn short(s: &str) -> String {
    s.chars().take(60).collect()
}

/// Check theme.css against the allowlist and rebuild it. `assets` are the pack's image and font paths.
pub fn sanitize_css(src: &str, assets: &HashSet<String>) -> Result<String, String> {
    if src.len() > MAX_CSS {
        return err("larger than 512 KB");
    }
    if src.contains('\\') {
        return err("backslash escapes are not allowed");
    }
    if src.contains('<') {
        return err("< is not allowed (no HTML)");
    }
    if src.chars().any(|c| c.is_control() && !matches!(c, '\n' | '\r' | '\t')) {
        return err("control characters are not allowed");
    }
    // Take out comments.
    let mut clean = String::with_capacity(src.len());
    let mut rest = src;
    while let Some(p) = rest.find("/*") {
        clean.push_str(&rest[..p]);
        let e = rest[p + 2..].find("*/").ok_or("a /* comment is not closed")?;
        clean.push(' ');
        rest = &rest[p + 2 + e + 2..];
    }
    clean.push_str(rest);
    if clean.contains("<!--") || clean.contains("-->") {
        return err("HTML comments are not allowed");
    }
    let mut out = String::new();
    Css { s: clean.as_bytes(), i: 0, assets }.rules(false, 0, &mut out)?;
    Ok(out)
}

// ------------------------------------------------------------------------------------------------ reading packs

fn now() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

/// Every file in a zip, with the same unpacking checks as mods (zip-slip, symlinks, passwords, methods) and
/// the theme caps.
pub fn read_zip(zip: &Path) -> Result<Vec<(String, Vec<u8>)>, String> {
    let size = fs::metadata(zip).map_err(|e| format!("could not read the zip: {e}"))?.len();
    if size > MAX_PACK {
        return Err("the zip is larger than 5 MB".into());
    }
    let f = fs::File::open(zip).map_err(|e| format!("could not read the zip: {e}"))?;
    let mut ar = zip::ZipArchive::new(io::BufReader::new(f)).map_err(|_| "this is not a zip file (or it is damaged)".to_string())?;
    if ar.len() > MAX_FILES * 4 {
        return Err(format!("a theme pack has at most {MAX_FILES} files"));
    }
    let mut out = Vec::new();
    let mut total = 0u64;
    for i in 0..ar.len() {
        let mut file = ar.by_index(i).map_err(|e| format!("the zip is damaged, password protected or packed oddly ({e})"))?;
        let raw = String::from_utf8_lossy(file.name_raw()).to_string();
        let Some(rel) = safe_rel(&raw)? else { continue };
        if file.is_dir() || rel.split('/').any(|p| p == "__MACOSX" || p == ".DS_Store" || p == "Thumbs.db") {
            continue;
        }
        if file.encrypted() {
            return Err("the zip is password protected".into());
        }
        if file.unix_mode().is_some_and(|m| m & 0o170000 == 0o120000) {
            return Err(format!("symbolic links are not allowed: {rel}"));
        }
        if !matches!(file.compression(), zip::CompressionMethod::Stored | zip::CompressionMethod::Deflated) {
            return Err(format!("{rel} uses a packing method Leyline cannot read"));
        }
        if file.size() > MAX_PACK {
            return Err("the pack is larger than 5 MB".into());
        }
        let mut b = Vec::new();
        (&mut file).take(MAX_PACK + 1 - total).read_to_end(&mut b).map_err(|_| format!("the zip is damaged: {rel} does not unpack"))?;
        total += b.len() as u64;
        if total > MAX_PACK {
            return Err("the pack unpacks to more than 5 MB".into());
        }
        out.push((rel, b));
    }
    Ok(out)
}

/// Every file in a folder (no symlinks), with the theme caps.
pub fn read_folder(dir: &Path) -> Result<Vec<(String, Vec<u8>)>, String> {
    let mut out = Vec::new();
    let mut total = 0u64;
    let mut stack = vec![(dir.to_path_buf(), String::new())];
    while let Some((d, rel)) = stack.pop() {
        let mut items: Vec<_> = fs::read_dir(&d).map_err(|e| format!("could not read the folder: {e}"))?.flatten().collect();
        items.sort_by_key(|e| e.file_name());
        for e in items {
            let n = e.file_name().to_string_lossy().to_string();
            if n == ".DS_Store" || n == "Thumbs.db" || n == "__MACOSX" {
                continue;
            }
            let r = if rel.is_empty() { n } else { format!("{rel}/{n}") };
            let md = fs::symlink_metadata(e.path()).map_err(|e| e.to_string())?;
            if md.file_type().is_symlink() {
                return Err(format!("symbolic links are not allowed: {r}"));
            }
            if md.is_dir() {
                if r.split('/').count() > 3 {
                    return Err(format!("{r} is too deep"));
                }
                stack.push((e.path(), r));
                continue;
            }
            total += md.len();
            if total > MAX_PACK {
                return Err("the pack is larger than 5 MB".into());
            }
            if out.len() >= MAX_FILES {
                return Err(format!("a theme pack has at most {MAX_FILES} files"));
            }
            out.push((r, fs::read(e.path()).map_err(|e| e.to_string())?));
        }
    }
    Ok(out)
}

// ------------------------------------------------------------------------------------------------ installed

pub fn themes_dir(app: &Path) -> PathBuf {
    app.join("themes")
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct Origin {
    /// `catalog` or `file`.
    pub source: String,
    /// The catalog project id (`mod:<id>`) for catalog packs.
    pub project: String,
    pub sha256: String,
    pub installed_at: u64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
struct Registry {
    packs: BTreeMap<String, Origin>,
}

fn registry(app: &Path) -> Registry {
    fs::read(themes_dir(app).join("installed.json")).ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_default()
}

fn save_registry(app: &Path, r: &Registry) -> Result<(), String> {
    let b = serde_json::to_vec_pretty(r).map_err(|e| e.to_string())?;
    write_atomic(&themes_dir(app).join("installed.json"), &b).map_err(|e| format!("could not save the theme list: {e}"))
}

/// A theme as the UI lists it.
#[derive(Debug, Clone, Serialize)]
pub struct ThemeInfo {
    pub id: String,
    pub name: String,
    pub author: String,
    pub version: String,
    pub licence: String,
    pub kind: String,
    pub description: String,
    pub builtin: bool,
    pub source: String,
    pub project: String,
    /// The preview as a `data:` address, when the pack has one.
    pub preview: Option<String>,
    pub size: u64,
    /// Set when an installed pack no longer passes the checks (it is then not offered).
    pub problem: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Themes {
    pub active: String,
    pub themes: Vec<ThemeInfo>,
}

fn builtin_info((id, name, kind, line): &(&str, &str, &str, &str)) -> ThemeInfo {
    ThemeInfo {
        id: id.to_string(),
        name: name.to_string(),
        author: "Leyline".into(),
        version: env!("CARGO_PKG_VERSION").into(),
        licence: "MIT".into(),
        kind: kind.to_string(),
        description: line.to_string(),
        builtin: true,
        source: "builtin".into(),
        project: String::new(),
        preview: None,
        size: 0,
        problem: None,
    }
}

fn data_url(kind: &str, b: &[u8]) -> String {
    format!("data:{};base64,{}", mime(kind), base64(b))
}

fn info(pack: &Pack, o: &Origin) -> ThemeInfo {
    let m = &pack.meta;
    ThemeInfo {
        id: m.id.clone(),
        name: m.name.clone(),
        author: m.author.clone(),
        version: m.version.clone(),
        licence: m.licence.clone(),
        kind: m.kind.clone(),
        description: m.description.clone(),
        builtin: false,
        source: if o.source.is_empty() { "file".into() } else { o.source.clone() },
        project: o.project.clone(),
        preview: (!m.preview.is_empty()).then(|| data_url(file_kind(&m.preview).unwrap_or(""), &pack.files[&m.preview])),
        size: pack.size,
        problem: None,
    }
}

/// An installed pack, read and checked again.
pub fn load(app: &Path, id: &str) -> Result<Pack, String> {
    if !id_ok(id) {
        return Err("No such theme.".into());
    }
    let dir = themes_dir(app).join(id);
    if !fs::symlink_metadata(&dir).map(|m| m.is_dir()).unwrap_or(false) {
        return Err("That theme is not installed.".into());
    }
    let pack = check_files(read_folder(&dir)?)?;
    if pack.meta.id != id {
        return Err("The pack's id does not match its folder.".into());
    }
    Ok(pack)
}

pub fn list(app: &Path) -> Themes {
    let mut themes: Vec<ThemeInfo> = BUILTINS.iter().map(builtin_info).collect();
    let reg = registry(app);
    let mut ids: Vec<String> = fs::read_dir(themes_dir(app))
        .map(|rd| rd.flatten().filter(|e| e.path().is_dir()).map(|e| e.file_name().to_string_lossy().to_string()).filter(|n| id_ok(n)).collect())
        .unwrap_or_default();
    ids.sort();
    for id in ids {
        let o = reg.packs.get(&id).cloned().unwrap_or_default();
        match load(app, &id) {
            Ok(p) => themes.push(info(&p, &o)),
            Err(e) => {
                let mut t = builtin_info(&("", "", "", ""));
                t.id = id.clone();
                t.name = id;
                t.builtin = false;
                t.author = String::new();
                t.version = String::new();
                t.licence = String::new();
                t.description = String::new();
                t.source = o.source;
                t.project = o.project;
                t.problem = Some(e);
                themes.push(t);
            }
        }
    }
    Themes { active: active(app), themes }
}

#[derive(Serialize, Deserialize, Default)]
#[serde(default)]
struct Active {
    theme: String,
}

/// The chosen theme (a built-in or an installed pack that still loads), or the default. An older built-in reads
/// as Dark or Light.
pub fn active(app: &Path) -> String {
    let id = fs::read(themes_dir(app).join("active.json")).ok().and_then(|b| serde_json::from_slice::<Active>(&b).ok()).map(|a| a.theme).unwrap_or_default();
    let id = migrate_id(&id).to_string();
    if is_builtin(&id) || (id_ok(&id) && themes_dir(app).join(&id).join("theme.json").is_file()) {
        id
    } else {
        DEFAULT.into()
    }
}

pub fn set_active(app: &Path, id: &str) -> Result<(), String> {
    let id = migrate_id(id);
    if !is_builtin(id) {
        load(app, id)?;
    }
    let b = serde_json::to_vec(&Active { theme: id.into() }).map_err(|e| e.to_string())?;
    write_atomic(&themes_dir(app).join("active.json"), &b).map_err(|e| format!("could not save the theme choice: {e}"))
}

/// What the UI injects for a pack: its kind (which base look) and its CSS with the pack's files inlined.
#[derive(Debug, Clone, Serialize)]
pub struct ThemeCss {
    pub id: String,
    pub kind: String,
    pub css: String,
}

pub fn css(app: &Path, id: &str) -> Result<ThemeCss, String> {
    let p = load(app, id)?;
    let mut css = p.css.clone();
    for (rel, b) in &p.files {
        if let Some(k @ ("png" | "webp" | "svg" | "woff2")) = file_kind(rel) {
            let needle = format!("url(\"{rel}\")");
            if css.contains(&needle) {
                css = css.replace(&needle, &format!("url(\"{}\")", data_url(k, b)));
            }
        }
    }
    Ok(ThemeCss { id: p.meta.id, kind: p.meta.kind, css })
}

/// Write a checked pack to `themes/<id>/` (replacing an older copy) and record where it came from.
pub fn install_pack(app: &Path, pack: &Pack, origin: Origin) -> Result<ThemeInfo, String> {
    let root = themes_dir(app);
    fs::create_dir_all(&root).map_err(|e| format!("could not make the themes folder: {e}"))?;
    let nanos = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
    let stage = root.join(format!(".staging-{}-{nanos}", std::process::id()));
    let res = (|| {
        for (rel, b) in &pack.files {
            let out = stage.join(rel);
            fs::create_dir_all(out.parent().unwrap_or(&stage)).map_err(|e| e.to_string())?;
            fs::write(&out, b).map_err(|e| e.to_string())?;
        }
        let dest = root.join(&pack.meta.id);
        if fs::symlink_metadata(&dest).is_ok() {
            fs::remove_dir_all(&dest).map_err(|e| format!("could not replace the old copy: {e}"))?;
        }
        fs::rename(&stage, &dest).map_err(|e| e.to_string())
    })();
    if res.is_err() {
        let _ = fs::remove_dir_all(&stage);
    }
    res?;
    let mut reg = registry(app);
    reg.packs.insert(pack.meta.id.clone(), Origin { installed_at: now(), ..origin.clone() });
    save_registry(app, &reg)?;
    Ok(info(pack, &origin))
}

/// Install a .zip or a folder the player picked.
pub fn install_local(app: &Path, path: &Path) -> Result<ThemeInfo, String> {
    let md = fs::symlink_metadata(path).map_err(|_| "That file or folder is not there.")?;
    let (files, sha) = if md.is_dir() {
        (read_folder(path)?, String::new())
    } else if path.extension().is_some_and(|e| e.eq_ignore_ascii_case("zip")) {
        (read_zip(path)?, net::sha256_file(path).map_err(|e| e.to_string())?)
    } else {
        return Err("Choose a theme pack: a .zip or a folder with theme.json in it.".into());
    };
    let pack = check_files(files)?;
    install_pack(app, &pack, Origin { source: "file".into(), sha256: sha, ..Default::default() })
}

/// Install a catalog theme: only from the catalog's own site, at most 5 MB, and only when it matches the
/// catalog's sha256. The pack's id must be the project's.
pub fn install_project(app: &Path, p: &Project, catalog_origin: &str) -> Result<ThemeInfo, String> {
    if p.category != CATEGORY {
        return Err("That is not a theme pack.".into());
    }
    if !p.installable() {
        return Err("This theme has no download in the catalog: get it from its page.".into());
    }
    let want = p.sha256.as_deref().ok_or("The catalog gives no checksum for this theme, so Leyline will not install it.")?;
    let url = p.download.as_deref().unwrap_or_default();
    if net::origin(url).as_deref() != Some(catalog_origin) {
        return Err("That download is not on the Workshop's own site.".into());
    }
    if p.size.is_some_and(|n| n > MAX_PACK) {
        return Err("This theme is larger than 5 MB.".into());
    }
    let root = themes_dir(app);
    fs::create_dir_all(&root).map_err(|e| e.to_string())?;
    let tmp = root.join(format!(".download-{}-{}.zip", std::process::id(), now()));
    let res = (|| {
        let (_, sha) = net::download(url, &tmp, MAX_PACK, net::TIMEOUT, Duration::from_secs(30)).map_err(|e| format!("Download failed: {e}"))?;
        if sha != want {
            return Err("The download does not match the catalog's checksum, so it was not installed.".to_string());
        }
        let pack = check_files(read_zip(&tmp)?)?;
        if Some(pack.meta.id.as_str()) != p.mod_id() {
            return Err(format!("The pack's id ({}) is not the catalog's ({}).", pack.meta.id, p.mod_id().unwrap_or("?")));
        }
        install_pack(app, &pack, Origin { source: "catalog".into(), project: p.id.clone(), sha256: sha, installed_at: 0 })
    })();
    let _ = fs::remove_file(&tmp);
    res
}

pub fn remove(app: &Path, id: &str) -> Result<(), String> {
    if is_builtin(id) || LEGACY.iter().any(|l| l.0 == id) {
        return Err("Built-in themes cannot be removed.".into());
    }
    if !id_ok(id) {
        return Err("No such theme.".into());
    }
    let dir = themes_dir(app).join(id);
    if !fs::symlink_metadata(&dir).map(|m| m.is_dir()).unwrap_or(false) {
        return Err("That theme is not installed.".into());
    }
    fs::remove_dir_all(&dir).map_err(|e| format!("could not remove it: {e}"))?;
    let mut reg = registry(app);
    reg.packs.remove(id);
    save_registry(app, &reg)?;
    if fs::read(themes_dir(app).join("active.json")).ok().and_then(|b| serde_json::from_slice::<Active>(&b).ok()).is_some_and(|a| a.theme == id) {
        set_active(app, DEFAULT)?;
    }
    Ok(())
}

/// Standard base64 (no dependency for one use).
pub fn base64(b: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut s = String::with_capacity(b.len().div_ceil(3) * 4);
    for c in b.chunks(3) {
        let n = (c[0] as u32) << 16 | (*c.get(1).unwrap_or(&0) as u32) << 8 | *c.get(2).unwrap_or(&0) as u32;
        s.push(T[(n >> 18) as usize & 63] as char);
        s.push(T[(n >> 12) as usize & 63] as char);
        s.push(if c.len() > 1 { T[(n >> 6) as usize & 63] as char } else { '=' });
        s.push(if c.len() > 2 { T[n as usize & 63] as char } else { '=' });
    }
    s
}

// ------------------------------------------------------------------------------------------------ Tauri

/// The commands the UI's `themes.js` calls (registered in `app.rs`).
#[cfg(feature = "app")]
pub mod commands {
    use super::*;
    use crate::catalog;
    use crate::settings::app_dir;
    use std::sync::Mutex;
    use tauri::AppHandle;
    use tauri_plugin_dialog::DialogExt;

    static LOCK: Mutex<()> = Mutex::new(());

    async fn blocking<T: Send + 'static>(f: impl FnOnce() -> Result<T, String> + Send + 'static) -> Result<T, String> {
        tauri::async_runtime::spawn_blocking(move || {
            let _g = LOCK.lock().map_err(|_| "theme lock poisoned")?;
            f()
        })
        .await
        .map_err(|e| e.to_string())?
    }

    #[tauri::command]
    pub async fn themes_list() -> Result<Themes, String> {
        blocking(|| Ok(list(&app_dir()))).await
    }

    #[tauri::command]
    pub async fn theme_apply(id: String) -> Result<(), String> {
        blocking(move || set_active(&app_dir(), &id)).await
    }

    #[tauri::command]
    pub async fn theme_css(id: String) -> Result<ThemeCss, String> {
        blocking(move || css(&app_dir(), &id)).await
    }

    /// Install a catalog theme by project id (looked up in the cached catalog; the UI never passes a URL).
    #[tauri::command]
    pub async fn theme_install(project: String) -> Result<ThemeInfo, String> {
        blocking(move || {
            let dir = app_dir();
            let cat = catalog::cached(&dir, catalog::URL).ok_or("Open Discover first so Leyline has the catalog.")?;
            let p = cat.into_iter().find(|x| x.id == project).ok_or("That theme is not in the catalog any more.")?;
            install_project(&dir, &p, &net::origin(catalog::URL).unwrap_or_default())
        })
        .await
    }

    #[tauri::command]
    pub async fn theme_install_local(path: String) -> Result<ThemeInfo, String> {
        blocking(move || install_local(&app_dir(), &PathBuf::from(path.trim()))).await
    }

    #[tauri::command]
    pub async fn theme_remove(id: String) -> Result<(), String> {
        blocking(move || remove(&app_dir(), &id)).await
    }

    #[tauri::command]
    pub async fn pick_theme(app: AppHandle, folder: bool) -> Option<String> {
        tauri::async_runtime::spawn_blocking(move || {
            let d = app.dialog().file().set_title(if folder { "Choose a theme folder" } else { "Choose a theme pack (.zip)" });
            if folder {
                d.blocking_pick_folder()
            } else {
                d.add_filter("Theme pack (.zip)", &["zip"]).blocking_pick_file()
            }
        })
        .await
        .ok()
        .flatten()
        .and_then(|p| p.into_path().ok())
        .map(|p| p.display().to_string())
    }
}

// ------------------------------------------------------------------------------------------------ tests

#[cfg(test)]
mod tests {
    use super::*;
    use crate::net::testserver::*;

    const PNG: &[u8] = b"\x89PNG\r\n\x1a\n0000IHDR";
    const META: &str = r#"{"id":"night-owl","name":"Night Owl","author":"alice","version":"1.0.0","licence":"MIT",
        "preview":"preview.png","kind":"rounded-dark","description":"Deep blue."}"#;
    const CSS: &str = "/* hi */ :root{--t-accent:#88f;--t-radius:10px}\n.side{background:url(images/bg.png) center/cover;}\
        @media (prefers-reduced-motion: reduce){.btn{transition:none}}\n@font-face{font-family:Owl;src:url('fonts/owl.woff2') format(\"woff2\")}";

    fn files(css: &str) -> Vec<(String, Vec<u8>)> {
        vec![
            ("theme.json".into(), META.as_bytes().to_vec()),
            ("theme.css".into(), css.as_bytes().to_vec()),
            ("preview.png".into(), PNG.to_vec()),
            ("images/bg.png".into(), PNG.to_vec()),
            ("fonts/owl.woff2".into(), b"wOF2rest".to_vec()),
            ("LICENSE.txt".into(), b"MIT".to_vec()),
        ]
    }

    fn css_err(css: &str) -> String {
        check_files(files(css)).err().unwrap_or_else(|| panic!("should be refused: {css}"))
    }

    #[test]
    fn a_good_pack_passes_and_is_rebuilt() {
        let p = check_files(files(CSS)).unwrap();
        assert_eq!(p.meta.id, "night-owl");
        assert!(p.css.contains(".side{background:url(\"images/bg.png\") center/cover;}"), "{}", p.css);
        assert!(p.css.contains("@media (prefers-reduced-motion: reduce){.btn{transition:none;}}"), "{}", p.css);
        assert!(p.css.contains("@font-face{font-family:Owl;src:url(\"fonts/owl.woff2\") format(\"woff2\");}"), "{}", p.css);
        assert!(!p.css.contains("hi"), "comments dropped");
        // Zipping a folder puts everything under one top folder: that is taken off.
        let nested = files(CSS).into_iter().map(|(r, b)| (format!("night-owl/{r}"), b)).collect();
        assert_eq!(check_files(nested).unwrap().meta.id, "night-owl");
    }

    #[test]
    fn no_scripts_no_remote_urls_no_imports() {
        for bad in [
            "@import url(images/bg.png);",
            "@import 'x.css'; a{color:red}",
            "a{background:url(https://evil.example/x.png)}",
            "a{background:url(//evil.example/x.png)}",
            "a{background:url(data:image/png;base64,AAAA)}",
            "a{background:url(../x.png)}",
            "a{background:url(images/missing.png)}",
            "a{width:expression(alert(1))}",
            "a{background:url(javascript:alert(1))}",
            "a{-moz-binding:url(x.xml#x)}",
            "a{behavior:url(x.htc)}",
            "a{background:image-set('https://e.x/a.png' 1x)}",
            "a{background:\\75rl(https://e.x)}",
            "</style><script>alert(1)</script>",
            "a{content:\"Enter your password\"}",
            "a{display:none}",
            "a{position:fixed}",
            "a{pointer-events:none}",
            "@namespace x url(http://e.x);",
            "@charset \"utf-8\";",
            "a{b{color:red}}",
            "a{color:red",
            "a{color:\"red}",
            "@media screen and (url(x)){a{color:red}}",
            "a[href^=\"http\"]{background:url(images/bg.png)}x{--a:url(https://e.x)}",
            "a{--x:url(https://e.x/track.png)}",
            "a{font-family:\"x\"} @font-face{src:url(images/bg.png)}",
            "@font-face{font-family:x;color:red}",
            "@keyframes spin{evil{color:red}}",
            "a{color:attr(data-x)}",
        ] {
            let e = css_err(bad);
            assert!(e.starts_with("theme.css"), "{bad}: {e}");
        }
        // Allowed: custom properties, plain rules, empty content, keyframes, supports.
        let ok = ":root{--x: 4px !important}a::before{content:\"\"}@keyframes glow{from{opacity:0.5}50%{opacity:1}to{opacity:.8}}\
            @supports (backdrop-filter: blur(4px)){.panel{backdrop-filter:blur(4px)}}html[data-theme=\"x\"] .nav.on{border-radius:12px}";
        check_files(files(ok)).unwrap();
    }

    #[test]
    fn only_the_allowed_files_with_the_right_bytes() {
        let with = |rel: &str, b: &[u8]| {
            let mut f = files(CSS);
            f.push((rel.to_string(), b.to_vec()));
            check_files(f)
        };
        assert!(with("evil.js", b"alert(1)").is_err());
        assert!(with("theme.html", b"<p>").is_err());
        assert!(with("extra.css", b"a{}").is_err(), "one CSS file only");
        assert!(with("x.png", b"MPQ\x1a....").is_err(), "game data magic is not a png");
        assert!(with("x.webp", b"RIFF0000WEBPVP8 ").is_ok());
        assert!(with("a/b/c/d.png", PNG).is_err(), "too deep");
        assert!(with("../up.png", PNG).is_err());
        assert!(with("x.svg", b"<svg xmlns=\"http://www.w3.org/2000/svg\"><script>alert(1)</script></svg>").is_err());
        assert!(with("x.svg", b"<svg onload=\"alert(1)\"/>").is_err());
        assert!(with("x.svg", b"<svg/onload=alert(1)>").is_err());
        assert!(with("x.svg", b"<svg><image href=\"https://e.x/a.png\"/></svg>").is_err());
        assert!(with("x.svg", b"<svg><use xlink:href=\"other.svg#a\"/></svg>").is_err());
        assert!(with("x.svg", b"<svg><rect style=\"fill:url(https://e.x)\"/></svg>").is_err());
        assert!(with("x.svg", b"<svg viewBox=\"0 0 1 1\"><defs><linearGradient id=\"g\"/></defs><rect fill=\"url(#g)\" font=\"x\"/><use href=\"#g\"/></svg>").is_ok());
        let mut f = files(CSS);
        f.push(("big.png".into(), [PNG, &vec![0u8; MAX_PACK as usize]].concat()));
        assert!(check_files(f).unwrap_err().contains("5 MB"));
        let mut f = files(CSS);
        f.retain(|(r, _)| r != "theme.css");
        assert!(check_files(f).is_err());
    }

    #[test]
    fn theme_json_is_checked() {
        for bad in [
            r#"{"id":"Bad Id","name":"x","author":"a","version":"1","licence":"MIT","kind":"classic"}"#,
            r#"{"id":"dark-rounded","name":"x","author":"a","version":"1","licence":"MIT","kind":"classic"}"#,
            r#"{"id":"leyline-classic","name":"x","author":"a","version":"1","licence":"MIT","kind":"dark"}"#,
            r#"{"id":"good-id","name":"x","author":"a","version":"1","licence":"MIT","kind":"system"}"#,
            r#"{"id":"good-id","name":"x","author":"a","version":"1","licence":"MIT","kind":"neon"}"#,
            r#"{"id":"good-id","name":"x","author":"a","version":"1","kind":"classic"}"#,
            r#"[1]"#,
        ] {
            assert!(parse_meta(bad.as_bytes()).is_err(), "{bad}");
        }
        let mut f = files(CSS);
        f[0].1 = META.replace("preview.png", "images/none.png").into_bytes();
        assert!(check_files(f).is_err(), "preview must be in the pack");
    }

    fn zip_of(fs_: &[(String, Vec<u8>)]) -> Vec<u8> {
        use std::io::Write;
        let mut w = zip::ZipWriter::new(io::Cursor::new(Vec::new()));
        for (r, b) in fs_ {
            w.start_file(r.as_str(), zip::write::SimpleFileOptions::default()).unwrap();
            w.write_all(b).unwrap();
        }
        w.finish().unwrap().into_inner()
    }

    #[test]
    fn install_list_apply_css_remove() {
        let d = tempfile::tempdir().unwrap();
        let app = d.path();
        assert_eq!(active(app), DEFAULT);
        assert_eq!(list(app).themes.len(), BUILTINS.len());
        let z = app.join("night-owl.zip");
        fs::write(&z, zip_of(&files(CSS))).unwrap();
        let t = install_local(app, &z).unwrap();
        assert_eq!((t.id.as_str(), t.source.as_str()), ("night-owl", "file"));
        assert!(t.preview.as_deref().unwrap().starts_with("data:image/png;base64,iVBORw0KGgo"));
        let l = list(app);
        assert_eq!(l.themes.len(), BUILTINS.len() + 1);
        set_active(app, "night-owl").unwrap();
        assert_eq!(active(app), "night-owl");
        let c = css(app, "night-owl").unwrap();
        assert_eq!(c.kind, "dark", "an older pack kind (rounded-dark) is read as dark");
        assert!(c.css.contains("url(\"data:image/png;base64,") && c.css.contains("url(\"data:font/woff2;base64,d09GMnJlc3Q=\")"), "{}", c.css);
        assert!(!c.css.contains("images/bg.png"));
        // A file changed on disk after install is caught when it loads.
        fs::write(themes_dir(app).join("night-owl/theme.css"), "@import 'https://e.x/a.css';").unwrap();
        assert!(css(app, "night-owl").is_err());
        assert!(list(app).themes.iter().any(|t| t.id == "night-owl" && t.problem.is_some()));
        // A folder install replaces it.
        let folder = app.join("src/night-owl");
        for (r, b) in files(CSS) {
            let p = folder.join(&r);
            fs::create_dir_all(p.parent().unwrap()).unwrap();
            fs::write(p, b).unwrap();
        }
        install_local(app, &folder).unwrap();
        assert!(css(app, "night-owl").is_ok());
        assert!(set_active(app, "nope-theme").is_err());
        assert!(set_active(app, "light").is_ok());
        set_active(app, "night-owl").unwrap();
        assert!(remove(app, "dark").is_err());
        assert!(remove(app, "leyline-classic").is_err());
        remove(app, "night-owl").unwrap();
        assert_eq!(active(app), DEFAULT, "removing the active pack goes back to the default");
        assert!(!themes_dir(app).join("night-owl").exists());
        assert!(remove(app, "../settings").is_err());
        assert!(install_local(app, &app.join("x.txt")).is_err());
    }

    #[test]
    fn zip_slip_and_size_are_refused() {
        let d = tempfile::tempdir().unwrap();
        let z = d.path().join("evil.zip");
        let mut f = files(CSS);
        f.push(("../../evil.png".into(), PNG.to_vec()));
        fs::write(&z, zip_of(&f)).unwrap();
        assert!(read_zip(&z).is_err());
        fs::write(&z, vec![0u8; (MAX_PACK + 1) as usize]).unwrap();
        assert!(read_zip(&z).unwrap_err().contains("5 MB"));
    }

    fn project(download: &str, sha: Option<String>) -> Project {
        Project {
            id: "mod:night-owl".into(),
            source: "packaged".into(),
            name: "Night Owl".into(),
            category: CATEGORY.into(),
            download: Some(download.into()),
            sha256: sha,
            ..Default::default()
        }
    }

    #[test]
    fn catalog_install_checks_the_sha256_and_the_site() {
        let d = tempfile::tempdir().unwrap();
        let app = d.path();
        let body = zip_of(&files(CSS));
        let sha = {
            use sha2::{Digest, Sha256};
            net::hex(&Sha256::digest(&body))
        };
        let base = serve_routes(vec![("/wrath/mods/night-owl/download", "200 OK", body.clone())]);
        let url = format!("{base}/wrath/mods/night-owl/download");
        let origin = net::origin(&base).unwrap();
        assert!(install_project(app, &project(&url, Some("0".repeat(64))), &origin).unwrap_err().contains("checksum"));
        assert!(install_project(app, &project(&url, None), &origin).unwrap_err().contains("checksum"));
        assert!(install_project(app, &project(&url, Some(sha.clone())), "https://play.openvanilla.app").is_err());
        let mut not_theme = project(&url, Some(sha.clone()));
        not_theme.category = "addons".into();
        assert!(install_project(app, &not_theme, &origin).is_err());
        let base2 = serve_routes(vec![("/wrath/mods/night-owl/download", "200 OK", body)]);
        let url2 = format!("{base2}/wrath/mods/night-owl/download");
        let t = install_project(app, &project(&url2, Some(sha)), &net::origin(&base2).unwrap()).unwrap();
        assert_eq!((t.source.as_str(), t.project.as_str()), ("catalog", "mod:night-owl"));
        assert!(fs::read_dir(themes_dir(app)).unwrap().flatten().all(|e| !e.file_name().to_string_lossy().starts_with(".download")));
    }

    #[test]
    fn base64_matches() {
        assert_eq!(base64(b""), "");
        assert_eq!(base64(b"f"), "Zg==");
        assert_eq!(base64(b"fo"), "Zm8=");
        assert_eq!(base64(b"foo"), "Zm9v");
        assert_eq!(base64(b"foobar"), "Zm9vYmFy");
    }

    /// Packs are inlined as data: addresses; the window must still refuse every script that is not the app's own.
    #[test]
    fn the_csp_blocks_remote_scripts_and_loads() {
        let conf: serde_json::Value = serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        let csp = conf["app"]["security"]["csp"].as_str().unwrap();
        let dir = |name: &str| csp.split(';').map(str::trim).find(|d| d.starts_with(name)).unwrap_or_else(|| panic!("{name} missing")).to_string();
        assert_eq!(dir("script-src"), "script-src 'self'");
        assert_eq!(dir("default-src"), "default-src 'self'");
        assert_eq!(dir("connect-src"), "connect-src ipc: http://ipc.localhost");
        // Images: the app, data: (packs are inlined) and exactly one https origin, the website's backdrop picture
        // (ui/app.js BACKDROP_URL). Pack CSS still can't name it: the checker refuses every http(s) url().
        assert_eq!(dir("img-src"), "img-src 'self' data: https://play.openvanilla.app");
        for d in ["font-src", "style-src"] {
            let v = dir(d);
            assert!(!v.contains("http:") && !v.contains("https:") && !v.contains('*') && !v.contains("unsafe-eval"), "{v}");
        }
        assert!(!csp.contains("unsafe-eval"));
    }

    #[test]
    fn builtins_are_known() {
        assert!(BUILTINS.iter().any(|b| b.0 == DEFAULT));
        assert!(BUILTINS.iter().all(|b| !id_ok(b.0)), "packs cannot take a built-in's id");
        assert!(LEGACY.iter().all(|l| !id_ok(l.0)), "nor an older built-in's");
    }

    #[test]
    fn only_dark_and_light_are_built_in_and_dark_is_the_default() {
        let ids: Vec<&str> = BUILTINS.iter().map(|b| b.0).collect();
        assert_eq!(ids, ["dark", "light"]);
        assert_eq!(DEFAULT, "dark");
        assert_eq!(KINDS, ["dark", "light"]);
        let d = tempfile::tempdir().unwrap();
        let l = list(d.path());
        assert_eq!(l.active, "dark", "nothing saved: Dark");
        assert_eq!(l.themes.iter().map(|t| (t.id.as_str(), t.name.as_str(), t.kind.as_str())).collect::<Vec<_>>(),
            [("dark", "Dark", "dark"), ("light", "Light", "light")]);
        for t in &l.themes {
            for bad in ["Classic", "parchment", "Rounded", "World of Warcraft", "WoW", "Warcraft", "Blizzard"] {
                assert!(!t.name.contains(bad) && !t.description.contains(bad), "{bad} in {t:?}");
            }
        }
    }

    #[test]
    fn an_older_saved_choice_moves_to_dark_or_light() {
        let d = tempfile::tempdir().unwrap();
        let app = d.path();
        fs::create_dir_all(themes_dir(app)).unwrap();
        for (old, new) in [("leyline-classic", "dark"), ("dark-rounded", "dark"), ("light-rounded", "light"), ("rounded-system", "dark"),
            ("gone-pack", "dark"), ("", "dark")] {
            fs::write(themes_dir(app).join("active.json"), format!(r#"{{"theme":"{old}"}}"#)).unwrap();
            assert_eq!(active(app), new, "{old}");
            assert_eq!(list(app).active, new, "{old}");
        }
        // An older UI asking for an old id gets the new one saved.
        set_active(app, "light-rounded").unwrap();
        let saved: Active = serde_json::from_slice(&fs::read(themes_dir(app).join("active.json")).unwrap()).unwrap();
        assert_eq!(saved.theme, "light");
        set_active(app, "leyline-classic").unwrap();
        assert_eq!(active(app), "dark");
        // A pack made for an older Leyline still installs: its kind is read as today's.
        for (old, new) in [("classic", "dark"), ("rounded-dark", "dark"), ("rounded-light", "light"), ("light", "light")] {
            let m = parse_meta(format!(r#"{{"id":"old-pack","name":"x","author":"a","version":"1","licence":"MIT","kind":"{old}"}}"#).as_bytes()).unwrap();
            assert_eq!(m.kind, new, "{old}");
        }
    }
}
