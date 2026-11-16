//! Commands for extensions (declarative packs of commands, themes, workflows and provider
//! presets that the daemon loads from the home). The daemon owns every rule; this side only
//! checks what goes into a URL or a body, so nothing odd reaches the loopback client.

use crate::commands::{delete, get, post, put};
use crate::state::AppState;
use serde_json::{json, Value};
use tauri::State;

type CmdResult<T> = Result<T, String>;

const EXT_ID_MAX: usize = 40;
const COMMAND_MAX: usize = 30;
pub const ARGS_MAX: usize = 2000;

/// An extension id: `[a-z0-9][a-z0-9-]{0,39}`.
pub fn validate_ext_id(id: &str) -> CmdResult<&str> {
    let mut chars = id.chars();
    let first_ok = chars.next().is_some_and(|c| c.is_ascii_lowercase() || c.is_ascii_digit());
    let rest_ok = chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-');
    if !first_ok || !rest_ok || id.len() > EXT_ID_MAX {
        return Err("Identifiant d'extension invalide.".into());
    }
    Ok(id)
}

/// A command or workflow name: `[a-z][a-z0-9-]{0,29}`.
pub fn validate_command(name: &str) -> CmdResult<&str> {
    let mut chars = name.chars();
    let first_ok = chars.next().is_some_and(|c| c.is_ascii_lowercase());
    let rest_ok = chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-');
    if !first_ok || !rest_ok || name.len() > COMMAND_MAX {
        return Err("Nom de commande invalide.".into());
    }
    Ok(name)
}

/// The arguments typed after the command: at most ARGS_MAX characters.
pub fn validate_args(args: &str) -> CmdResult<&str> {
    if args.chars().count() > ARGS_MAX {
        return Err(format!("Arguments trop longs ({ARGS_MAX} caractères max)."));
    }
    Ok(args)
}

#[tauri::command]
pub async fn ext_list(state: State<'_, AppState>) -> CmdResult<Value> {
    get(&state, &["extensions"]).await
}

#[tauri::command]
pub async fn ext_reload(state: State<'_, AppState>) -> CmdResult<Value> {
    post(&state, &["extensions", "reload"], &json!({})).await
}

#[tauri::command]
pub async fn ext_set_enabled(state: State<'_, AppState>, id: String, enabled: bool) -> CmdResult<Value> {
    put(&state, &["extensions", validate_ext_id(&id)?], &json!({ "enabled": enabled })).await
}

#[tauri::command]
pub async fn ext_remove(state: State<'_, AppState>, id: String) -> CmdResult<Value> {
    delete(&state, &["extensions", validate_ext_id(&id)?]).await
}

#[tauri::command]
pub async fn ext_expand(state: State<'_, AppState>, command: String, args: String) -> CmdResult<Value> {
    let body = json!({ "command": validate_command(&command)?, "args": validate_args(&args)? });
    post(&state, &["extensions", "expand"], &body).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extension_ids_follow_the_daemon_pattern() {
        assert!(validate_ext_id("resume-page").is_ok());
        assert!(validate_ext_id("9lives").is_ok());
        assert!(validate_ext_id(&"a".repeat(40)).is_ok());
        for bad in ["", "-x", "Abc", "a_b", "a/b", "../x", "a b", "é"] {
            assert!(validate_ext_id(bad).is_err(), "{bad:?}");
        }
        assert!(validate_ext_id(&"a".repeat(41)).is_err());
    }

    #[test]
    fn command_names_start_with_a_letter() {
        assert!(validate_command("resume").is_ok());
        assert!(validate_command("a1-b").is_ok());
        assert!(validate_command(&"a".repeat(30)).is_ok());
        for bad in ["", "1a", "-a", "A", "a_b", "a/b", "a?b", "a b"] {
            assert!(validate_command(bad).is_err(), "{bad:?}");
        }
        assert!(validate_command(&"a".repeat(31)).is_err());
    }

    #[test]
    fn arguments_are_bounded_by_characters() {
        assert!(validate_args("").is_ok());
        assert!(validate_args(&"é".repeat(ARGS_MAX)).is_ok());
        assert!(validate_args(&"é".repeat(ARGS_MAX + 1)).is_err());
    }
}
