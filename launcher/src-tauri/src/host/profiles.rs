//! Host any client: which realm the host kit can run for the clients Leyline found on this PC.
//!
//! The kit hosts the 3.3.5a profiles on AzerothCore (its default compose file) and, for other clients, the
//! profiles in `hosting/kit/profiles/<id>/` (built on the host's PC from each core's own source; their facts are
//! in `hosting/kit/tools/wuhost/cores.py`, and the hosting tests check this table against it). The Host page
//! offers the profiles whose build matches one of the player's own clients (`clients.rs`), with that client's
//! folder filled in: the kit reads the server data from it (read-only) and nothing is downloaded.
//!
//! The choice is kept in the kit folder (`state/launcher-host.json`) and handed to the kit's script as
//! `WU_PROFILE` / `LEYLINE_RULESET` and `WU_CLIENT_DIR` (3.3.5a: `WU_WOW_DIR`) when the realm starts.
//!
//! A Den (`den`, docs/DEN.md: a private room to build in) is always private: its start also gets
//! `LEYLINE_VISIBILITY` / `WU_VISIBILITY=private` (and `host.rs` adds `--private`), and on its first start the name
//! "My Den". The kit then makes its join page take accounts only from the invite link and never runs bots.

use crate::clients::{Build, ClientProfile};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

/// One realm profile the kit can host.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct KitProfile {
    pub id: &'static str,
    pub label: &'static str,
    pub build: Build,
    pub core: &'static str,
    /// Lives in `profiles/<id>/` of the kit (another client); the 3.3.5a ones use the kit's default files.
    pub own_folder: bool,
}

pub const PROFILES: &[KitProfile] = &[
    KitProfile { id: "dalaran", label: "3.3.5a: a light Dalaran hangout (boost to 80, no bots)", build: Build::V335a, core: "azerothcore", own_folder: false },
    KitProfile { id: "den", label: "3.3.5a: My Den (a private room to build in)", build: Build::V335a, core: "azerothcore", own_folder: false },
    KitProfile { id: "main", label: "3.3.5a: normal from level 1, or a one-time boost", build: Build::V335a, core: "azerothcore", own_folder: false },
    KitProfile { id: "brawl", label: "3.3.5a: everyone starts at 80", build: Build::V335a, core: "azerothcore", own_folder: false },
    KitProfile { id: "progression", label: "3.3.5a: blizzlike progression", build: Build::V335a, core: "azerothcore", own_folder: false },
    KitProfile { id: "vanillaplus", label: "3.3.5a: Vanilla+ (the original world to 60, made to stay up)", build: Build::V335a, core: "azerothcore", own_folder: false },
    KitProfile { id: "cmangos-1.12.1", label: "1.12.1: a plain realm (CMaNGOS Classic)", build: Build::V1121, core: "cmangos", own_folder: true },
    KitProfile { id: "cmangos-2.4.3", label: "2.4.3: a plain realm (CMaNGOS TBC)", build: Build::V243, core: "cmangos", own_folder: true },
    KitProfile { id: "tcpp-4.3.4", label: "4.3.4: a plain realm (TrinityCore 4.3.4)", build: Build::V434, core: "trinitycore", own_folder: true },
];

/// A profile id as the kit names its folders: never a path.
pub fn id_ok(id: &str) -> bool {
    let b = id.as_bytes();
    (2..=32).contains(&b.len())
        && b[0].is_ascii_alphanumeric()
        && b.iter().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'.' || *c == b'-')
        && !id.contains("..")
}

/// The private room to build in (docs/DEN.md): private, sign-up from the invite link only, no bots.
pub const DEN: &str = "den";
/// A new Den's name (the kit's own question otherwise).
pub const DEN_NAME: &str = "My Den";

/// The profiles that never run bots (the kit refuses them): the Dalaran hangout and a Den.
pub fn no_bots(id: &str) -> bool {
    id == "dalaran" || id == DEN
}

pub fn find(id: &str) -> Option<&'static KitProfile> {
    PROFILES.iter().find(|p| p.id == id)
}

/// One of the player's clients a profile can use.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ClientPick {
    pub id: String,
    pub name: String,
    pub path: String,
}

/// What the Host page shows for one profile.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Offer {
    pub id: String,
    pub label: String,
    /// The client build it runs, as players write it (`2.4.3`).
    pub version: String,
    pub core: String,
    /// This kit has the profile's files (an older kit may not).
    pub in_kit: bool,
    /// The player's clients of that build; empty: add one on the Clients page first.
    pub clients: Vec<ClientPick>,
    /// Why it cannot be picked yet, in plain words.
    pub note: Option<String>,
}

/// The kit's profiles for these clients: the ones a client on this PC can play first, then the rest (with a note).
pub fn offers(kit: Option<&Path>, clients: &[ClientProfile]) -> Vec<Offer> {
    offers_in(kit, clients, crate::clients::all_clients())
}

/// `offers`; a profile on a build that is not offered now (tcpp-4.3.4: `clients::MAX_OFFERED_BUILD`) is left out
/// unless `all`.
pub fn offers_in(kit: Option<&Path>, clients: &[ClientProfile], all: bool) -> Vec<Offer> {
    let mut out: Vec<Offer> = PROFILES
        .iter()
        .filter(|p| p.build.offered_in(all))
        .map(|p| {
            let in_kit = !p.own_folder || kit.is_some_and(|k| k.join("profiles").join(p.id).join("profile.lock").is_file());
            let picks: Vec<ClientPick> = clients
                .iter()
                .filter(|c| c.build == p.build)
                .map(|c| ClientPick { id: c.id.clone(), name: c.name.clone(), path: c.path.display().to_string() })
                .collect();
            let note = if !in_kit {
                Some("Your host kit is older than this profile: update the Host pack.".to_string())
            } else if picks.is_empty() {
                Some(format!("Add your own {} client on the Clients page first: the server data is made from it.", p.build.version()))
            } else {
                None
            };
            Offer {
                id: p.id.into(),
                label: p.label.into(),
                version: p.build.version().into(),
                core: p.core.into(),
                in_kit,
                clients: picks,
                note,
            }
        })
        .collect();
    out.sort_by_key(|o| o.note.is_some());
    out
}

/// The Host page's choice, kept in the kit folder.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Choice {
    pub profile: String,
    #[serde(default)]
    pub client_dir: String,
}

fn choice_path(kit: &Path) -> PathBuf {
    kit.join("state").join("launcher-host.json")
}

pub fn read_choice(kit: &Path) -> Option<Choice> {
    let c: Choice = serde_json::from_str(&fs::read_to_string(choice_path(kit)).ok()?).ok()?;
    (id_ok(&c.profile) && find(&c.profile).is_some_and(|p| p.build.offered())).then_some(c)
}

/// Keep the choice: a known profile and, when given, one of the player's own clients of its build.
/// An empty `profile` forgets the choice: the kit keeps the realm it hosts, or asks.
pub fn choose(kit: &Path, profile: &str, client: Option<&ClientProfile>) -> Result<Choice, String> {
    if profile.is_empty() {
        let _ = fs::remove_file(choice_path(kit));
        return Ok(Choice::default());
    }
    let p = find(profile).ok_or("That is not a realm profile Leyline knows.")?;
    if !p.build.offered() {
        return Err(format!("{} realms are not offered yet.", p.build.version()));
    }
    if p.own_folder && !kit.join("profiles").join(p.id).join("profile.lock").is_file() {
        return Err("Your host kit is older than this profile: update the Host pack first.".into());
    }
    let client_dir = match client {
        Some(c) if c.build != p.build => {
            return Err(format!("That client is {}; this realm needs a {} client.", c.build.version(), p.build.version()))
        }
        Some(c) => c.path.display().to_string(),
        None => String::new(),
    };
    let c = Choice { profile: p.id.into(), client_dir };
    fs::create_dir_all(kit.join("state")).map_err(|e| e.to_string())?;
    fs::write(choice_path(kit), serde_json::to_string_pretty(&c).map_err(|e| e.to_string())?)
        .map_err(|e| format!("Could not save the choice in the kit folder: {e}"))?;
    Ok(c)
}

/// The environment the kit's script gets for the saved choice (empty: the script asks, as before).
pub fn env_for(kit: &Path) -> Vec<(String, String)> {
    let Some(c) = read_choice(kit) else { return Vec::new() };
    let Some(p) = find(&c.profile) else { return Vec::new() };
    let mut env = vec![("WU_PROFILE".to_string(), c.profile.clone()), ("LEYLINE_RULESET".to_string(), c.profile.clone())];
    if c.profile == DEN {
        for k in ["LEYLINE_VISIBILITY", "WU_VISIBILITY"] {
            env.push((k.to_string(), "private".to_string()));
        }
        // the first start only: a realm already set up keeps its own name
        if !kit.join("state").join("host.json").is_file() {
            for k in ["LEYLINE_NAME", "WU_NAME"] {
                env.push((k.to_string(), DEN_NAME.to_string()));
            }
        }
    }
    if !c.client_dir.is_empty() && Path::new(&c.client_dir).is_dir() {
        let key = if p.build == Build::V335a { "WU_WOW_DIR" } else { "WU_CLIENT_DIR" };
        env.push((key.to_string(), c.client_dir));
    }
    env
}

#[cfg(test)]
mod tests {
    use super::*;

    fn client(id: &str, b: Build, path: &str) -> ClientProfile {
        ClientProfile {
            id: id.into(),
            name: format!("my {}", b.version()),
            path: path.into(),
            build: b,
            realmlist: String::new(),
            locale: None,
            exe_version: None,
            exe: None,
        }
    }

    fn kit(name: &str, folders: &[&str]) -> PathBuf {
        let d = std::env::temp_dir().join(format!("wu-profiles-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&d);
        for f in folders {
            fs::create_dir_all(d.join("profiles").join(f)).unwrap();
            fs::write(d.join("profiles").join(f).join("profile.lock"), format!("LL_PROFILE={f}\n")).unwrap();
        }
        fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn ids_are_never_paths() {
        for ok in ["dalaran", "den", "cmangos-1.12.1", "tcpp-4.3.4"] {
            assert!(id_ok(ok), "{ok}");
        }
        for bad in ["", "a", "../x", "a/b", "A-b", "x..y", ".hidden", "a b", "c:\\x"] {
            assert!(!id_ok(bad), "{bad}");
        }
        assert!(PROFILES.iter().all(|p| id_ok(p.id)));
    }

    #[test]
    fn the_profiles_that_fit_my_clients_come_first() {
        let k = kit("offers", &["cmangos-1.12.1", "cmangos-2.4.3"]);
        let mine = [client("a", Build::V243, "/games/243"), client("b", Build::V335a, "/games/335")];
        // 4.3.4 is not offered for now (owner, 2026-10-30): tcpp-4.3.4 is left out unless the override is on.
        let capped = offers_in(Some(&k), &mine, false);
        assert_eq!(capped.len(), PROFILES.len() - 1);
        assert!(capped.iter().all(|x| x.id != "tcpp-4.3.4"));
        let o = offers_in(Some(&k), &mine, true);
        assert_eq!(o.len(), PROFILES.len());
        let ready: Vec<&str> = o.iter().filter(|x| x.note.is_none()).map(|x| x.id.as_str()).collect();
        assert_eq!(ready, ["dalaran", "den", "main", "brawl", "progression", "vanillaplus", "cmangos-2.4.3"]);
        let den = o.iter().find(|x| x.id == "den").unwrap();
        assert_eq!((den.version.as_str(), den.core.as_str(), den.clients[0].path.as_str()), ("3.3.5a", "azerothcore", "/games/335"));
        let tbc = o.iter().find(|x| x.id == "cmangos-2.4.3").unwrap();
        assert_eq!((tbc.version.as_str(), tbc.clients[0].path.as_str()), ("2.4.3", "/games/243"));
        let classic = o.iter().find(|x| x.id == "cmangos-1.12.1").unwrap();
        assert!(classic.in_kit && classic.note.as_deref().unwrap().contains("1.12.1 client"));
        let cata = o.iter().find(|x| x.id == "tcpp-4.3.4").unwrap();
        assert!(!cata.in_kit && cata.note.as_deref().unwrap().contains("update the Host pack"));
        let _ = fs::remove_dir_all(&k);
    }

    #[test]
    fn the_choice_reaches_the_kit_script() {
        let k = kit("choice", &["cmangos-2.4.3"]);
        let games = std::env::temp_dir().join(format!("wu-profiles-243-{}", std::process::id()));
        fs::create_dir_all(&games).unwrap();
        let tbc = client("a", Build::V243, games.to_str().unwrap());
        let wrath = client("b", Build::V335a, games.to_str().unwrap());
        assert!(env_for(&k).is_empty(), "nothing chosen: the script asks");
        assert!(choose(&k, "cmangos-2.4.3", Some(&wrath)).unwrap_err().contains("needs a 2.4.3 client"));
        let e = choose(&k, "tcpp-4.3.4", None).unwrap_err();
        assert!(e.contains(if crate::clients::all_clients() { "older" } else { "not offered yet" }), "{e}");
        assert!(choose(&k, "../../x", None).is_err());
        choose(&k, "cmangos-2.4.3", Some(&tbc)).unwrap();
        let env = env_for(&k);
        assert!(env.contains(&("WU_PROFILE".into(), "cmangos-2.4.3".into())));
        assert!(env.contains(&("LEYLINE_RULESET".into(), "cmangos-2.4.3".into())));
        assert!(env.contains(&("WU_CLIENT_DIR".into(), games.display().to_string())));
        choose(&k, "dalaran", Some(&wrath)).unwrap();
        assert!(env_for(&k).contains(&("WU_WOW_DIR".into(), games.display().to_string())));
        assert!(!env_for(&k).iter().any(|(k, _)| k.ends_with("VISIBILITY") || k.ends_with("NAME")), "only a Den is made private");
        choose(&k, "", None).unwrap();
        assert!(env_for(&k).is_empty(), "forgotten");
        fs::write(k.join("state/launcher-host.json"), r#"{"profile":"../evil","client_dir":"/"}"#).unwrap();
        assert!(env_for(&k).is_empty());
        let _ = fs::remove_dir_all(&k);
        let _ = fs::remove_dir_all(&games);
    }

    /// A Den (docs/DEN.md): private, its own name on the first start only, never bots.
    #[test]
    fn a_den_is_private_and_has_no_bots() {
        let k = kit("den", &[]);
        let games = std::env::temp_dir().join(format!("wu-profiles-den-335-{}", std::process::id()));
        fs::create_dir_all(&games).unwrap();
        let wrath = client("b", Build::V335a, games.to_str().unwrap());
        let p = find(DEN).unwrap();
        assert_eq!((p.build, p.core, p.own_folder), (Build::V335a, "azerothcore", false));
        assert!(p.label.contains("My Den"));
        assert!(no_bots("den") && no_bots("dalaran") && !no_bots("main") && !no_bots("brawl"));
        let tbc = client("a", Build::V243, games.to_str().unwrap());
        assert!(choose(&k, DEN, Some(&tbc)).unwrap_err().contains("needs a 3.3.5a client"));
        choose(&k, DEN, Some(&wrath)).unwrap();
        let env = env_for(&k);
        for (key, v) in [("WU_PROFILE", "den"), ("LEYLINE_RULESET", "den"), ("LEYLINE_VISIBILITY", "private"), ("WU_VISIBILITY", "private"),
            ("LEYLINE_NAME", "My Den"), ("WU_NAME", "My Den")] {
            assert!(env.contains(&(key.into(), v.into())), "{key}={v}: {env:?}");
        }
        assert!(env.contains(&("WU_WOW_DIR".into(), games.display().to_string())));
        // set up once: the realm keeps its own name, and stays private
        fs::write(k.join("state/host.json"), r#"{"realm_id":"abcdefghijk2345a","name":"Bea's Den","profile":"den"}"#).unwrap();
        let env = env_for(&k);
        assert!(!env.iter().any(|(k, _)| k.ends_with("NAME")), "{env:?}");
        assert!(env.contains(&("LEYLINE_VISIBILITY".into(), "private".into())));
        let _ = fs::remove_dir_all(&k);
        let _ = fs::remove_dir_all(&games);
    }

    /// The table matches the kit: every profile with its own folder exists in hosting/kit/profiles with the same
    /// build, and every folder there is offered here.
    #[test]
    fn matches_the_kit_folders() {
        let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../hosting/kit/profiles");
        if !dir.is_dir() {
            return; // the exported launcher repo has no hosting/ folder
        }
        for p in PROFILES.iter().filter(|p| p.own_folder) {
            // a Windows checkout may give the file CRLF line ends
            let lock = fs::read_to_string(dir.join(p.id).join("profile.lock"))
                .unwrap_or_else(|_| panic!("{} has no folder", p.id))
                .replace("\r\n", "\n");
            assert!(lock.contains(&format!("\nLL_BUILD={}\n", p.build.number())), "{}: build", p.id);
            assert!(lock.contains(&format!("\nLL_CORE={}\n", p.core)), "{}: core", p.id);
        }
        for e in fs::read_dir(&dir).unwrap().flatten() {
            if e.path().join("profile.lock").is_file() {
                let id = e.file_name().to_string_lossy().to_string();
                assert!(find(&id).is_some(), "{id} is in the kit but not offered by the launcher");
            }
        }
    }
}
