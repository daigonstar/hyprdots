//! Where the notes live while their tabs are open: one Markdown file per tab in ~/.local/state/hyprdots/notes (or the
//! folder in NOTES_DIR), saved as you type, so open tabs survive a crash or a restart. Closing a tab deletes its file, to
//! the bin so a slip can be undone. The same files and the same .tabs.json as notebook.py, so either version reads what
//! the other wrote.

use gtk::{gio, glib};
use regex::Regex;
use serde_json::{Map, Value};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use std::time::{SystemTime, UNIX_EPOCH};

pub const INBOX: &str = "inbox"; // the tab notes.sh --append writes to
pub type State = Map<String, Value>;

pub fn home() -> PathBuf {
    std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/"))
}

pub fn default_dir() -> PathBuf {
    if let Some(dir) = std::env::var_os("NOTES_DIR").filter(|d| !d.is_empty()) {
        return PathBuf::from(dir);
    }
    let state = std::env::var_os("XDG_STATE_HOME").map(PathBuf::from).unwrap_or_else(|| home().join(".local/state"));
    state.join("hyprdots/notes")
}

static TITLE_MARKS: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^\s*(?:#{1,6}\s+|[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+|>\s*)").unwrap());
static UNSAFE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r#"[/\\:*?"<>|\x00-\x1f]+"#).unwrap());
static SPACES: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\s+").unwrap());

/// Line breaks as Python's str.splitlines() counts them.
fn is_break(c: char) -> bool {
    matches!(c, '\n' | '\r' | '\x0b' | '\x0c' | '\x1c' | '\x1d' | '\x1e' | '\u{85}' | '\u{2028}' | '\u{2029}')
}

/// What a note is about: its first line that is not empty, without the Markdown marks around it.
pub fn title_of(text: &str) -> String {
    for line in text.split(is_break) {
        let line = TITLE_MARKS.replace(line, "");
        let line = line.trim_matches(|c| matches!(c, ' ' | '*' | '_' | '`' | '#'));
        if !line.is_empty() {
            return line.chars().take(80).collect();
        }
    }
    String::new()
}

/// A name for Save as, from the note's title: no slashes or characters other systems refuse.
pub fn file_name(title: &str) -> String {
    let name = UNSAFE.replace_all(title, " ");
    let name = name.trim().trim_matches('.').trim();
    let name: String = SPACES.replace_all(name, " ").chars().take(60).collect();
    format!("{}.md", if name.is_empty() { "Note" } else { &name })
}

pub struct Notebook {
    pub dir: PathBuf,
    pub state_path: PathBuf,
}

impl Notebook {
    pub fn new(folder: Option<PathBuf>) -> Notebook {
        let dir = folder.unwrap_or_else(default_dir);
        let _ = fs::create_dir_all(&dir);
        Notebook { state_path: dir.join(".tabs.json"), dir }
    }

    /// Open tabs in the order you left them. A note file the order does not mention (one notes.sh made while the window
    /// was not running, say) still gets a tab, at the end, so nothing is ever hidden.
    pub fn tabs(&self) -> Vec<PathBuf> {
        let state = self.load_state();
        let mut files: Vec<(String, PathBuf, SystemTime)> = Vec::new();
        if let Ok(entries) = fs::read_dir(&self.dir) {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().into_owned();
                let path = entry.path();
                if name.ends_with(".md") && path.is_file() {
                    let mtime = path.metadata().and_then(|m| m.modified()).unwrap_or(UNIX_EPOCH);
                    files.push((name, path, mtime));
                }
            }
        }
        let mut ordered = Vec::new();
        if let Some(Value::Array(names)) = state.get("tabs") {
            for name in names.iter().filter_map(Value::as_str) {
                if let Some(i) = files.iter().position(|(n, _, _)| n == name) {
                    ordered.push(files.remove(i).1);
                }
            }
        }
        files.sort_by_key(|(_, _, mtime)| *mtime);
        ordered.extend(files.into_iter().map(|(_, p, _)| p));
        ordered
    }

    /// A new note, named for when it was made, as notebook.py names them.
    pub fn create(&self, text: &str) -> io::Result<PathBuf> {
        let stamp = glib::DateTime::now_local()
            .and_then(|t| t.format("%Y%m%d-%H%M%S"))
            .map(|s| s.to_string())
            .unwrap_or_else(|_| "note".into());
        let nanos = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.subsec_nanos()).unwrap_or(0);
        let mut n = 0;
        let path = loop {
            let tail = (nanos + n) % 1000;
            let path = self.dir.join(format!("{stamp}-{:03}{tail:03}.md", std::process::id() % 1000));
            if !path.exists() || n > 1000 {
                break path;
            }
            n += 1;
        };
        self.write(&path, text)?;
        Ok(path)
    }

    pub fn read(&self, path: &Path) -> String {
        fs::read(path).ok().and_then(|b| String::from_utf8(b).ok()).unwrap_or_default()
    }

    /// Atomic: a crash or power cut leaves the old version or the new one, never half of one.
    pub fn write(&self, path: &Path, text: &str) -> io::Result<()> {
        let name = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
        let tmp = path.with_file_name(format!(".{name}.{}.tmp", std::process::id()));
        fs::write(&tmp, text)?;
        fs::rename(&tmp, path)
    }

    /// Closing a tab deletes its note. An empty one is simply removed; one with something in it goes to the bin.
    pub fn close(&self, path: &Path) {
        if !path.exists() {
            return;
        }
        if self.read(path).trim().is_empty() {
            let _ = fs::remove_file(path);
            return;
        }
        if gio::prelude::FileExt::trash(&gio::File::for_path(path), gio::Cancellable::NONE).is_err() {
            let _ = fs::remove_file(path);
        }
    }

    /// For scripts: adds a line to the Inbox tab, made if it is missing, without the window open.
    pub fn append(&self, text: &str) -> io::Result<PathBuf> {
        let path = self.dir.join(format!("{INBOX}.md"));
        let old = if path.exists() { self.read(&path) } else { "# Inbox\n".to_string() };
        let join = if old.ends_with('\n') { "" } else { "\n" };
        self.write(&path, &format!("{old}{join}{}\n", text.trim_end_matches('\n')))?;
        Ok(path)
    }

    pub fn load_state(&self) -> State {
        match fs::read_to_string(&self.state_path).ok().and_then(|t| serde_json::from_str(&t).ok()) {
            Some(Value::Object(map)) => map,
            _ => State::new(),
        }
    }

    /// As json.dumps(state, indent=1) writes it.
    pub fn save_state(&self, state: &State) -> io::Result<()> {
        let mut out = Vec::new();
        let formatter = serde_json::ser::PrettyFormatter::with_indent(b" ");
        let mut ser = serde_json::Serializer::with_formatter(&mut out, formatter);
        serde::Serialize::serialize(state, &mut ser).map_err(io::Error::other)?;
        let tmp = self.state_path.with_file_name(format!(".tabs.json.{}.tmp", std::process::id()));
        fs::write(&tmp, out)?;
        fs::rename(&tmp, &self.state_path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread::sleep;
    use std::time::Duration;

    struct Tmp(PathBuf);
    impl Drop for Tmp {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn book(name: &str) -> (Tmp, Notebook) {
        let root = std::env::temp_dir().join(format!("hyprdots-notes-test-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let book = Notebook::new(Some(root.join("notes")));
        (Tmp(root), book)
    }

    fn names(paths: &[PathBuf]) -> Vec<String> {
        paths.iter().map(|p| p.file_name().unwrap().to_string_lossy().into_owned()).collect()
    }

    #[test]
    fn new_write_read() {
        let (_t, book) = book("rw");
        let path = book.create("milk\n").unwrap();
        assert_eq!(book.read(&path), "milk\n");
        assert_ne!(book.create("").unwrap(), path);
    }

    #[test]
    fn tabs_keep_their_order_and_stray_notes_get_one_at_the_end() {
        let (_t, book) = book("order");
        let (a, b) = (book.create("a").unwrap(), book.create("b").unwrap());
        let mut state = State::new();
        state.insert("tabs".into(), Value::from(names(&[b.clone(), a.clone()])));
        book.save_state(&state).unwrap();
        sleep(Duration::from_millis(20));
        let stray = book.create("from a script").unwrap();
        assert_eq!(book.tabs(), vec![b, a, stray]);
    }

    #[test]
    fn closing_deletes_the_note() {
        let (_t, book) = book("close");
        let (full, empty) = (book.create("keep me?").unwrap(), book.create("   \n").unwrap());
        book.close(&full);
        book.close(&empty);
        assert!(!full.exists());
        assert!(!empty.exists());
        assert!(book.tabs().is_empty());
        book.close(&full); // already gone: nothing happens
    }

    #[test]
    fn tabs_survive_a_restart() {
        let (_t, book) = book("restart");
        book.create("still here").unwrap();
        let again = Notebook::new(Some(book.dir.clone()));
        let texts: Vec<String> = again.tabs().iter().map(|p| again.read(p)).collect();
        assert_eq!(texts, vec!["still here"]);
    }

    #[test]
    fn state_and_hidden_files_are_not_tabs() {
        let (_t, book) = book("hidden");
        book.save_state(&State::new()).unwrap();
        book.create("x").unwrap();
        assert_eq!(book.tabs().len(), 1);
    }

    #[test]
    fn append_makes_the_inbox() {
        let (_t, book) = book("append");
        let path = book.append("first thought").unwrap();
        book.append("second").unwrap();
        assert_eq!(book.read(&path), "# Inbox\nfirst thought\nsecond\n");
    }

    #[test]
    fn a_broken_state_file_is_ignored() {
        let (_t, book) = book("broken");
        fs::write(&book.state_path, "{broken").unwrap();
        assert!(book.load_state().is_empty());
    }

    #[test]
    fn writes_leave_no_temp_files() {
        let (_t, book) = book("tmp");
        let path = book.create("x").unwrap();
        book.write(&path, "y").unwrap();
        let left: Vec<_> = fs::read_dir(&book.dir).unwrap().flatten().map(|e| e.path()).collect();
        assert_eq!(left, vec![path]);
    }

    #[test]
    fn reads_and_writes_the_state_as_the_python_version_does() {
        // as notebook.py writes it, with keys this version does not use kept as they are
        let (_t, book) = book("state");
        let python = "{\n \"tabs\": [\n  \"a.md\"\n ],\n \"current\": \"a.md\",\n \"pinned\": false,\n \"cursors\": {\n  \"a.md\": 3\n },\n \"welcomed\": true,\n \"zoom\": 1.1,\n \"later\": \"\\u00e9\"\n}";
        fs::write(&book.state_path, python).unwrap();
        let state = book.load_state();
        assert_eq!(state["cursors"]["a.md"], 3);
        assert_eq!(state["later"], "é");
        book.save_state(&state).unwrap();
        let ours = fs::read_to_string(&book.state_path).unwrap();
        assert_eq!(ours, python.replace("\\u00e9", "é"));
    }

    #[test]
    fn title_and_save_as_name() {
        assert_eq!(title_of("\n\n## Plan for **Monday**\nmore"), "Plan for **Monday");
        assert_eq!(title_of("- [ ] buy milk"), "buy milk");
        assert_eq!(title_of("   \n"), "");
        assert_eq!(file_name(r#"a/b: "c"?"#), "a b c.md");
        assert_eq!(file_name(""), "Note.md");
    }
}
