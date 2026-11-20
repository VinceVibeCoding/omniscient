//! Widget settings: the daemon URL, whether the widget may start the daemon in WSL
//! (and from which Omniscient folder), and whether autostart was set up once. Stored as JSON in the app config dir (per
//! Windows user, %APPDATA%). The widget token is NOT a setting: it lives in the Windows
//! Credential Manager (vault.rs). An older settings.json that still holds a token or a
//! token command is rewritten without them on start.

use reqwest::Url;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::path::Path;

pub const DEFAULT_URL: &str = "http://127.0.0.1:7341";
const FILE_NAME: &str = "settings.json";
const LOOPBACK_HOSTS: [&str; 3] = ["127.0.0.1", "localhost", "[::1]"];
const TOKEN_MIN: usize = 16;
const TOKEN_MAX: usize = 256;
const LEGACY_SECRETS: [&str; 3] = ["token", "token_command", "wsl_distro"];

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub daemon_url: String,
    /// Start `omniscient group serve` in WSL when the daemon does not answer.
    pub start_daemon: bool,
    /// The Omniscient folder in WSL (`~/…` or `/…`), where the daemon is started.
    pub wsl_home: String,
    /// Launch at Windows login was switched on once (first run); the owner may undo it.
    pub autostart_init: bool,
    /// The first-run assistant (pairing, AI provider, look) was finished or skipped.
    pub wizard_done: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            daemon_url: DEFAULT_URL.to_string(),
            start_daemon: false,
            wsl_home: String::new(),
            autostart_init: false,
            wizard_done: false,
        }
    }
}

impl Settings {
    /// A normalised copy, or a French error naming the bad field.
    pub fn validated(&self) -> Result<Settings, String> {
        let wsl_home = validate_wsl_home(&self.wsl_home)?;
        if self.start_daemon && wsl_home.is_empty() {
            return Err("Indiquez le dossier Omniscient dans WSL pour démarrer le démon.".into());
        }
        Ok(Settings {
            daemon_url: validate_url(&self.daemon_url)?,
            start_daemon: self.start_daemon,
            wsl_home,
            autostart_init: self.autostart_init,
            wizard_done: self.wizard_done,
        })
    }
}

const WSL_HOME_MAX: usize = 512;

/// A Linux folder: empty, `~`, `~/…` or absolute; no `..`, no control or quote characters.
/// It reaches the daemon launcher as one argv entry, never through a shell string.
pub fn validate_wsl_home(raw: &str) -> Result<String, String> {
    let path = raw.trim();
    if path.is_empty() {
        return Ok(String::new());
    }
    let rooted = path == "~" || path.starts_with("~/") || path.starts_with('/');
    let bad_char = path.chars().any(|c| c.is_control() || matches!(c, '"' | '\'' | '`' | '$' | '\\'));
    let dotdot = path.split('/').any(|part| part == "..");
    if !rooted || bad_char || dotdot || path.chars().count() > WSL_HOME_MAX {
        return Err("Dossier WSL invalide : utilisez ~/… ou /… (sans « .. »).".into());
    }
    Ok(path.trim_end_matches('/').to_string())
}

/// What `load` found: the settings, and whether the file still held legacy secrets.
pub struct Loaded {
    pub settings: Settings,
    pub legacy: bool,
}

/// Only plain HTTP on the loopback interface: the token must never leave the machine.
pub fn validate_url(raw: &str) -> Result<String, String> {
    let raw = raw.trim();
    let url = Url::parse(raw).map_err(|_| format!("Adresse du démon invalide : « {raw} »."))?;
    let host = url.host_str().unwrap_or_default();
    if url.scheme() != "http" || !LOOPBACK_HOSTS.contains(&host) {
        return Err("L'adresse du démon doit être http://127.0.0.1:<port> ou http://localhost:<port>.".into());
    }
    if !url.username().is_empty() || url.password().is_some() || url.query().is_some() {
        return Err("L'adresse du démon ne doit contenir ni identifiants ni paramètres.".into());
    }
    if url.path() != "/" {
        return Err("L'adresse du démon ne doit pas contenir de chemin.".into());
    }
    Ok(raw.trim_end_matches('/').to_string())
}

/// A widget token as the daemon mints it (secrets.token_urlsafe).
pub fn validate_token(raw: &str) -> Result<String, String> {
    let token = raw.trim();
    let ok_chars = token.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_');
    if !ok_chars || !(TOKEN_MIN..=TOKEN_MAX).contains(&token.len()) {
        return Err("Jeton reçu du démon invalide : recommencez le couplage.".into());
    }
    Ok(token.to_string())
}

fn has_legacy_secret(value: &Value) -> bool {
    match value.as_object() {
        Some(map) => LEGACY_SECRETS.iter().any(|key| map.contains_key(*key)),
        None => false,
    }
}

/// Missing file → defaults; unreadable or invalid file → French error.
pub fn load(dir: &Path) -> Result<Loaded, String> {
    let path = dir.join(FILE_NAME);
    let text = match fs::read_to_string(&path) {
        Ok(text) => text,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
            return Ok(Loaded { settings: Settings::default(), legacy: false });
        }
        Err(err) => return Err(format!("Réglages illisibles : {err}")),
    };
    let value: Value = serde_json::from_str(&text).map_err(|err| format!("Réglages corrompus : {err}"))?;
    let legacy = has_legacy_secret(&value);
    let parsed: Settings = serde_json::from_value(value).map_err(|err| format!("Réglages corrompus : {err}"))?;
    Ok(Loaded { settings: parsed.validated()?, legacy })
}

/// Atomic write (temp file + rename) of validated settings.
pub fn save(dir: &Path, settings: &Settings) -> Result<(), String> {
    fs::create_dir_all(dir).map_err(|err| format!("Dossier des réglages inaccessible : {err}"))?;
    let text = serde_json::to_string_pretty(settings).map_err(|err| format!("Réglages non sérialisables : {err}"))?;
    let tmp = dir.join(format!(".{FILE_NAME}.tmp"));
    fs::write(&tmp, text).map_err(|err| format!("Écriture des réglages impossible : {err}"))?;
    fs::rename(&tmp, dir.join(FILE_NAME)).map_err(|err| format!("Écriture des réglages impossible : {err}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_dir(name: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!("omniscient-test-{name}-{}", std::process::id()))
    }

    #[test]
    fn wsl_home_is_a_plain_linux_folder() {
        assert_eq!(validate_wsl_home("").unwrap(), "");
        assert_eq!(validate_wsl_home(" ~/projects/omniscient/ ").unwrap(), "~/projects/omniscient");
        assert_eq!(validate_wsl_home("/srv/home").unwrap(), "/srv/home");
        assert_eq!(validate_wsl_home("~").unwrap(), "~");
        for bad in ["projects", "C:\\x", "~/a/../b", "/a$(x)", "/a`x`", "/a'b", "/a\nb", "~user/x"] {
            assert!(validate_wsl_home(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn starting_the_daemon_needs_a_folder() {
        let on = Settings { start_daemon: true, ..Settings::default() };
        assert!(on.validated().is_err());
        let ok = Settings { start_daemon: true, wsl_home: "~/omni".into(), ..Settings::default() };
        assert_eq!(ok.validated().unwrap().wsl_home, "~/omni");
    }

    #[test]
    fn older_files_load_with_new_defaults() {
        let parsed: Settings = serde_json::from_str(r#"{"daemon_url":"http://127.0.0.1:7341"}"#).unwrap();
        assert!(!parsed.start_daemon && !parsed.autostart_init && parsed.wsl_home.is_empty());
        assert!(!parsed.wizard_done);
    }

    #[test]
    fn accepts_loopback_urls_and_strips_trailing_slash() {
        assert_eq!(validate_url("http://127.0.0.1:7341/").unwrap(), "http://127.0.0.1:7341");
        assert!(validate_url("http://localhost:7341").is_ok());
        assert!(validate_url("http://[::1]:7341").is_ok());
    }

    #[test]
    fn rejects_remote_or_tls_or_paths() {
        assert!(validate_url("http://example.com:7341").is_err());
        assert!(validate_url("https://127.0.0.1:7341").is_err());
        assert!(validate_url("http://127.0.0.1:7341/api").is_err());
        assert!(validate_url("http://user:pw@127.0.0.1:7341").is_err());
    }

    #[test]
    fn token_rules() {
        assert!(validate_token("abcDEF0123456789_-xyz").is_ok());
        assert!(validate_token("").is_err());
        assert!(validate_token("short").is_err());
        assert!(validate_token("has space in the middle!!").is_err());
    }

    #[test]
    fn save_then_load_round_trips_without_any_secret() {
        let dir = temp_dir("roundtrip");
        let settings = Settings { daemon_url: "http://localhost:7341".into(), ..Settings::default() };
        save(&dir, &settings).unwrap();
        let text = fs::read_to_string(dir.join(FILE_NAME)).unwrap();
        assert!(!text.contains("token"));
        let loaded = load(&dir).unwrap();
        assert_eq!(loaded.settings, settings);
        assert!(!loaded.legacy);
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn legacy_token_files_are_flagged_for_rewrite() {
        let dir = temp_dir("legacy");
        fs::create_dir_all(&dir).unwrap();
        let old = r#"{"daemon_url": "http://127.0.0.1:7341", "token": "abcDEF0123456789_-xyz",
                      "wsl_distro": "", "token_command": "omniscient group token"}"#;
        fs::write(dir.join(FILE_NAME), old).unwrap();
        let loaded = load(&dir).unwrap();
        assert!(loaded.legacy);
        save(&dir, &loaded.settings).unwrap();
        assert!(!fs::read_to_string(dir.join(FILE_NAME)).unwrap().contains("abcDEF"));
        assert!(!load(&dir).unwrap().legacy);
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn missing_file_gives_defaults() {
        let loaded = load(&temp_dir("missing")).unwrap();
        assert_eq!(loaded.settings, Settings::default());
    }
}
