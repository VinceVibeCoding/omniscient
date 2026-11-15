//! Where the owner dragged the widget. Stored as the window's bottom-right corner (the
//! "anchor", physical pixels) in `window.json` next to settings.json, so the pill and the
//! taller panel both grow from the same corner. No anchor = docked in the screen corner.
//! The same file keeps the widget's size factor (`scale`, set with the resize grip).

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

const FILE_NAME: &str = "window.json";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}

#[derive(Debug, Default, Serialize, Deserialize)]
struct Stored {
    anchor: Option<[i32; 2]>,
    #[serde(default)]
    scale: Option<f64>,
}

/// What window.json holds: where the widget was dragged and how big it was made.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Placement {
    pub anchor: Option<(i32, i32)>,
    pub scale: Option<f64>,
}

/// Top-left position of a `size` window whose bottom-right corner sits on `anchor`
/// (or `margin` pixels inside the work area's corner when there is none), kept fully
/// inside `area`.
pub fn place(area: Rect, size: (i32, i32), anchor: Option<(i32, i32)>, margin: i32) -> (i32, i32) {
    let (width, height) = size;
    let right = area.x + area.width;
    let bottom = area.y + area.height;
    let (ax, ay) = anchor.unwrap_or((right - margin, bottom - margin));
    let x = (ax - width).clamp(area.x, (right - width).max(area.x));
    let y = (ay - height).clamp(area.y, (bottom - height).max(area.y));
    (x, y)
}

/// Top-left of a `size` popup opened at `cursor`: below-right of it, flipped left / up
/// when it would leave `area`, and always kept inside it.
pub fn popup_origin(area: Rect, size: (i32, i32), cursor: (i32, i32)) -> (i32, i32) {
    let (width, height) = size;
    let (cx, cy) = cursor;
    let right = area.x + area.width;
    let bottom = area.y + area.height;
    let x = if cx + width > right { cx - width } else { cx };
    let y = if cy + height > bottom { cy - height } else { cy };
    let x = x.clamp(area.x, (right - width).max(area.x));
    let y = y.clamp(area.y, (bottom - height).max(area.y));
    (x, y)
}

/// True when `point` lies inside `area` (used to pick the monitor of an anchor).
pub fn contains(area: Rect, point: (i32, i32)) -> bool {
    let (px, py) = point;
    px >= area.x && px <= area.x + area.width && py >= area.y && py <= area.y + area.height
}

/// The saved placement; a missing or unreadable file means "docked, default size".
pub fn load(dir: &Path) -> Placement {
    let Ok(text) = fs::read_to_string(dir.join(FILE_NAME)) else { return Placement::default() };
    match serde_json::from_str::<Stored>(&text) {
        Ok(stored) => Placement { anchor: stored.anchor.map(|[x, y]| (x, y)), scale: stored.scale },
        Err(err) => {
            eprintln!("omnigroup: window.json ignored: {err}");
            Placement::default()
        }
    }
}

/// Atomic write (temp file + rename); `anchor: None` forgets the position.
pub fn save(dir: &Path, placement: Placement) -> Result<(), String> {
    fs::create_dir_all(dir).map_err(|err| format!("Dossier des réglages inaccessible : {err}"))?;
    let stored = Stored { anchor: placement.anchor.map(|(x, y)| [x, y]), scale: placement.scale };
    let text = serde_json::to_string(&stored).map_err(|err| format!("Position non sérialisable : {err}"))?;
    let tmp = dir.join(format!(".{FILE_NAME}.tmp"));
    fs::write(&tmp, text).map_err(|err| format!("Écriture de la position impossible : {err}"))?;
    fs::rename(&tmp, dir.join(FILE_NAME)).map_err(|err| format!("Écriture de la position impossible : {err}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    const AREA: Rect = Rect { x: 0, y: 0, width: 1920, height: 1032 };

    #[test]
    fn popup_opens_below_right_of_the_cursor() {
        assert_eq!(popup_origin(AREA, (240, 320), (600, 300)), (600, 300));
    }

    #[test]
    fn popup_flips_near_the_right_and_bottom_edges() {
        // The OSD sits in the bottom-right corner: the menu opens up and to the left.
        assert_eq!(popup_origin(AREA, (240, 320), (1800, 1000)), (1560, 680));
    }

    #[test]
    fn popup_stays_inside_a_small_area() {
        let small = Rect { x: 100, y: 100, width: 200, height: 200 };
        assert_eq!(popup_origin(small, (240, 320), (150, 150)), (100, 100));
    }

    #[test]
    fn docks_in_the_corner_without_anchor() {
        assert_eq!(place(AREA, (236, 60), None, 12), (1672, 960));
    }

    #[test]
    fn bottom_right_follows_the_anchor() {
        assert_eq!(place(AREA, (236, 60), Some((800, 500)), 12), (564, 440));
        assert_eq!(place(AREA, (360, 520), Some((800, 500)), 12), (440, 0));
    }

    #[test]
    fn stays_inside_the_work_area() {
        assert_eq!(place(AREA, (236, 60), Some((100, 30)), 12), (0, 0));
        assert_eq!(place(AREA, (236, 60), Some((5000, 5000)), 12), (1684, 972));
        let second = Rect { x: 1920, y: 0, width: 1280, height: 1024 };
        assert_eq!(place(second, (236, 60), Some((1950, 40)), 12), (1920, 0));
    }

    #[test]
    fn contains_checks_bounds() {
        assert!(contains(AREA, (10, 10)));
        assert!(!contains(AREA, (2000, 10)));
    }

    #[test]
    fn save_load_and_forget() {
        let dir = std::env::temp_dir().join(format!("omnigroup-pos-{}", std::process::id()));
        let none = Placement::default();
        assert_eq!(load(&dir), none);
        let both = Placement { anchor: Some((900, 700)), scale: Some(1.25) };
        save(&dir, both).unwrap();
        assert_eq!(load(&dir), both);
        save(&dir, Placement { anchor: None, scale: Some(1.25) }).unwrap();
        assert_eq!(load(&dir), Placement { anchor: None, scale: Some(1.25) });
        fs::write(dir.join(FILE_NAME), r#"{"anchor":[1,2]}"#).unwrap(); // 0.1.1 file: no scale
        assert_eq!(load(&dir), Placement { anchor: Some((1, 2)), scale: None });
        fs::write(dir.join(FILE_NAME), "not json").unwrap();
        assert_eq!(load(&dir), none);
        fs::remove_dir_all(&dir).unwrap();
    }
}
