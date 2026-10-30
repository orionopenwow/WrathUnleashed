//! Docker for hosting: is it there and running, and the realm's own compose calls (stop, logs) plus the
//! kit's tools image (a new invite link). Every call is `docker ...` with fixed arguments and the kit folder;
//! nothing from the UI reaches a command line.

use serde::Serialize;
use std::io::Read;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use super::HostOs;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DockerState {
    /// No `docker` program.
    Missing,
    /// The program is there, the engine is not running (Docker Desktop closed).
    Stopped,
    /// Running, but without `docker compose`.
    NoCompose,
    Ready,
}

#[derive(Debug, Clone, Serialize)]
pub struct DockerInfo {
    pub state: DockerState,
    pub version: Option<String>,
    /// What to do, in plain words, for this OS.
    pub help: String,
    /// The page to get Docker from, for this OS.
    pub get_url: &'static str,
}

pub const DESKTOP_URL: &str = "https://docs.docker.com/desktop/";
pub const ENGINE_URL: &str = "https://docs.docker.com/engine/install/";

/// A command's exit code and output (stdout then stderr), or None when it could not start.
pub type Runner<'a> = &'a dyn Fn(&[&str]) -> Option<(i32, String)>;

pub fn help(os: HostOs, state: DockerState) -> (String, &'static str) {
    let get = match os {
        HostOs::Windows => "Install Docker Desktop for Windows (it sets up WSL 2 for you), then start it once and accept its terms.",
        HostOs::Mac => "Install Docker Desktop for Mac (Apple chip or Intel, pick yours), then open it once.",
        HostOs::Linux => "Install Docker Engine with the compose plugin from your distribution's guide on docs.docker.com, then add yourself to the docker group (sudo usermod -aG docker $USER) and log out and in.",
    };
    let url = if os == HostOs::Linux { ENGINE_URL } else { DESKTOP_URL };
    let text = match state {
        DockerState::Missing => get.to_string(),
        DockerState::Stopped => match os {
            HostOs::Linux => "Docker is installed but not running: sudo systemctl start docker (and enable it to start at boot). If it says permission denied, add yourself to the docker group.".into(),
            _ => "Docker Desktop is installed but not running: open it and wait for \"Engine running\".".into(),
        },
        DockerState::NoCompose => match os {
            HostOs::Linux => "This Docker has no compose plugin: install docker-compose-plugin from the same guide.".into(),
            _ => "This Docker Desktop is too old for `docker compose`: update it.".into(),
        },
        DockerState::Ready => "Docker is ready.".into(),
    };
    (text, url)
}

pub fn detect(os: HostOs, run: Runner) -> DockerInfo {
    let state;
    let mut version = None;
    match run(&["version", "--format", "{{.Server.Version}}"]) {
        None => state = DockerState::Missing,
        Some((0, out)) if !out.trim().is_empty() => {
            version = Some(out.trim().lines().next().unwrap_or("").chars().take(40).collect());
            state = match run(&["compose", "version"]) {
                Some((0, _)) => DockerState::Ready,
                _ => DockerState::NoCompose,
            };
        }
        Some(_) => state = DockerState::Stopped,
    }
    let (help, get_url) = help(os, state);
    DockerInfo { state, version, help, get_url }
}

/// Run `docker` with `args` in `cwd`, at most `timeout`; output capped at 256 KB.
pub fn run_docker(args: &[&str], cwd: Option<&Path>, timeout: Duration) -> Option<(i32, String)> {
    run_capture("docker", args, cwd, timeout)
}

/// Run `program` with `args`, at most `timeout` (then it is killed, code -2); None when it cannot start.
pub fn run_capture(program: &str, args: &[&str], cwd: Option<&Path>, timeout: Duration) -> Option<(i32, String)> {
    let mut c = Command::new(program);
    c.args(args).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    if let Some(d) = cwd {
        c.current_dir(d);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        c.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = c.spawn().ok()?;
    let mut out = child.stdout.take()?;
    let mut err = child.stderr.take()?;
    let t1 = std::thread::spawn(move || {
        let mut b = Vec::new();
        let _ = (&mut out).take(256 * 1024).read_to_end(&mut b);
        b
    });
    let t2 = std::thread::spawn(move || {
        let mut b = Vec::new();
        let _ = (&mut err).take(64 * 1024).read_to_end(&mut b);
        b
    });
    let start = Instant::now();
    let code = loop {
        match child.try_wait() {
            Ok(Some(s)) => break s.code().unwrap_or(-1),
            Ok(None) if start.elapsed() > timeout => {
                let _ = child.kill();
                let _ = child.wait();
                break -2;
            }
            Ok(None) => std::thread::sleep(Duration::from_millis(50)),
            Err(_) => break -1,
        }
    };
    let mut text = String::from_utf8_lossy(&t1.join().unwrap_or_default()).to_string();
    text.push_str(&String::from_utf8_lossy(&t2.join().unwrap_or_default()));
    Some((code, text))
}

/// Drop terminal colour codes.
pub fn plain(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut it = s.chars().peekable();
    while let Some(c) = it.next() {
        if c == '\u{1b}' {
            if it.peek() == Some(&'[') {
                it.next();
                for d in it.by_ref() {
                    if d.is_ascii_alphabetic() {
                        break;
                    }
                }
            }
            continue;
        }
        if c == '\n' || c == '\t' || !c.is_control() {
            out.push(c);
        }
    }
    out
}

/// The compose arguments for the kit (the same as the kit's own scripts use).
pub fn compose_args(kit: &Path, tail: &[&str]) -> Vec<String> {
    let mut a = vec![
        "compose".to_string(),
        "-f".into(),
        kit.join("docker-compose.host.yml").display().to_string(),
        "--project-directory".into(),
        kit.display().to_string(),
    ];
    a.extend(tail.iter().map(|s| s.to_string()));
    a
}

/// The kit's tools image, as "Realm tools.bat" runs it: `docker run --rm -v <kit>:/kit ... wuhost.setup <cmd>`.
pub fn tools_args(kit: &Path, cmd: &[&str]) -> Vec<String> {
    let mut a = vec![
        "run".to_string(),
        "--rm".into(),
        "-v".into(),
        format!("{}:/kit", kit.display()),
        "-e".into(),
        "WU_KIT=/kit".into(),
        "wu-host-tools:1".into(),
        "python".into(),
        "-m".into(),
        "wuhost.setup".into(),
    ];
    a.extend(cmd.iter().map(|s| s.to_string()));
    a
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn states_and_help() {
        let missing = detect(HostOs::Windows, &|_| None);
        assert_eq!(missing.state, DockerState::Missing);
        assert!(missing.help.contains("Docker Desktop") && missing.get_url == DESKTOP_URL);
        let stopped = detect(HostOs::Linux, &|a| Some(if a[0] == "version" { (1, "Cannot connect to the Docker daemon".into()) } else { (0, String::new()) }));
        assert_eq!(stopped.state, DockerState::Stopped);
        assert!(stopped.help.contains("systemctl") && stopped.get_url == ENGINE_URL);
        let ready = detect(HostOs::Mac, &|a| Some(if a[0] == "version" { (0, "27.3.1\n".into()) } else { (0, "Docker Compose version v2".into()) }));
        assert_eq!((ready.state, ready.version.as_deref()), (DockerState::Ready, Some("27.3.1")));
        let old = detect(HostOs::Mac, &|a| Some(if a[0] == "version" { (0, "19.0".into()) } else { (1, "unknown command".into()) }));
        assert_eq!(old.state, DockerState::NoCompose);
    }

    #[test]
    fn args_and_output() {
        let k = Path::new("/home/me/hostpack/kit");
        let a = compose_args(k, &["logs", "--tail", "200", "--no-color"]);
        assert_eq!(a[0..2], ["compose", "-f"]);
        assert!(a[2].ends_with("docker-compose.host.yml") && a.last().unwrap() == "--no-color");
        let t = tools_args(k, &["new-invite"]);
        assert_eq!(t[3], "/home/me/hostpack/kit:/kit");
        assert_eq!(t.last().unwrap(), "new-invite");
        assert_eq!(plain("\u{1b}[32mok\u{1b}[0m\r\nnext\u{7}"), "ok\nnext");
    }

    #[cfg(unix)]
    #[test]
    fn capture_and_timeout() {
        assert!(run_capture("leyline-no-such-program-xyz", &[], None, Duration::from_secs(1)).is_none());
        let (c, out) = run_capture("sh", &["-c", "echo hi; echo err >&2; exit 3"], None, Duration::from_secs(5)).unwrap();
        assert_eq!((c, out.as_str()), (3, "hi\nerr\n"));
        let (c, _) = run_capture("sh", &["-c", "sleep 5"], None, Duration::from_millis(200)).unwrap();
        assert_eq!(c, -2);
    }
}
