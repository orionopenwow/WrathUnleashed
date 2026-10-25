//! Starting a client: its executable, from its own folder. On macOS and Linux through Wine when that is on.

use crate::clients::{find_ci, ClientProfile};
use crate::settings::Wine;
use std::path::PathBuf;
use std::process::{Child, Command};

/// What will be run. Built separately from running it so it can be tested.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Plan {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub cwd: PathBuf,
    pub env: Vec<(String, String)>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Os {
    Windows,
    Other,
}

impl Os {
    pub fn current() -> Os {
        if cfg!(windows) {
            Os::Windows
        } else {
            Os::Other
        }
    }
}

pub fn plan(profile: &ClientProfile, wine: &Wine, os: Os) -> Result<Plan, String> {
    let exe = find_ci(&profile.path, profile.build.exe_name())
        .ok_or_else(|| format!("The game's .exe is missing from {}.", profile.path.display()))?;
    let cwd = profile.path.clone();
    match os {
        Os::Windows => Ok(Plan { program: exe, args: vec![], cwd, env: vec![] }),
        Os::Other if wine.enabled => {
            let cmd = wine.command.trim();
            if cmd.is_empty() {
                return Err("Set the Wine command in Settings.".into());
            }
            let env = if wine.prefix.trim().is_empty() {
                vec![]
            } else {
                vec![("WINEPREFIX".to_string(), wine.prefix.trim().to_string())]
            };
            Ok(Plan { program: cmd.into(), args: vec![exe.to_string_lossy().to_string()], cwd, env })
        }
        Os::Other => Err("This client is a Windows program. Turn on Wine in Settings to launch it here.".into()),
    }
}

pub fn run(p: &Plan) -> Result<Child, String> {
    Command::new(&p.program)
        .args(&p.args)
        .current_dir(&p.cwd)
        .envs(p.env.iter().map(|(k, v)| (k, v)))
        .spawn()
        .map_err(|e| format!("Could not start {}: {e}", p.program.display()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::clients::{detect, new_profile, testutil};

    fn client() -> (tempfile::TempDir, ClientProfile) {
        let d = tempfile::tempdir().unwrap();
        testutil::fake_335a(d.path(), true);
        let p = new_profile(d.path(), &detect(d.path()).unwrap(), &[]);
        (d, p)
    }

    #[test]
    fn windows_runs_the_exe_in_its_folder() {
        let (d, p) = client();
        let pl = plan(&p, &Wine::default(), Os::Windows).unwrap();
        assert_eq!(pl.program, d.path().join("Wow.exe"));
        assert_eq!(pl.cwd, d.path());
        assert!(pl.args.is_empty());
    }

    #[test]
    fn elsewhere_through_wine() {
        let (d, p) = client();
        let w = Wine { enabled: true, command: "wine64".into(), prefix: "/home/me/.wine-leyline".into() };
        let pl = plan(&p, &w, Os::Other).unwrap();
        assert_eq!(pl.program, PathBuf::from("wine64"));
        assert_eq!(pl.args, vec![d.path().join("Wow.exe").to_string_lossy().to_string()]);
        assert_eq!(pl.env, vec![("WINEPREFIX".into(), "/home/me/.wine-leyline".into())]);
        let off = Wine { enabled: false, ..w };
        assert!(plan(&p, &off, Os::Other).unwrap_err().contains("Wine"));
    }

    #[test]
    fn missing_exe() {
        let (d, p) = client();
        std::fs::remove_file(d.path().join("Wow.exe")).unwrap();
        assert!(plan(&p, &Wine::default(), Os::Windows).unwrap_err().contains("missing"));
    }

    #[cfg(unix)]
    #[test]
    fn run_starts_a_process_in_the_folder() {
        let d = tempfile::tempdir().unwrap();
        let pl = Plan { program: "sh".into(), args: vec!["-c".into(), "pwd > out.txt".into()], cwd: d.path().into(), env: vec![] };
        run(&pl).unwrap().wait().unwrap();
        let out = std::fs::read_to_string(d.path().join("out.txt")).unwrap();
        assert_eq!(std::fs::canonicalize(out.trim()).unwrap(), std::fs::canonicalize(d.path()).unwrap());
    }
}
