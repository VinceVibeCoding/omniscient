//! The pure part of reading a web page from the browser window: where things are on the
//! screen, which windows are browsers, how a window title or the address bar becomes the
//! page's title and address. No Windows API here, so it is unit-tested everywhere.

use serde::Serialize;
use std::collections::HashSet;

const HEADINGS_MAX: usize = 30;
const CONTROLS_MAX: usize = 50;
const TEXT_ITEM_MAX: usize = 100;
const URL_MAX: usize = 2048;
/// Items closer than this (px) on the same line with the same text count as one.
const DUPLICATE_BAND_PX: i32 = 40;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Rect {
    pub left: i32,
    pub top: i32,
    pub right: i32,
    pub bottom: i32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Heading,
    Link,
    Button,
    Field,
}

impl Kind {
    fn role(self) -> &'static str {
        match self {
            Kind::Heading => "heading",
            Kind::Link => "link",
            Kind::Button => "button",
            Kind::Field => "field",
        }
    }
}

#[derive(Clone, Debug)]
pub struct RawItem {
    pub kind: Kind,
    pub name: String,
    pub rect: Rect,
}

/// What the daemon's page context calls an outline item (`where` is a Rust keyword).
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct OutlineItem {
    pub role: &'static str,
    pub text: String,
    #[serde(rename = "where")]
    pub place: String,
}

/// Where `item` is relative to the visible part of the page (`view`), as short French text.
pub fn place(item: Rect, view: Rect) -> String {
    let width = f64::from((view.right - view.left).max(1));
    let height = f64::from((view.bottom - view.top).max(1));
    let top = f64::from(item.top - view.top);
    let bottom = f64::from(item.bottom - view.top);
    if bottom <= 0.0 {
        return "plus haut dans la page (hors de l'écran)".into();
    }
    if top >= height {
        let screens = ((top - height) / height).round().max(1.0);
        return format!("plus bas dans la page (à environ {screens} écran(s) sous l'écran visible)");
    }
    let cx = (f64::from(item.left + item.right) / 2.0 - f64::from(view.left)) / width;
    let cy = (top + bottom) / 2.0 / height;
    let row = if cy < 0.33 { "en haut" } else if cy > 0.66 { "en bas" } else { "au milieu" };
    let col = if cx < 0.33 { "à gauche" } else if cx > 0.66 { "à droite" } else { "au centre" };
    format!("visible, {row} {col}")
}

pub fn tidy(text: &str) -> String {
    let joined = text.split_whitespace().collect::<Vec<_>>().join(" ");
    joined.chars().take(TEXT_ITEM_MAX).collect()
}

/// One outline entry with what is needed to find it again on the screen (« Montrer »).
#[derive(Clone, Debug)]
pub struct Picked {
    pub kind: Kind,
    pub text: String,
    pub rect: Rect,
    pub place: String,
}

impl Picked {
    pub fn outline(&self) -> OutlineItem {
        OutlineItem { role: self.kind.role(), text: self.text.clone(), place: self.place.clone() }
    }
}

pub fn build_outline(items: &[RawItem], view: Rect) -> Vec<OutlineItem> {
    pick_outline(items, view).iter().map(Picked::outline).collect()
}

/// Headings first, then links / buttons / fields, each in page order, deduplicated and capped.
/// The position in the result is the element's number (#1, #2…) in the outline the model gets.
pub fn pick_outline(items: &[RawItem], view: Rect) -> Vec<Picked> {
    let mut seen: HashSet<(&'static str, String, i32)> = HashSet::new();
    let mut pick = |wanted: fn(Kind) -> bool, cap: usize| -> Vec<Picked> {
        let mut out = Vec::new();
        for item in items.iter().filter(|i| wanted(i.kind)) {
            let text = tidy(&item.name);
            let tiny = item.rect.right - item.rect.left < 2 || item.rect.bottom - item.rect.top < 2;
            if out.len() >= cap || text.is_empty() || tiny {
                continue;
            }
            let band = (item.rect.top - view.top) / DUPLICATE_BAND_PX;
            if !seen.insert((item.kind.role(), text.clone(), band)) {
                continue;
            }
            out.push(Picked { kind: item.kind, place: place(item.rect, view), text, rect: item.rect });
        }
        out
    };
    let mut outline = pick(|k| k == Kind::Heading, HEADINGS_MAX);
    outline.extend(pick(|k| k != Kind::Heading, CONTROLS_MAX));
    outline
}

/// Only Chromium-family browsers: their accessibility tree is the one this was built for.
pub fn browser_label(exe: &str) -> Option<&'static str> {
    match exe.to_ascii_lowercase().as_str() {
        "chrome.exe" => Some("Chrome"),
        "msedge.exe" => Some("Edge"),
        "brave.exe" => Some("Brave"),
        "vivaldi.exe" => Some("Vivaldi"),
        "opera.exe" => Some("Opera"),
        "chromium.exe" => Some("Chromium"),
        _ => None,
    }
}

const BROWSER_WORDS: [&str; 6] = ["google chrome", "microsoft edge", "brave", "vivaldi", "opera", "chromium"];

/// « Page - Google Chrome » → « Page ».
pub fn clean_title(raw: &str) -> String {
    let title: String = raw.chars().filter(|c| *c != '\u{200b}').collect();
    for separator in [" - ", " – ", " — "] {
        if let Some(at) = title.rfind(separator) {
            let tail = title[at + separator.len()..].to_lowercase();
            if BROWSER_WORDS.iter().any(|word| tail.contains(word)) {
                return title[..at].trim().to_string();
            }
        }
    }
    title.trim().to_string()
}

fn is_local(host: &str) -> bool {
    let name = host.split(':').next().unwrap_or("");
    host.starts_with("[::1]")
        || name == "localhost"
        || name.starts_with("127.")
        || name.starts_with("192.168.")
        || name.starts_with("10.")
}

/// The address bar's text as an http(s) address without query or fragment, or None when it
/// is not an address (a search being typed, an internal page, an address with a login).
pub fn normalize_url(raw: &str) -> Option<String> {
    let raw = raw.trim();
    if raw.is_empty() || raw.len() > URL_MAX || raw.chars().any(|c| c.is_whitespace() || c.is_control()) {
        return None;
    }
    let (scheme, rest) = match raw.split_once("://") {
        Some((s, r)) if s.eq_ignore_ascii_case("http") || s.eq_ignore_ascii_case("https") => (s.to_ascii_lowercase(), r),
        Some(_) => return None,
        None => (String::new(), raw),
    };
    let rest = rest.split(['?', '#']).next().unwrap_or("");
    let host = rest.split('/').next().unwrap_or("");
    if host.is_empty() || host.contains('@') || !(host.contains('.') || host.contains(':') || host == "localhost") {
        return None;
    }
    let scheme = match (scheme.as_str(), is_local(host)) {
        ("", true) => "http".to_string(),
        ("", false) => "https".to_string(),
        _ => scheme,
    };
    Some(format!("{scheme}://{rest}"))
}

// ---- picture of the window: pixel and text helpers (no Windows API) ----------------------------

/// Windows gives blue-green-red-alpha rows; JPEG wants red-green-blue.
pub fn bgra_to_rgb(bgra: &[u8]) -> Vec<u8> {
    bgra.chunks_exact(4).flat_map(|px| [px[2], px[1], px[0]]).collect()
}

/// Shrinks an RGB picture so its longest side is at most `max_edge` (average of each block of
/// source pixels: text stays readable). A picture already small enough is returned as is.
pub fn downscale_rgb(rgb: &[u8], width: usize, height: usize, max_edge: usize) -> (Vec<u8>, usize, usize) {
    let longest = width.max(height);
    if longest <= max_edge || width == 0 || height == 0 {
        return (rgb.to_vec(), width, height);
    }
    let new_w = (width * max_edge / longest).max(1);
    let new_h = (height * max_edge / longest).max(1);
    let mut out = Vec::with_capacity(new_w * new_h * 3);
    for y in 0..new_h {
        let (y0, y1) = (y * height / new_h, ((y + 1) * height / new_h).max(y * height / new_h + 1));
        for x in 0..new_w {
            let (x0, x1) = (x * width / new_w, ((x + 1) * width / new_w).max(x * width / new_w + 1));
            let mut sum = [0u32; 3];
            for sy in y0..y1.min(height) {
                for sx in x0..x1.min(width) {
                    let at = (sy * width + sx) * 3;
                    for (c, total) in sum.iter_mut().enumerate() {
                        *total += u32::from(rgb[at + c]);
                    }
                }
            }
            let count = ((y1.min(height) - y0) * (x1.min(width) - x0)).max(1) as u32;
            out.extend(sum.iter().map(|total| (total / count) as u8));
        }
    }
    (out, new_w, new_h)
}

const BASE64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/// Standard base64 with padding (what the daemon decodes).
pub fn base64_encode(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let n = (u32::from(chunk[0]) << 16) | (u32::from(*chunk.get(1).unwrap_or(&0)) << 8) | u32::from(*chunk.get(2).unwrap_or(&0));
        out.push(BASE64[(n >> 18) as usize & 63] as char);
        out.push(BASE64[(n >> 12) as usize & 63] as char);
        out.push(if chunk.len() > 1 { BASE64[(n >> 6) as usize & 63] as char } else { '=' });
        out.push(if chunk.len() > 2 { BASE64[n as usize & 63] as char } else { '=' });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    const VIEW: Rect = Rect { left: 0, top: 100, right: 1000, bottom: 700 };

    fn at(left: i32, top: i32, right: i32, bottom: i32) -> Rect {
        Rect { left, top, right, bottom }
    }

    fn item(kind: Kind, name: &str, rect: Rect) -> RawItem {
        RawItem { kind, name: name.into(), rect }
    }

    #[test]
    fn says_where_a_visible_item_is() {
        assert_eq!(place(at(800, 110, 950, 150), VIEW), "visible, en haut à droite");
        assert_eq!(place(at(10, 650, 100, 690), VIEW), "visible, en bas à gauche");
        assert_eq!(place(at(450, 380, 550, 420), VIEW), "visible, au milieu au centre");
    }

    #[test]
    fn says_when_an_item_is_off_screen() {
        assert!(place(at(0, 1900, 200, 1930), VIEW).starts_with("plus bas dans la page (à environ 2 écran(s)"));
        assert!(place(at(0, 20, 200, 60), VIEW).starts_with("plus haut dans la page"));
    }

    #[test]
    fn outline_puts_headings_first_and_drops_noise() {
        let items = vec![
            item(Kind::Button, "Payer", at(800, 110, 950, 150)),
            item(Kind::Heading, "Votre panier", at(20, 200, 400, 240)),
            item(Kind::Link, "  ", at(0, 300, 50, 320)),      // no text
            item(Kind::Link, "Accueil", at(0, 300, 1, 320)),   // too thin
            item(Kind::Link, "Accueil", at(0, 300, 60, 320)),
            item(Kind::Link, "Accueil", at(70, 305, 130, 322)), // same line, same text
        ];
        let out = build_outline(&items, VIEW);
        let roles: Vec<_> = out.iter().map(|i| (i.role, i.text.as_str())).collect();
        assert_eq!(roles, [("heading", "Votre panier"), ("button", "Payer"), ("link", "Accueil")]);
        assert_eq!(out[1].place, "visible, en haut à droite");
    }

    #[test]
    fn outline_is_capped_and_texts_are_short() {
        let many: Vec<_> = (0..200).map(|i| item(Kind::Link, &format!("lien {i}"), at(0, 120 + i * 50, 80, 140 + i * 50))).collect();
        assert_eq!(build_outline(&many, VIEW).len(), CONTROLS_MAX);
        let long = vec![item(Kind::Button, &"x ".repeat(300), at(0, 120, 80, 140))];
        assert!(build_outline(&long, VIEW)[0].text.chars().count() <= TEXT_ITEM_MAX);
    }

    #[test]
    fn only_chromium_browsers_are_read() {
        assert_eq!(browser_label("chrome.exe"), Some("Chrome"));
        assert_eq!(browser_label("MSEdge.exe"), Some("Edge"));
        assert_eq!(browser_label("outlook.exe"), None);
        assert_eq!(browser_label("keepass.exe"), None);
    }

    #[test]
    fn the_browser_name_is_removed_from_the_title() {
        assert_eq!(clean_title("Panier - Google Chrome"), "Panier");
        assert_eq!(clean_title("Mon - site - Microsoft\u{200b} Edge"), "Mon - site");
        assert_eq!(clean_title("Panier"), "Panier");
        assert_eq!(clean_title("Rapport - Q3"), "Rapport - Q3");
    }

    #[test]
    fn base64_matches_the_standard_vectors() {
        assert_eq!(base64_encode(b""), "");
        assert_eq!(base64_encode(b"f"), "Zg==");
        assert_eq!(base64_encode(b"fo"), "Zm8=");
        assert_eq!(base64_encode(b"foo"), "Zm9v");
        assert_eq!(base64_encode(b"foobar"), "Zm9vYmFy");
        assert_eq!(base64_encode(&[0xff, 0xd8, 0xff]), "/9j/");
    }

    #[test]
    fn windows_pixels_become_rgb() {
        assert_eq!(bgra_to_rgb(&[1, 2, 3, 255, 10, 20, 30, 255]), [3, 2, 1, 30, 20, 10]);
    }

    #[test]
    fn a_big_picture_is_averaged_down_and_a_small_one_is_left_alone() {
        let small = vec![9u8; 4 * 2 * 3];
        assert_eq!(downscale_rgb(&small, 4, 2, 100), (small.clone(), 4, 2));
        // 4x2 picture, left half black, right half white, shrunk to 2x1: one black and one white pixel
        let mut rgb = Vec::new();
        for _ in 0..2 {
            rgb.extend([0u8; 6]);
            rgb.extend([255u8; 6]);
        }
        let (out, w, h) = downscale_rgb(&rgb, 4, 2, 2);
        assert_eq!((w, h), (2, 1));
        assert_eq!(out, [0, 0, 0, 255, 255, 255]);
        let (_, w, h) = downscale_rgb(&vec![0u8; 3000 * 1500 * 3], 3000, 1500, 1280);
        assert_eq!((w, h), (1280, 640));
    }

    #[test]
    fn the_address_bar_becomes_a_clean_address() {
        assert_eq!(normalize_url("example.com/panier?token=abc#x").as_deref(), Some("https://example.com/panier"));
        assert_eq!(normalize_url("http://example.com/a").as_deref(), Some("http://example.com/a"));
        assert_eq!(normalize_url("127.0.0.1:8099").as_deref(), Some("http://127.0.0.1:8099"));
        assert_eq!(normalize_url("localhost:3000/x").as_deref(), Some("http://localhost:3000/x"));
        for not_an_address in ["", "recette de crêpes", "chrome://settings", "https://user:pw@host.com/", "motseul", "file:///C:/x"] {
            assert_eq!(normalize_url(not_an_address), None, "{not_an_address}");
        }
    }
}
