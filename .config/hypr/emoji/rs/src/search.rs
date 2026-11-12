//! What the search box finds. Every word typed must start a word of the emoji's name or keywords; names count more
//! than keywords, whole words more than beginnings. ":thumbs_up:" works too, as does pasting the emoji itself.

use crate::data::Emoji;

/// The query as words: lower case, without the colons and underscores of a :short_code:.
pub fn words(query: &str) -> Vec<String> {
    query.to_lowercase().replace(['_', ':'], " ").split_whitespace().map(str::to_string).collect()
}

fn score_word(word: &str, e: &Emoji) -> u32 {
    let name_words = e.name.split(|c: char| c.is_whitespace() || c == ':' || c == '-').filter(|w| !w.is_empty());
    let mut best = 0;
    for n in name_words {
        let n = n.to_lowercase();
        best = best.max(if n == word {
            6
        } else if n.starts_with(word) {
            4
        } else {
            0
        });
    }
    for k in e.keywords.iter().flat_map(|k| k.split_whitespace()) {
        best = best.max(if k == word {
            3
        } else if k.starts_with(word) {
            2
        } else {
            0
        });
    }
    best
}

/// Indexes into `all` that match `query`, best first; ties keep the keyboard order. Empty for an empty query.
pub fn search(all: &[Emoji], query: &str) -> Vec<usize> {
    let trimmed = query.trim();
    // a pasted emoji (in any skin tone) finds itself
    if let Some(i) = all.iter().position(|e| e.emoji == trimmed || e.tones.is_some_and(|t| t.contains(&trimmed))) {
        return vec![i];
    }
    let words = words(trimmed);
    if words.is_empty() {
        return Vec::new();
    }
    let phrase = words.join(" ");
    let mut scored: Vec<(i32, usize)> = all
        .iter()
        .enumerate()
        .filter_map(|(i, e)| {
            let mut total = 0;
            for w in &words {
                match score_word(w, e) {
                    0 => return None,
                    s => total += s as i32,
                }
            }
            let name = e.name.to_lowercase();
            if name == phrase {
                total += 20;
            } else if name.starts_with(&phrase) {
                total += 1;
            }
            // Short names first: "heart" should reach ❤️ (red heart) before the many "heart with ..." ones
            total -= 2 * name.split_whitespace().count() as i32;
            Some((total, i))
        })
        .collect();
    scored.sort_by(|a, b| b.0.cmp(&a.0).then(a.1.cmp(&b.1)));
    scored.into_iter().map(|(_, i)| i).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data;

    fn first(all: &[Emoji], q: &str) -> &'static str {
        search(all, q).first().map(|&i| all[i].emoji).unwrap_or("")
    }

    #[test]
    fn names_and_keywords() {
        let all = data::all();
        assert_eq!(first(&all, "grinning face"), "😀");
        assert_eq!(first(&all, "thumbs up"), "👍");
        assert_eq!(first(&all, ":thumbs_up:"), "👍");
        assert_eq!(first(&all, "  Thumbs   UP "), "👍");
        assert_eq!(first(&all, "red heart"), "❤️");
        assert!(search(&all, "heart").iter().take(12).any(|&i| all[i].emoji == "❤️"));
        assert_eq!(first(&all, "fire"), "🔥");
        assert_eq!(first(&all, "flag japan"), "🇯🇵");
        let happy = search(&all, "happy");
        assert!(happy.len() > 5);
        assert!(happy.iter().any(|&i| all[i].emoji == "😀"), "keywords count");
    }

    #[test]
    fn every_word_has_to_match() {
        let all = data::all();
        assert!(search(&all, "grinning zzzqqq").is_empty());
        assert!(search(&all, "").is_empty());
        assert!(search(&all, "   ").is_empty());
        // beginnings of words, not the middle
        assert!(search(&all, "rinning").is_empty());
        assert_eq!(first(&all, "grin"), "😀");
    }

    #[test]
    fn a_pasted_emoji_finds_itself() {
        let all = data::all();
        assert_eq!(first(&all, "🔥"), "🔥");
        assert_eq!(first(&all, "✋🏽"), "✋"); // a tone version finds its base
    }

    #[test]
    fn ties_keep_keyboard_order() {
        let all = data::all();
        let found = search(&all, "face");
        let firsts: Vec<usize> = found.iter().take(2).copied().collect();
        assert!(firsts[0] < firsts[1]);
    }
}
