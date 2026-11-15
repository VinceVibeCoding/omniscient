//! Commands for the LLM providers (Claude Code by default, plus the ones the person adds):
//! list, save, remove and test. The API key goes webview → Rust → daemon over the loopback
//! only and is never stored here; the daemon keeps it write-only and answers with « has a
//! key » and the last 4 characters. Every input is validated here and again by the daemon.

use crate::client::validate_id;
use crate::commands::{daemon_for, get, post};
use crate::state::AppState;
use serde_json::{Map, Value};
use tauri::State;

type CmdResult<T> = Result<T, String>;

pub const KINDS: [&str; 4] = ["openai", "gemini", "anthropic", "openai-compatible"];
const ID_MAX: usize = 32;
const LABEL_MAX: usize = 60;
const MODEL_MAX: usize = 128;
const URL_MAX: usize = 512;
const KEY_MIN: usize = 8;
const KEY_MAX: usize = 512;

/// A provider id: lowercase letters, digits and dashes, starting with a letter or digit.
pub fn validate_provider_id(id: &str) -> CmdResult<&str> {
    let mut chars = id.chars();
    let first_ok = chars.next().is_some_and(|c| c.is_ascii_lowercase() || c.is_ascii_digit());
    let rest_ok = chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-');
    if !first_ok || !rest_ok || id.len() > ID_MAX {
        return Err("Identifiant de fournisseur invalide.".into());
    }
    Ok(id)
}

fn text<'a>(obj: &'a Map<String, Value>, key: &str) -> CmdResult<Option<&'a str>> {
    match obj.get(key) {
        None => Ok(None),
        Some(Value::String(s)) => Ok(Some(s.as_str())),
        Some(_) => Err(format!("Valeur invalide pour {key}.")),
    }
}

fn model_ok(model: &str) -> bool {
    let first = model.chars().next().is_some_and(|c| c.is_ascii_alphanumeric());
    first
        && model.len() <= MODEL_MAX
        && model.chars().all(|c| c.is_ascii_alphanumeric() || "._:/@+-".contains(c))
}

/// A provider patch from the webview: known keys, sane values; the key is never echoed in
/// an error message.
pub fn validate_provider_patch(patch: &Value) -> CmdResult<Value> {
    let obj = patch.as_object().ok_or("Réglage invalide.")?;
    if obj.is_empty() {
        return Err("Aucun réglage à changer.".into());
    }
    let mut clean = Map::new();
    for (key, value) in obj {
        match key.as_str() {
            "kind" => {
                let kind = text(obj, key)?.unwrap_or_default();
                if !KINDS.contains(&kind) {
                    return Err("Type de fournisseur inconnu.".into());
                }
            }
            "label" => {
                let label = text(obj, key)?.unwrap_or_default().trim();
                if label.is_empty() || label.chars().count() > LABEL_MAX || label.chars().any(char::is_control) {
                    return Err(format!("Nom invalide ({LABEL_MAX} caractères au plus)."));
                }
            }
            "model" => {
                let model = text(obj, key)?.unwrap_or_default();
                // "" = not chosen yet (the daemon lists the models once the key is tested).
                if !model.is_empty() && !model_ok(model) {
                    return Err("Modèle invalide : lettres, chiffres et . _ : / @ + - seulement.".into());
                }
            }
            "base_url" => {
                let url = text(obj, key)?.unwrap_or_default();
                if url.len() > URL_MAX || url.chars().any(|c| c.is_control() || c.is_whitespace()) {
                    return Err("Adresse invalide.".into());
                }
            }
            "api_key" => {
                let key_text = text(obj, key)?.unwrap_or_default();
                let visible = key_text.chars().all(|c| ('\u{21}'..='\u{7e}').contains(&c));
                if !visible || !(KEY_MIN..=KEY_MAX).contains(&key_text.len()) {
                    return Err("Clé invalide : 8 à 512 caractères visibles, sans espace.".into());
                }
            }
            "default" if value.is_boolean() => {}
            "default" => return Err("Valeur invalide pour default.".into()),
            _ => return Err(format!("Réglage inconnu : {key}")),
        }
        clean.insert(key.clone(), value.clone());
    }
    Ok(Value::Object(clean))
}

#[tauri::command]
pub async fn providers_list(state: State<'_, AppState>) -> CmdResult<Value> {
    get(&state, &["providers"]).await
}

#[tauri::command]
pub async fn provider_save(state: State<'_, AppState>, id: String, patch: Value) -> CmdResult<Value> {
    let id = validate_provider_id(&id)?;
    let body = validate_provider_patch(&patch)?;
    let app_state: &AppState = &state;
    let daemon = daemon_for(app_state)?;
    daemon.put(&["providers", id], &body).await.map_err(|err| err.message())
}

#[tauri::command]
pub async fn provider_remove(state: State<'_, AppState>, id: String) -> CmdResult<Value> {
    let id = validate_provider_id(&id)?;
    post(&state, &["providers", id, "remove"], &Value::Object(Map::new())).await
}

/// Proves the key and address work; the reply lists the models the key can use.
#[tauri::command]
pub async fn provider_test(state: State<'_, AppState>, id: String) -> CmdResult<Value> {
    // "claude-code" is the built-in provider: it has no saved key but can be tested.
    let id = if id == "claude-code" { id.as_str() } else { validate_provider_id(&id)? };
    let id = validate_id(id)?;
    post(&state, &["providers", id, "test"], &Value::Object(Map::new())).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn ids_are_plain_slugs() {
        assert!(validate_provider_id("gemini-2").is_ok());
        for bad in ["", "Gemini", "-x", "a b", "a/b", "../x", &"a".repeat(33)] {
            assert!(validate_provider_id(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn a_good_patch_passes_unchanged() {
        let ok = json!({
            "kind": "gemini", "label": "Mon Gemini", "model": "gemini-x",
            "base_url": "https://example.com/v1", "api_key": "sk-test-0123456789", "default": true
        });
        assert_eq!(validate_provider_patch(&ok).unwrap(), ok);
        let unchosen = json!({"kind": "openai", "model": "", "api_key": "sk-test-0123456789"});
        assert_eq!(validate_provider_patch(&unchosen).unwrap(), unchosen);
    }

    #[test]
    fn bad_patches_are_refused_without_echoing_the_key() {
        let bad = [
            json!({}),
            json!("x"),
            json!({"kind": "skynet"}),
            json!({"label": "  "}),
            json!({"label": "l".repeat(61)}),
            json!({"model": "bad model;"}),
            json!({"model": "-x"}),
            json!({"base_url": "https://a b"}),
            json!({"api_key": "short"}),
            json!({"api_key": "has a space in it 123"}),
            json!({"api_key": "k".repeat(600)}),
            json!({"api_key": 5}),
            json!({"default": "yes"}),
            json!({"token": "x"}),
        ];
        for patch in bad {
            assert!(validate_provider_patch(&patch).is_err(), "{patch}");
        }
        let err = validate_provider_patch(&json!({"api_key": "secret key with spaces"})).unwrap_err();
        assert!(!err.contains("secret"));
    }
}
