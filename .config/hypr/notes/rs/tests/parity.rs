//! The Rust rules must give exactly what markdown.py and notebook.py give, since both versions edit the same notes.
//! Generates a few hundred awkward texts, asks Python, and compares. Skipped when python3 is not installed.

use std::io::Write;
use std::process::{Command, Stdio};

#[path = "../src/markdown.rs"]
mod markdown;
#[path = "../src/notebook.rs"]
#[allow(dead_code)]
mod notebook;

const PIECES: &[&str] = &[
    "*", "**", "_", "__", "~~", "`", "#", "# ", "## ", "#### ", "- ", "* ", "+ ", "[ ] ", "[x] ", "[X]", "1. ", "12) ",
    "\n", "\n\n", "a", "b c", "word", "é", "🙂", "```", "\n```\n", "> ", "---", "***", " ", "  ", "\t", "https://x.y/z",
    "[l](u)", "<http://a.b>", "snake_case", "2*3", "x_", ")", "(",
];

fn corpus() -> Vec<String> {
    let mut seed: u64 = 0x5eed;
    let mut next = move |n: usize| {
        seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        ((seed >> 33) as usize) % n
    };
    let mut out: Vec<String> = (0..400).map(|_| (0..1 + next(14)).map(|_| PIECES[next(PIECES.len())]).collect()).collect();
    out.push(include_str!("../src/app.rs").split("const WELCOME: &str = \"").nth(1).unwrap().split("\";").next().unwrap().into());
    out
}

const PYTHON: &str = r#"
import json, sys
sys.path.insert(0, sys.argv[1])
import markdown, notebook
out = []
for text in json.load(sys.stdin):
    line = text.split("\n")[0]
    prefix, clear = markdown.next_item(line)
    out.append({"spans": [list(s) for s in markdown.spans(text)], "next": [prefix, clear], "box": markdown.toggle_box(line),
                "h2": markdown.heading(line, 2), "wrap": markdown.wrap(text, "**"), "title": notebook.title_of(text),
                "file": notebook.file_name(text)})
print(json.dumps(out))
"#;

#[test]
fn rust_and_python_agree() {
    let here = concat!(env!("CARGO_MANIFEST_DIR"), "/..");
    let Ok(mut child) = Command::new("python3").args(["-I", "-c", PYTHON, here]).stdin(Stdio::piped()).stdout(Stdio::piped()).spawn()
    else {
        eprintln!("python3 not found: skipped");
        return;
    };
    let texts = corpus();
    child.stdin.take().unwrap().write_all(serde_json::to_string(&texts).unwrap().as_bytes()).unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success(), "python failed");
    let python: Vec<serde_json::Value> = serde_json::from_slice(&output.stdout).unwrap();
    for (text, want) in texts.iter().zip(python) {
        let line = text.split('\n').next().unwrap();
        let spans: Vec<serde_json::Value> =
            markdown::spans(text).into_iter().map(|(a, b, t)| serde_json::json!([a, b, t])).collect();
        assert_eq!(serde_json::Value::from(spans), want["spans"], "spans of {text:?}");
        let (prefix, clear) = markdown::next_item(line);
        assert_eq!(serde_json::json!([prefix, clear]), want["next"], "next_item of {line:?}");
        assert_eq!(markdown::toggle_box(line), want["box"], "toggle_box of {line:?}");
        assert_eq!(markdown::heading(line, 2), want["h2"], "heading of {line:?}");
        assert_eq!(markdown::wrap(text, "**"), want["wrap"], "wrap of {text:?}");
        assert_eq!(notebook::title_of(text), want["title"], "title_of {text:?}");
        assert_eq!(notebook::file_name(text), want["file"], "file_name of {text:?}");
    }
}
