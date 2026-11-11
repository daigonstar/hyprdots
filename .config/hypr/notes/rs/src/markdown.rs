//! Markdown for the editor: which parts of the text get which look, and what Enter does in a list. Plain functions on
//! text, no GTK, so they can be tested. The same rules as markdown.py; offsets are in characters, as GTK counts them.

use fancy_regex::Regex as Fancy;
use regex::Regex;
use std::sync::LazyLock;

struct Rules {
    fence: Regex,
    lines: Vec<(&'static str, Regex)>,
    marks: Vec<(&'static str, Fancy, usize)>,
    list_item: Regex,
    task: Regex,
    item: Regex,
    indent: Regex,
    heading: Regex,
}

static RULES: LazyLock<Rules> = LazyLock::new(|| Rules {
    fence: Regex::new(r"(?ms)^```.*?(?:^```[^\n]*$|\z)").unwrap(),
    lines: vec![
        ("h1", Regex::new(r"(?m)^# .*$").unwrap()),
        ("h2", Regex::new(r"(?m)^## .*$").unwrap()),
        ("h3", Regex::new(r"(?m)^#{3,6} .*$").unwrap()),
        ("quote", Regex::new(r"(?m)^>.*$").unwrap()),
        ("rule", Regex::new(r"(?m)^ {0,3}(?:-{3,}|\*{3,}|_{3,})\s*$").unwrap()),
        ("done", Regex::new(r"(?m)^\s*[-*+] \[[xX]\] .*$").unwrap()),
    ],
    marks: vec![
        ("bullet", Fancy::new(r"(?m)^\s*(?:[-*+]|\d+[.)])(?= )").unwrap(), 0),
        ("box", Fancy::new(r"(?m)^\s*[-*+] (\[[ xX]\])(?= )").unwrap(), 1),
        ("bold", Fancy::new(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1").unwrap(), 0),
        ("italic", Fancy::new(r"(?<![*\w])([*_])(?=[^\s*_])(.+?)(?<=[^\s*_])\1(?![*\w])").unwrap(), 0),
        ("strike", Fancy::new(r"~~(?=\S)(.+?)(?<=\S)~~").unwrap(), 0),
        ("code", Fancy::new(r"`[^`\n]+`").unwrap(), 0),
        ("link", Fancy::new(r"\[[^\]\n]+\]\([^)\s]+\)|<?https?://[^\s>)]+>?").unwrap(), 0),
    ],
    list_item: Regex::new(r"^(\s*)(?:([-*+])( \[[ xX]\])?|(\d+)([.)]))( +)(.*)$").unwrap(),
    task: Regex::new(r"^(\s*[-*+] )\[([ xX])\]( .*)?$").unwrap(),
    item: Regex::new(r"^(\s*)[-*+] (.*)$").unwrap(),
    indent: Regex::new(r"^(\s*)(.*)$").unwrap(),
    heading: Regex::new(r"^(#{1,6}) (.*)$").unwrap(),
});

/// Byte offset to character offset, for every byte offset of `text`.
fn char_offsets(text: &str) -> Vec<usize> {
    let mut map = vec![0; text.len() + 1];
    let mut chars = 0;
    for (byte, ch) in text.char_indices() {
        for i in 0..ch.len_utf8() {
            map[byte + i] = chars;
        }
        chars += 1;
    }
    map[text.len()] = chars;
    map
}

/// (start, end, tag) for everything that looks different, in characters. Code blocks win: nothing inside them is
/// formatted.
pub fn spans(text: &str) -> Vec<(usize, usize, &'static str)> {
    let rules = &*RULES;
    let mut out: Vec<(usize, usize, &'static str)> = Vec::new();
    let mut fenced = Vec::new();
    for m in rules.fence.find_iter(text) {
        fenced.push((m.start(), m.end()));
        out.push((m.start(), m.end(), "fence"));
    }
    let inside = |a: usize, b: usize| fenced.iter().any(|&(s, e)| s <= a && b <= e);
    for (tag, pattern) in &rules.lines {
        for m in pattern.find_iter(text) {
            if !inside(m.start(), m.end()) {
                out.push((m.start(), m.end(), tag));
            }
        }
    }
    for (tag, pattern, group) in &rules.marks {
        for caps in pattern.captures_iter(text).flatten() {
            let (whole, part) = (caps.get(0).unwrap(), caps.get(*group));
            if let Some(part) = part.filter(|_| !inside(whole.start(), whole.end())) {
                out.push((part.start(), part.end(), tag));
            }
        }
    }
    let map = char_offsets(text);
    let mut out: Vec<_> = out.into_iter().map(|(a, b, tag)| (map[a], map[b], tag)).collect();
    out.sort();
    out
}

/// What Enter at the end of a list line should do: the text to start the next line with (None for a plain newline), and
/// whether to clear this line instead, which ends the list when the item is empty.
pub fn next_item(line: &str) -> (Option<String>, bool) {
    let Some(m) = RULES.list_item.captures(line) else { return (None, false) };
    let get = |i| m.get(i).map_or("", |g| g.as_str());
    let (indent, bullet, boxed, number, dot, space, rest) = (get(1), get(2), get(3), get(4), get(5), get(6), get(7));
    if rest.trim().is_empty() {
        return (Some(String::new()), true);
    }
    if !bullet.is_empty() {
        let tick = if boxed.is_empty() { "" } else { " [ ]" };
        return (Some(format!("{indent}{bullet}{tick}{space}")), false);
    }
    match number.parse::<u64>() {
        Ok(n) => (Some(format!("{indent}{}{dot}{space}", n + 1)), false),
        Err(_) => (None, false),
    }
}

/// A task line with its box ticked or unticked; a plain list item becomes a task; anything else becomes one too.
pub fn toggle_box(line: &str) -> String {
    if let Some(m) = RULES.task.captures(line) {
        let tick = if matches!(&m[2], "x" | "X") { " " } else { "x" };
        return format!("{}[{tick}]{}", &m[1], m.get(3).map_or("", |g| g.as_str()));
    }
    if let Some(m) = RULES.item.captures(line) {
        return format!("{}- [ ] {}", &m[1], &m[2]);
    }
    let m = RULES.indent.captures(line).unwrap();
    format!("{}- [ ] {}", &m[1], &m[2])
}

/// Bold or italic on a selection, or off when it already has it.
pub fn wrap(text: &str, mark: &str) -> String {
    let (n, m) = (text.chars().count(), mark.chars().count());
    if n >= 2 * m && text.starts_with(mark) && text.ends_with(mark) {
        return text[mark.len()..text.len() - mark.len()].to_string();
    }
    format!("{mark}{text}{mark}")
}

/// The line as a heading of that level, or plain again when it already is one.
pub fn heading(line: &str, level: usize) -> String {
    if let Some(m) = RULES.heading.captures(line) {
        if m[1].len() == level {
            return m[2].to_string();
        }
        return format!("{} {}", "#".repeat(level), &m[2]);
    }
    format!("{} {line}", "#".repeat(level))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tags(text: &str) -> Vec<(String, &'static str)> {
        let chars: Vec<char> = text.chars().collect();
        spans(text).into_iter().map(|(a, b, tag)| (chars[a..b].iter().collect(), tag)).collect()
    }

    fn has(got: &[(String, &str)], text: &str, tag: &str) -> bool {
        got.iter().any(|(t, g)| t == text && *g == tag)
    }

    #[test]
    fn headings_and_inline() {
        let got = tags("# Title\nsome **bold** and *it* and `code` ~~gone~~\n");
        for (text, tag) in [("# Title", "h1"), ("**bold**", "bold"), ("*it*", "italic"), ("`code`", "code"), ("~~gone~~", "strike")] {
            assert!(has(&got, text, tag), "{text} {tag} in {got:?}");
        }
    }

    #[test]
    fn lists_and_tasks() {
        let got = tags("- one\n- [x] done\n- [ ] todo\n2. two\n");
        assert!(has(&got, "-", "bullet"));
        assert!(has(&got, "2.", "bullet"));
        assert!(has(&got, "[ ]", "box"));
        assert!(has(&got, "- [x] done", "done"));
    }

    #[test]
    fn code_blocks_are_left_alone() {
        let got = tags("```\n# not a heading **no**\n```\nafter **yes**");
        assert!(has(&got, "```\n# not a heading **no**\n```", "fence"));
        assert!(!has(&got, "# not a heading **no**", "h1"));
        assert!(!has(&got, "**no**", "bold"));
        assert!(has(&got, "**yes**", "bold"));
    }

    #[test]
    fn an_unclosed_code_block_runs_to_the_end() {
        assert_eq!(tags("```\nstill typing"), vec![("```\nstill typing".to_string(), "fence")]);
    }

    #[test]
    fn links() {
        let got = tags("see [docs](https://x.org) or https://y.org/a");
        assert!(has(&got, "[docs](https://x.org)", "link"));
        assert!(has(&got, "https://y.org/a", "link"));
    }

    #[test]
    fn snake_case_is_not_italic() {
        assert!(tags("a_b_c and 2*3*4").is_empty());
    }

    #[test]
    fn offsets_are_characters_not_bytes() {
        // GTK counts characters: an accent or an emoji before the mark must not shift it
        assert_eq!(spans("café **ok**"), vec![(5, 11, "bold")]);
        assert_eq!(spans("🙂 `x`"), vec![(2, 5, "code")]);
    }

    #[test]
    fn enter_continues_lists() {
        let s = |x: &str| Some(x.to_string());
        assert_eq!(next_item("- milk"), (s("- "), false));
        assert_eq!(next_item("  * milk"), (s("  * "), false));
        assert_eq!(next_item("- [x] milk"), (s("- [ ] "), false));
        assert_eq!(next_item("9. nine"), (s("10. "), false));
        assert_eq!(next_item("- "), (s(""), true));
        assert_eq!(next_item("plain"), (None, false));
    }

    #[test]
    fn toggling_boxes() {
        assert_eq!(toggle_box("- [ ] a"), "- [x] a");
        assert_eq!(toggle_box("  - [x] a"), "  - [ ] a");
        assert_eq!(toggle_box("- a"), "- [ ] a");
        assert_eq!(toggle_box("a"), "- [ ] a");
    }

    #[test]
    fn wrap_and_heading() {
        assert_eq!(wrap("x", "**"), "**x**");
        assert_eq!(wrap("**x**", "**"), "x");
        assert_eq!(wrap("*", "*"), "***");
        assert_eq!(heading("Title", 2), "## Title");
        assert_eq!(heading("## Title", 2), "Title");
        assert_eq!(heading("# Title", 3), "### Title");
    }
}
