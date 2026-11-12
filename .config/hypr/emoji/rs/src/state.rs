//! What the picker remembers between runs: recent picks, favourites and the skin tone, in
//! ~/.local/state/hyprdots/emoji.json. Emoji are kept without their tone, so changing the tone changes them all.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

pub const RECENT_KEPT: usize = 40;

#[derive(Default, Serialize, Deserialize, Debug, PartialEq)]
#[serde(default)]
pub struct State {
    pub recent: Vec<String>,
    pub favourites: Vec<String>,
    /// 0 is the default yellow, 1 to 5 light to dark
    pub tone: usize,
}

pub fn path() -> PathBuf {
    let state = std::env::var_os("XDG_STATE_HOME").filter(|s| !s.is_empty()).map(PathBuf::from);
    let home = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/tmp"));
    state.unwrap_or_else(|| home.join(".local/state")).join("hyprdots/emoji.json")
}

impl State {
    /// A missing or damaged file starts afresh rather than stopping the picker.
    pub fn load(path: &Path) -> State {
        let mut state: State =
            fs::read_to_string(path).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or_default();
        if state.tone > 5 {
            state.tone = 0;
        }
        state
    }

    /// Written next to the file, then moved over it, so a crash never leaves half a file.
    pub fn save(&self, path: &Path) -> std::io::Result<()> {
        if let Some(dir) = path.parent() {
            fs::create_dir_all(dir)?;
        }
        let tmp = path.with_extension("json.new");
        fs::write(&tmp, serde_json::to_string_pretty(self)? + "\n")?;
        fs::rename(tmp, path)
    }

    pub fn picked(&mut self, emoji: &str) {
        self.recent.retain(|e| e != emoji);
        self.recent.insert(0, emoji.to_string());
        self.recent.truncate(RECENT_KEPT);
    }

    /// Adds or removes a favourite; true when it is now a favourite.
    pub fn toggle_favourite(&mut self, emoji: &str) -> bool {
        if let Some(i) = self.favourites.iter().position(|e| e == emoji) {
            self.favourites.remove(i);
            false
        } else {
            self.favourites.push(emoji.to_string());
            true
        }
    }

    pub fn is_favourite(&self, emoji: &str) -> bool {
        self.favourites.iter().any(|e| e == emoji)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("hyprdots-emoji-test-{}-{name}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        dir.join("state/emoji.json")
    }

    #[test]
    fn recent_is_newest_first_without_repeats() {
        let mut s = State::default();
        for e in ["a", "b", "a", "c"] {
            s.picked(e);
        }
        assert_eq!(s.recent, ["c", "a", "b"]);
        for i in 0..100 {
            s.picked(&i.to_string());
        }
        assert_eq!(s.recent.len(), RECENT_KEPT);
        assert_eq!(s.recent[0], "99");
    }

    #[test]
    fn favourites_toggle() {
        let mut s = State::default();
        assert!(s.toggle_favourite("🔥"));
        assert!(s.is_favourite("🔥"));
        assert!(!s.toggle_favourite("🔥"));
        assert!(s.favourites.is_empty());
    }

    #[test]
    fn saves_and_loads() {
        let path = scratch("roundtrip");
        let mut s = State { tone: 3, ..Default::default() };
        s.picked("👍");
        s.toggle_favourite("🔥");
        s.save(&path).unwrap();
        assert_eq!(State::load(&path), s);
        assert!(!path.with_extension("json.new").exists());
        let _ = fs::remove_dir_all(path.parent().unwrap().parent().unwrap());
    }

    #[test]
    fn a_damaged_or_odd_file_starts_afresh() {
        let path = scratch("damaged");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, "{ not json").unwrap();
        assert_eq!(State::load(&path), State::default());
        fs::write(&path, r#"{"tone": 9, "recent": ["x"], "unknown": true}"#).unwrap();
        let s = State::load(&path);
        assert_eq!((s.tone, s.recent.as_slice()), (0, ["x".to_string()].as_slice()));
        assert_eq!(State::load(&path.with_file_name("missing.json")), State::default());
        let _ = fs::remove_dir_all(path.parent().unwrap().parent().unwrap());
    }
}
