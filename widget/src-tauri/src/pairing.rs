//! Pairing with the daemon: the owner asks for a code (POST /pair/start, no credential),
//! reads the 6 digits on the Windows desktop, types them in the widget (POST /pair/finish).
//! The daemon returns a widget token once; it goes straight to the Windows vault.
//! No shell, no WSL command and no token command are involved any more.

pub const CLIENT_NAME: &str = "Omniscient (Windows)";
const CODE_DIGITS: usize = 6;

/// Six ASCII digits (spaces around are tolerated), or a French error.
pub fn validate_code(raw: &str) -> Result<String, String> {
    let code = raw.trim();
    if code.len() != CODE_DIGITS || !code.chars().all(|c| c.is_ascii_digit()) {
        return Err("Le code de couplage fait 6 chiffres.".into());
    }
    Ok(code.to_string())
}

const EMAIL_MAX: usize = 254;
const EMAIL_CODE_MIN: usize = 6;
const EMAIL_CODE_MAX: usize = 10;

/// A plausible e-mail address (the daemon and the account service check it for real).
pub fn validate_email(raw: &str) -> Result<String, String> {
    let email = raw.trim();
    let sane = email.len() <= EMAIL_MAX
        && !email.chars().any(|c| c.is_whitespace() || c.is_control())
        && email.split_once('@').is_some_and(|(local, domain)| !local.is_empty() && domain.contains('.') && !domain.contains('@'));
    if !sane {
        return Err("Adresse e-mail invalide.".into());
    }
    Ok(email.to_string())
}

/// The code received by e-mail: 6 to 10 ASCII digits (spaces around are tolerated).
pub fn validate_email_code(raw: &str) -> Result<String, String> {
    let code = raw.trim();
    if !(EMAIL_CODE_MIN..=EMAIL_CODE_MAX).contains(&code.len()) || !code.chars().all(|c| c.is_ascii_digit()) {
        return Err("Le code reçu par courriel est fait de chiffres (6 à 10).".into());
    }
    Ok(code.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn emails_are_plausible_addresses() {
        assert_eq!(validate_email(" ana@example.com ").unwrap(), "ana@example.com");
        for bad in ["", "ana", "ana@", "@example.com", "ana@example", "a b@example.com", "a@b@example.com"] {
            assert!(validate_email(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn email_codes_are_six_to_ten_digits() {
        assert_eq!(validate_email_code(" 123456 ").unwrap(), "123456");
        assert!(validate_email_code("12345").is_err());
        assert!(validate_email_code("12345678901").is_err());
        assert!(validate_email_code("12345a").is_err());
    }

    #[test]
    fn codes_are_six_ascii_digits() {
        assert_eq!(validate_code(" 042137 ").unwrap(), "042137");
        assert!(validate_code("42137").is_err());
        assert!(validate_code("0421378").is_err());
        assert!(validate_code("04213a").is_err());
        assert!(validate_code("０４２１３７").is_err()); // full-width digits
    }
}
