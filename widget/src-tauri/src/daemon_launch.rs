//! Starting the daemon from the widget: when the owner allows it (setting `start_daemon`)
//! and nothing answers on the daemon's port, the widget runs
//! `wsl.exe --exec bash -lc 'cd … && exec omniscient group serve'` hidden, and stops it
//! when the widget quits. The folder is passed as a separate argument ("$1"), never
//! spliced into the script, so a setting can't inject a command. Holding the wsl.exe
//! process also keeps the WSL distribution alive while the widget runs.

use crate::settings::Settings;
use crate::state::{lock, AppState};
use reqwest::Url;
use std::net::{SocketAddr, TcpStream};
use std::process::{Command, Stdio};
use std::time::Duration;
use tauri::{AppHandle, Manager};

const PROBE_TIMEOUT: Duration = Duration::from_millis(600);
/// `$1` is the folder; a leading `~` is expanded by bash itself, not by us.
const SCRIPT: &str = r#"cd -- "${1/#\~/$HOME}" && exec omniscient group serve"#;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// The argv after `wsl.exe` for a validated folder.
pub fn wsl_args(home: &str) -> Vec<String> {
    ["--exec", "bash", "-lc", SCRIPT, "omnigroup-daemon", home].iter().map(|s| s.to_string()).collect()
}

/// The loopback address the daemon URL points at (settings only allow loopback).
pub fn probe_addr(daemon_url: &str) -> Option<SocketAddr> {
    let url = Url::parse(daemon_url).ok()?;
    let port = url.port_or_known_default()?;
    Some(SocketAddr::from(([127, 0, 0, 1], port)))
}

fn answering(daemon_url: &str) -> bool {
    probe_addr(daemon_url).is_some_and(|addr| TcpStream::connect_timeout(&addr, PROBE_TIMEOUT).is_ok())
}

fn our_child_running(state: &AppState) -> bool {
    let mut child = lock(&state.daemon_child);
    match child.as_mut().map(|c| c.try_wait()) {
        Some(Ok(None)) => true,
        Some(Ok(Some(status))) => {
            eprintln!("omnigroup: the daemon started by the widget exited ({status})");
            *child = None;
            false
        }
        Some(Err(err)) => {
            eprintln!("omnigroup: daemon process unreadable: {err}");
            false
        }
        None => false,
    }
}

fn spawn(home: &str) -> std::io::Result<std::process::Child> {
    let mut command = Command::new("wsl.exe");
    command.args(wsl_args(home)).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command.spawn()
}

/// Starts the daemon when allowed and not already answering. Blocking (probe): call it
/// off the main thread.
pub fn ensure(app: &AppHandle) {
    let state = app.state::<AppState>();
    let settings: Settings = lock(&state.settings).clone();
    if !settings.start_daemon || settings.wsl_home.is_empty() || our_child_running(&state) {
        return;
    }
    if answering(&settings.daemon_url) {
        return; // started elsewhere (systemd, a terminal): leave it alone
    }
    match spawn(&settings.wsl_home) {
        Ok(child) => *lock(&state.daemon_child) = Some(child),
        Err(err) => eprintln!("omnigroup: daemon not started: {err}"),
    }
}

/// Same as `ensure`, on a blocking worker thread.
pub fn ensure_later(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn_blocking(move || ensure(&app));
}

/// Widget quitting: stop the daemon it started (none started → nothing to do).
pub fn stop(app: &AppHandle) {
    let state = app.state::<AppState>();
    let Some(mut child) = lock(&state.daemon_child).take() else { return };
    if let Err(err) = child.kill() {
        eprintln!("omnigroup: daemon not stopped: {err}");
    }
    let _ = child.wait(); // reap; its exit status is irrelevant once killed
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn folder_is_its_own_argument() {
        let args = wsl_args("~/a b; rm -rf /");
        assert_eq!(args[..3], ["--exec", "bash", "-lc"]);
        assert_eq!(args[3], SCRIPT);
        assert_eq!(args.last().unwrap(), "~/a b; rm -rf /");
        assert!(!args[3].contains("rm"));
    }

    #[test]
    fn probes_the_loopback_port_of_the_url() {
        assert_eq!(probe_addr("http://127.0.0.1:7341"), Some(SocketAddr::from(([127, 0, 0, 1], 7341))));
        assert_eq!(probe_addr("http://localhost:9000"), Some(SocketAddr::from(([127, 0, 0, 1], 9000))));
        assert_eq!(probe_addr("not a url"), None);
    }
}
