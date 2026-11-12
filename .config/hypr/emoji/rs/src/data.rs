//! The emoji the picker knows, built in from data/emoji.tsv (made by examples/generate.rs from Unicode's data).

pub struct Group {
    pub name: &'static str,
    /// What the group's tab shows
    pub icon: &'static str,
}

pub const GROUPS: [Group; 9] = [
    Group { name: "Smileys & emotion", icon: "😀" },
    Group { name: "People & body", icon: "👋" },
    Group { name: "Animals & nature", icon: "🐻" },
    Group { name: "Food & drink", icon: "🍔" },
    Group { name: "Travel & places", icon: "✈️" },
    Group { name: "Activities", icon: "⚽" },
    Group { name: "Objects", icon: "💡" },
    Group { name: "Symbols", icon: "🔣" },
    Group { name: "Flags", icon: "🏁" },
];

pub struct Emoji {
    pub emoji: &'static str,
    pub group: usize,
    pub name: &'static str,
    pub keywords: Vec<&'static str>,
    /// Light to dark, when the emoji comes in skin tones
    pub tones: Option<[&'static str; 5]>,
}

impl Emoji {
    /// The emoji in skin tone `tone` (0 is the default yellow, 1 to 5 light to dark), when it has tones.
    pub fn with_tone(&self, tone: usize) -> &'static str {
        match (&self.tones, tone) {
            (Some(tones), 1..=5) => tones[tone - 1],
            _ => self.emoji,
        }
    }
}

const DATA: &str = include_str!("../data/emoji.tsv");

pub fn all() -> Vec<Emoji> {
    parse(DATA)
}

pub fn parse(text: &'static str) -> Vec<Emoji> {
    text.lines()
        .filter_map(|line| {
            let mut f = line.split('\t');
            let (emoji, group, name, keywords, tones) =
                (f.next()?, f.next()?, f.next()?, f.next()?, f.next().unwrap_or(""));
            let group: usize = group.parse().ok().filter(|g| *g < GROUPS.len())?;
            let tones: Vec<&str> = tones.split(' ').filter(|t| !t.is_empty()).collect();
            Some(Emoji {
                emoji,
                group,
                name,
                keywords: keywords.split(',').filter(|k| !k.is_empty()).collect(),
                tones: tones.try_into().ok(),
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_built_in_list_is_complete() {
        let all = all();
        assert!(all.len() > 1800, "only {} emoji", all.len());
        assert_eq!(all[0].emoji, "😀");
        assert_eq!(all[0].name, "grinning face");
        assert!(all[0].keywords.contains(&"happy"));
        for (g, group) in GROUPS.iter().enumerate() {
            assert!(all.iter().any(|e| e.group == g), "group {} is empty", group.name);
        }
        // every tab icon is an emoji of its own group
        for (g, group) in GROUPS.iter().enumerate() {
            assert!(all.iter().any(|e| e.emoji == group.icon && e.group == g), "{}", group.icon);
        }
    }

    #[test]
    fn skin_tones() {
        let all = all();
        let hand = all.iter().find(|e| e.emoji == "✋").unwrap();
        assert_eq!(hand.with_tone(0), "✋");
        assert_eq!(hand.with_tone(3), "✋🏽");
        assert_eq!(hand.with_tone(5), "✋🏿");
        let grin = &all[0];
        assert_eq!(grin.with_tone(3), "😀");
        // tone versions are not entries of their own
        assert!(!all.iter().any(|e| e.emoji.contains('\u{1F3FD}')));
    }

    #[test]
    fn bad_lines_are_skipped() {
        let parsed = parse("😀\t0\tgrinning face\thappy\t\nbroken line\n😀\t99\ttoo far\t\t\n✋\t1\thand\t\ta b c\n");
        assert_eq!(parsed.len(), 2);
        assert!(parsed[1].tones.is_none()); // three tones is not five
    }
}
