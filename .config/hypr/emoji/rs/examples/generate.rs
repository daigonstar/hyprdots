//! Makes data/emoji.tsv, the emoji list the picker has built in, from Unicode's own data. Run it when a new emoji
//! version comes out (data/update.sh downloads the files and runs this):
//!
//!   cargo run --example generate -- emoji-test.txt annotations.json annotationsDerived.json > data/emoji.tsv
//!
//! emoji-test.txt (unicode.org/Public/emoji/latest) gives every emoji in keyboard order with its group and name.
//! The two CLDR files (github.com/unicode-org/cldr-json, English) give the search keywords.
//!
//! Each line of the output: emoji, group number, name, keywords (comma separated), and the five skin tone versions
//! (space separated, light to dark) when the emoji has them. Skin tone versions are not listed on lines of their own,
//! and neither are components (the bare tone swatches and hair styles).

use serde_json::Value;
use std::collections::HashMap;
use std::fs;

const GROUPS: [&str; 9] = [
    "Smileys & Emotion",
    "People & Body",
    "Animals & Nature",
    "Food & Drink",
    "Travel & Places",
    "Activities",
    "Objects",
    "Symbols",
    "Flags",
];
const TONES: [char; 5] = ['\u{1F3FB}', '\u{1F3FC}', '\u{1F3FD}', '\u{1F3FE}', '\u{1F3FF}'];

struct Entry {
    emoji: String,
    group: usize,
    name: String,
    tones: [Option<String>; 5],
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [test, annotations, derived] = args.as_slice() else {
        eprintln!("usage: generate emoji-test.txt annotations.json annotationsDerived.json");
        std::process::exit(2);
    };
    let keywords =
        load_keywords(annotations, "annotations").into_iter().chain(load_keywords(derived, "annotationsDerived"));
    let keywords: HashMap<String, Vec<String>> = keywords.collect();

    let mut entries: Vec<Entry> = Vec::new();
    let mut by_bare: HashMap<String, usize> = HashMap::new(); // the emoji without FE0F, to find it from a toned version
    let mut group = None;
    for line in fs::read_to_string(test).expect("emoji-test.txt").lines() {
        if let Some(name) = line.strip_prefix("# group: ") {
            group = GROUPS.iter().position(|g| *g == name); // None for "Component": skipped below
            continue;
        }
        let Some(group) = group else { continue };
        let Some((codes, rest)) = line.split_once(';') else { continue };
        if line.starts_with('#') || !rest.trim_start().starts_with("fully-qualified") {
            continue;
        }
        let emoji: String = codes
            .split_whitespace()
            .map(|c| char::from_u32(u32::from_str_radix(c, 16).expect("hex")).expect("code point"))
            .collect();
        // "# 😀 E1.0 grinning face": the name follows the version
        let comment = rest.split_once('#').expect("comment").1.trim();
        let name = comment.splitn(3, ' ').nth(2).expect("name").to_string();

        let tones_in: Vec<char> = emoji.chars().filter(|c| TONES.contains(c)).collect();
        if !tones_in.is_empty() {
            // A skin tone version: kept on its base emoji when every person in it has the same tone
            let bare: String = emoji.chars().filter(|c| !TONES.contains(c) && *c != '\u{FE0F}').collect();
            if tones_in.iter().all(|t| *t == tones_in[0])
                && let Some(&base) = by_bare.get(&bare)
            {
                let slot = TONES.iter().position(|t| *t == tones_in[0]).unwrap();
                entries[base].tones[slot].get_or_insert(emoji);
            }
            continue;
        }
        by_bare.insert(emoji.chars().filter(|c| *c != '\u{FE0F}').collect(), entries.len());
        entries.push(Entry { emoji, group, name, tones: Default::default() });
    }

    let mut missing = 0;
    for e in &entries {
        let bare: String = e.emoji.chars().filter(|c| *c != '\u{FE0F}').collect();
        let words = keywords.get(&e.emoji).or_else(|| keywords.get(&bare));
        if words.is_none() {
            missing += 1;
        }
        let words: Vec<&str> = words
            .map(|w| {
                w.iter().map(String::as_str).filter(|w| !w.eq_ignore_ascii_case(&e.name) && !w.contains(',')).collect()
            })
            .unwrap_or_default();
        let tones = if e.tones.iter().all(Option::is_some) {
            e.tones.iter().flatten().cloned().collect::<Vec<_>>().join(" ")
        } else {
            String::new()
        };
        println!("{}\t{}\t{}\t{}\t{}", e.emoji, e.group, e.name, words.join(","), tones);
    }
    eprintln!(
        "{} emoji, {} with skin tones, {} without keywords",
        entries.len(),
        entries.iter().filter(|e| e.tones.iter().all(Option::is_some)).count(),
        missing
    );
}

fn load_keywords(path: &str, top: &str) -> Vec<(String, Vec<String>)> {
    let json: Value = serde_json::from_str(&fs::read_to_string(path).expect("annotations")).expect("json");
    let Some(map) = json[top]["annotations"].as_object() else { panic!("{path}: no {top}.annotations") };
    map.iter()
        .map(|(emoji, v)| {
            let words =
                v["default"].as_array().map(|a| a.iter().filter_map(|w| w.as_str().map(str::to_lowercase)).collect());
            (emoji.clone(), words.unwrap_or_default())
        })
        .collect()
}
