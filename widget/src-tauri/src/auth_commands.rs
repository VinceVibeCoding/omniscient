//! Commands for the account (Google / GitHub / e-mail + password). The daemon does the
//! whole sign-in and keeps the tokens; this side only asks it to start, opens the browser
//! on the URL it returns (checked here first) and relays the e-mail form. A password goes
//! webview → Rust → daemon over the loopback and is never kept or echoed.

use crate::commands::{get, post};
use crate::state::AppState;
use reqwest::Url;
use serde_json::{json, Value};
use std::process::{Command, Stdio};
use tauri::State;

type CmdResult<T> = Result<T, String>;

const PROVIDERS: [&str; 2] = ["google", "github"];
const MODES: [&str; 2] = ["signin", "signup"];
const URL_MAX: usize = 2048;
const EMAIL_MAX: usize = 254;
const PASSWORD_MIN: usize = 8;
const PASSWORD_MAX: usize = 128;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// The URL the daemon wants the browser on: https (or the machine itself, for a local test
/// server), no embedded credentials, no control characters. Anything else is never opened.
pub fn validate_browser_url(raw: &str) -> CmdResult<Url> {
    if raw.is_empty() || raw.len() > URL_MAX || raw.chars().any(|c| c.is_control() || c.is_whitespace()) {
        return Err("Adresse de connexion invalide.".into());
    }
    let url = Url::parse(raw).map_err(|_| "Adresse de connexion invalide.".to_string())?;
    let local = matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "[::1]"));
    let scheme_ok = url.scheme() == "https" || (url.scheme() == "http" && local);
    if !scheme_ok || url.host_str().is_none() || !url.username().is_empty() || url.password().is_some() {
        return Err("Adresse de connexion refusée.".into());
    }
    Ok(url)
}

pub fn validate_provider(provider: &str) -> CmdResult<&str> {
    PROVIDERS.contains(&provider).then_some(provider).ok_or_else(|| "Fournisseur de connexion inconnu.".to_string())
}

/// mode ∈ {signin, signup}, a plausible e-mail, a password of 8–128 characters. The password
/// is never part of an error message.
pub fn validate_credentials<'a>(mode: &'a str, email: &'a str, password: &'a str) -> CmdResult<(&'a str, &'a str, &'a str)> {
    if !MODES.contains(&mode) {
        return Err("Action inconnue.".into());
    }
    let email_ok = !email.is_empty()
        && email.len() <= EMAIL_MAX
        && email.matches('@').count() == 1
        && !email.chars().any(|c| c.is_control() || c.is_whitespace());
    if !email_ok {
        return Err("Adresse e-mail invalide.".into());
    }
    let length = password.chars().count();
    if !(PASSWORD_MIN..=PASSWORD_MAX).contains(&length) || password.contains('\0') {
        return Err(format!("Le mot de passe doit faire {PASSWORD_MIN} à {PASSWORD_MAX} caractères."));
    }
    Ok((mode, email, password))
}

fn open_in_browser(url: &Url) -> CmdResult<()> {
    let target = url.as_str();
    #[cfg(windows)]
    let mut command = {
        use std::os::windows::process::CommandExt;
        let mut c = Command::new("rundll32");
        c.args(["url.dll,FileProtocolHandler", target]).creation_flags(CREATE_NO_WINDOW);
        c
    };
    #[cfg(not(windows))]
    let mut command = {
        let mut c = Command::new("xdg-open");
        c.arg(target);
        c
    };
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
        .map_err(|err| format!("Navigateur introuvable : {err}"))
}

#[tauri::command]
pub async fn auth_status(state: State<'_, AppState>) -> CmdResult<Value> {
    get(&state, &["auth"]).await
}

/// Starts a Google / GitHub sign-in: the daemon prepares it, the browser opens on it, and
/// the daemon announces the result (SSE `auth`). The URL is also returned, in case the
/// browser did not open.
#[tauri::command]
pub async fn auth_start(state: State<'_, AppState>, provider: String) -> CmdResult<Value> {
    let provider = validate_provider(&provider)?;
    let reply = post(&state, &["auth", "start"], &json!({ "provider": provider })).await?;
    let raw = reply.get("url").and_then(Value::as_str).ok_or("Réponse du démon invalide.")?;
    let url = validate_browser_url(raw)?;
    if let Err(err) = open_in_browser(&url) {
        eprintln!("omniscient: {err}");
    }
    Ok(json!({ "url": url.as_str(), "expires_in": reply.get("expires_in").cloned().unwrap_or(Value::Null) }))
}

#[tauri::command]
pub async fn auth_password(state: State<'_, AppState>, mode: String, email: String, password: String) -> CmdResult<Value> {
    let (mode, email, password) = validate_credentials(&mode, email.trim(), &password)?;
    post(&state, &["auth", "password"], &json!({ "mode": mode, "email": email, "password": password })).await
}

#[tauri::command]
pub async fn auth_signout(state: State<'_, AppState>) -> CmdResult<Value> {
    post(&state, &["auth", "signout"], &json!({})).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_safe_browser_urls_are_opened() {
        let ok = "https://abcdefgh.supabase.co/auth/v1/authorize?provider=google&redirect_to=http%3A%2F%2F127.0.0.1%3A7341%2Fauth%2Fcallback";
        assert!(validate_browser_url(ok).is_ok());
        assert!(validate_browser_url("http://127.0.0.1:18090/auth/v1/authorize?x=1").is_ok());
        for bad in [
            "",
            "javascript:alert(1)",
            "file:///C:/Windows/System32/calc.exe",
            "ms-msdt:/id",
            "http://evil.example/login",
            "https://user:pw@evil.example/",
            "https://a b.example/",
            "https://x.example/\n--help",
            "ftp://x.example/",
            "not a url",
        ] {
            assert!(validate_browser_url(bad).is_err(), "{bad:?}");
        }
        assert!(validate_browser_url(&format!("https://x.example/{}", "a".repeat(URL_MAX))).is_err());
    }

    #[test]
    fn providers_are_google_or_github() {
        assert!(validate_provider("google").is_ok() && validate_provider("github").is_ok());
        for bad in ["facebook", "", "Google", "google;x"] {
            assert!(validate_provider(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn credentials_are_checked_without_echoing_the_password() {
        assert!(validate_credentials("signin", "ana@example.com", "long-enough").is_ok());
        assert!(validate_credentials("signup", "ana@example.com", &"p".repeat(PASSWORD_MAX)).is_ok());
        for (mode, email, pw) in [
            ("hack", "ana@example.com", "long-enough"),
            ("signin", "", "long-enough"),
            ("signin", "no-at-sign", "long-enough"),
            ("signin", "a@b@c.d", "long-enough"),
            ("signin", "ana @example.com", "long-enough"),
            ("signin", "ana@example.com\nBcc: x", "long-enough"),
            ("signin", "ana@example.com", "short"),
            ("signin", "ana@example.com", ""),
            ("signin", "ana@example.com", &"p".repeat(PASSWORD_MAX + 1)),
            ("signin", "ana@example.com", "has\0nul-char"),
        ] {
            let err = validate_credentials(mode, email, pw).unwrap_err();
            assert!(!err.contains("long-enough") && !err.contains("short"), "{err}");
        }
        assert!(validate_credentials("signin", &format!("{}@x.io", "a".repeat(EMAIL_MAX)), "long-enough").is_err());
    }
}
