//! Colours from the Theme page, read from the quick tray's theme file, and the theme override's look from gtk.css (as
//! hyprsettings/livetheme.py gives it to our own windows). Text in, text out, so it can be tested.

use regex::Regex;
use std::sync::LazyLock;

pub const DEFAULT_COLOURS: [(&str, &str); 7] = [
    ("tray_bg", "rgba(27,26,27,0.96)"),
    ("tray_text", "#F9F8F9"),
    ("tray_card", "rgba(128,128,128,0.18)"),
    ("tray_accent", "#7aa2f7"),
    ("tray_on_accent", "#1B1A1B"),
    ("tray_muted", "#9a9a9a"),
    ("tray_attention", "#e06c75"),
];

static DEFINE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"@define-color\s+(\w+)\s+([^;]+);").unwrap());
static FONT: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"font-family:\s*([^;]+);").unwrap());

/// The defaults, with whatever the theme file defines laid over them, in order.
pub fn colours(theme_css: Option<&str>) -> Vec<(String, String)> {
    let mut out: Vec<(String, String)> = DEFAULT_COLOURS.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect();
    for m in DEFINE.captures_iter(theme_css.unwrap_or("")) {
        let (name, value) = (m[1].to_string(), m[2].to_string());
        match out.iter_mut().find(|(k, _)| *k == name) {
            Some(slot) => slot.1 = value,
            None => out.push((name, value)),
        }
    }
    out
}

pub fn get<'a>(colours: &'a [(String, String)], name: &str) -> &'a str {
    colours.iter().find(|(k, _)| k == name).map_or("", |(_, v)| v.as_str())
}

/// The colours as CSS variables, and the theme's font for the panel.
pub fn variables_css(colours: &[(String, String)], theme_css: Option<&str>) -> String {
    let mut css = String::from(":root {\n");
    for (k, v) in colours {
        css += &format!("  --{k}: {v};\n");
    }
    css += "}\n";
    if let Some(m) = theme_css.and_then(|t| FONT.captures(t)) {
        css += &format!(".panel {{ font-family: {}; }}\n", &m[1]);
    }
    css
}

// ---- livetheme.py: the theme override's look, for windows marked LIVE_CLASS -----------------------------------------
pub const LIVE_CLASS: &str = "hyprdots-live";
const SKIP: &str = "window:not(.hyprdots-live)";
const MARK: &str = "/* hyprdots theme: ";
const END: &str = "/* hyprdots theme end */";

/// The hyprdots block of gtk.css, as our own marked windows should have it. Empty without one.
pub fn live_block(gtk_css: Option<&str>) -> String {
    let Some(text) = gtk_css else { return String::new() };
    let Some(start) = text.find(MARK) else { return String::new() };
    let end = text[start..].find(END).map_or(text.len(), |e| start + e);
    text[start..end].replace(&format!("{SKIP} "), "").replace(SKIP, "window")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn theme_colours_lay_over_the_defaults() {
        let c = colours(Some("@define-color tray_accent #ff0000;\n@define-color extra rgba(1,2,3,0.5);\n"));
        assert_eq!(get(&c, "tray_accent"), "#ff0000");
        assert_eq!(get(&c, "tray_text"), "#F9F8F9");
        assert_eq!(get(&c, "extra"), "rgba(1,2,3,0.5)");
        assert_eq!(colours(None).len(), 7);
    }

    #[test]
    fn variables_and_font() {
        let css = variables_css(&colours(None), Some("* { font-family: \"Inter\", sans; }"));
        assert!(css.starts_with(":root {\n  --tray_bg: rgba(27,26,27,0.96);\n"));
        assert!(css.ends_with(".panel { font-family: \"Inter\", sans; }\n"));
        assert!(!variables_css(&colours(None), None).contains("font-family"));
    }

    #[test]
    fn the_live_block_is_unprefixed() {
        let gtk = "mine { a: b; }\n/* hyprdots theme: luna */\nwindow:not(.hyprdots-live) headerbar { c: d; }\n\
                   window:not(.hyprdots-live).background { e: f; }\n/* hyprdots theme end */\nafter { g: h; }";
        let block = live_block(Some(gtk));
        assert!(block.starts_with("/* hyprdots theme: luna */"));
        assert!(block.contains("\nheaderbar { c: d; }"));
        assert!(block.contains("window.background { e: f; }"));
        assert!(!block.contains("mine") && !block.contains("after") && !block.contains("hyprdots-live"));
        assert_eq!(live_block(Some("nothing here")), "");
        assert_eq!(live_block(None), "");
    }
}
