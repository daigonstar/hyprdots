//! The picker window: a card over the screen with a search box, a tab per group (plus Recent and Favourites), a grid
//! of emoji and, under it, the one you are on and the skin tones. The keyboard drives everything while the search box
//! keeps the focus, so typing always searches.

use crate::data::{self, Emoji, GROUPS};
use crate::state::{self, State};
use crate::theme;
use gtk::{gdk, gio, glib, prelude::*};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use std::cell::{Cell, RefCell};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::rc::Rc;

pub const COLUMNS: u32 = 10;
const RECENT: usize = 0;
const FAVOURITES: usize = 1;
const FIRST_GROUP: usize = 2;
const TONE_HANDS: [&str; 6] = ["✋", "✋🏻", "✋🏼", "✋🏽", "✋🏾", "✋🏿"];
const TONE_NAMES: [&str; 6] = ["Default", "Light", "Medium-light", "Medium", "Medium-dark", "Dark"];

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Action {
    /// Typed into the window you were in
    Type,
    /// Put on the clipboard
    Copy,
}

pub struct Pick {
    pub emoji: String,
    pub action: Action,
}

const CSS: &str = "
window.emoji-picker { background: transparent; }
.backdrop { background: rgba(0, 0, 0, 0.18); }
.panel { background: var(--tray_solid); color: var(--tray_text); border-radius: 18px; padding: 14px 14px 10px 14px;
         border: 1px solid color-mix(in srgb, var(--tray_accent) 55%, transparent); box-shadow: 0 18px 60px rgba(0, 0, 0, 0.5); }
.panel label { color: var(--tray_text); }
.emoji { font-family: \"Noto Color Emoji\", emoji; }
entry.search { min-height: 40px; font-size: 1.15em; background: var(--tray_card); border: none; border-radius: 12px;
               box-shadow: none; outline: none; padding: 0 10px; color: var(--tray_text); caret-color: var(--tray_accent); }
entry.search image { color: var(--tray_accent); }
.tabs { margin: 10px 0 4px 0; }
.tabs button { background: none; border: none; box-shadow: none; border-radius: 10px; min-width: 40px; min-height: 36px;
               padding: 0; font-size: 1.25em; transition: background-color 110ms ease-out, opacity 110ms ease-out; }
.tabs button:hover { background: var(--tray_card); }
.tabs button:checked { background: color-mix(in srgb, var(--tray_accent) 35%, transparent); box-shadow: inset 0 -2px 0 var(--tray_accent); }
.tabs.searching button { opacity: 0.4; }
.heading { color: var(--tray_muted); font-size: 0.78em; font-weight: 700; letter-spacing: 1px; margin: 6px 4px 4px 4px; }
gridview, gridview > child, scrolledwindow, viewport { background: none; padding: 0; }
gridview > child { border-radius: 10px; transition: background-color 90ms ease-out; }
gridview > child:selected { background: color-mix(in srgb, var(--tray_accent) 42%, transparent); }
.cell { font-size: 26px; min-width: 48px; min-height: 46px; }
.empty { color: var(--tray_muted); margin: 40px 30px; }
.foot { margin-top: 8px; padding-top: 8px; border-top: 1px solid color-mix(in srgb, var(--tray_text) 12%, transparent); }
.preview { font-size: 32px; min-width: 46px; }
.name { font-weight: 600; }
.hint { color: var(--tray_muted); font-size: 0.82em; }
.tone { background: none; border: none; box-shadow: none; border-radius: 8px; min-width: 30px; min-height: 30px; padding: 0; font-size: 1.05em; }
.tone:hover { background: var(--tray_card); }
.tone:checked { background: color-mix(in srgb, var(--tray_accent) 40%, transparent); }
scrollbar { background: none; }
";
const TOUCH_CSS: &str = "
.cell { font-size: 34px; min-width: 62px; min-height: 60px; }
.tabs button { min-width: 50px; min-height: 48px; }
.tone { min-width: 44px; min-height: 44px; }
";

fn home() -> PathBuf {
    std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/tmp"))
}

fn touch_mode() -> bool {
    home().join(".local/state/hyprdots/touch-mode").exists()
}

fn gtk4_css_path() -> PathBuf {
    let config = std::env::var_os("XDG_CONFIG_HOME").filter(|c| !c.is_empty()).map(PathBuf::from);
    config.unwrap_or_else(|| home().join(".config")).join("gtk-4.0/gtk.css")
}

struct Ui {
    app: gtk::Application,
    win: gtk::ApplicationWindow,
    all: Vec<Emoji>,
    index_of: HashMap<&'static str, usize>,
    state: RefCell<State>,
    state_path: PathBuf,
    tab: Cell<usize>,
    shown: RefCell<Vec<usize>>,
    model: gtk::StringList,
    selection: gtk::SingleSelection,
    grid: gtk::GridView,
    entry: gtk::SearchEntry,
    tab_row: gtk::Box,
    tabs: Vec<gtk::ToggleButton>,
    tones: Vec<gtk::ToggleButton>,
    heading: gtk::Label,
    stack: gtk::Stack,
    empty: gtk::Label,
    preview: gtk::Label,
    name: gtk::Label,
    pick: Rc<RefCell<Option<Pick>>>,
}

pub fn run(pick: Rc<RefCell<Option<Pick>>>) -> glib::ExitCode {
    let app = gtk::Application::new(Some("com.hyprdots.emoji"), gio::ApplicationFlags::NON_UNIQUE);
    app.connect_activate(move |app| build(app, pick.clone()));
    let argv0 = std::env::args().next().unwrap_or_else(|| "hyprdots-emoji".into());
    app.run_with_args(&[argv0])
}

fn load_css(display: &gdk::Display) {
    let theme_text = fs::read_to_string(home().join(".config/hypr/tray/theme.css")).ok();
    let colours = theme::colours(theme_text.as_deref());
    // the panel is solid, so the emoji read well over anything
    let solid =
        gdk::RGBA::parse(theme::get(&colours, "tray_bg")).map(|c| c.with_alpha(1.0)).unwrap_or(gdk::RGBA::BLACK);
    let mut names = colours.clone();
    names.push(("tray_solid".into(), solid.to_string()));
    let live = theme::live_block(fs::read_to_string(gtk4_css_path()).ok().as_deref());
    let parts = [
        live,
        theme::variables_css(&names, theme_text.as_deref()),
        CSS.to_string(),
        if touch_mode() { TOUCH_CSS.to_string() } else { String::new() },
    ];
    for (priority, css) in (800u32..).zip(parts) {
        let provider = gtk::CssProvider::new();
        provider.load_from_string(&css);
        gtk::style_context_add_provider_for_display(display, &provider, priority);
    }
}

fn build(app: &gtk::Application, pick: Rc<RefCell<Option<Pick>>>) {
    let display = gdk::Display::default().expect("no display");
    load_css(&display);

    let win = gtk::ApplicationWindow::builder()
        .application(app)
        .title("Emoji")
        .css_classes(["emoji-picker", theme::LIVE_CLASS])
        .build();
    if gtk4_layer_shell::is_supported() {
        win.init_layer_shell();
        win.set_namespace(Some("hyprdots-emoji"));
        win.set_layer(Layer::Overlay);
        win.set_keyboard_mode(KeyboardMode::Exclusive);
        win.set_exclusive_zone(-1);
        for edge in [Edge::Top, Edge::Bottom, Edge::Left, Edge::Right] {
            win.set_anchor(edge, true);
        }
    } else {
        win.set_default_size(640, 620);
    }

    let backdrop = gtk::Box::builder().css_classes(["backdrop"]).build();
    let panel = gtk::Box::builder()
        .orientation(gtk::Orientation::Vertical)
        .css_classes(["panel"])
        .halign(gtk::Align::Center)
        .valign(gtk::Align::Center)
        .hexpand(true)
        .vexpand(true)
        .build();
    backdrop.append(&panel);
    win.set_child(Some(&backdrop));

    let entry =
        gtk::SearchEntry::builder().css_classes(["search"]).placeholder_text("Search emoji").hexpand(true).build();
    entry.set_search_delay(0);
    panel.append(&entry);

    let tab_row = gtk::Box::builder().css_classes(["tabs"]).spacing(2).halign(gtk::Align::Center).build();
    let mut tab_specs = vec![("🕘", "Recent".to_string()), ("⭐", "Favourites".to_string())];
    tab_specs.extend(GROUPS.iter().map(|g| (g.icon, g.name.to_string())));
    let tabs: Vec<gtk::ToggleButton> = tab_specs
        .iter()
        .map(|(icon, name)| {
            let b = gtk::ToggleButton::builder()
                .label(*icon)
                .tooltip_text(name.as_str())
                .css_classes(["emoji"])
                .can_focus(false)
                .build();
            tab_row.append(&b);
            b
        })
        .collect();
    panel.append(&tab_row);

    let heading = gtk::Label::builder().xalign(0.0).css_classes(["heading"]).build();
    panel.append(&heading);

    let model = gtk::StringList::new(&[]);
    let selection = gtk::SingleSelection::builder().model(&model).autoselect(true).can_unselect(false).build();
    let grid = gtk::GridView::builder()
        .model(&selection)
        .min_columns(COLUMNS)
        .max_columns(COLUMNS)
        .single_click_activate(true)
        .can_focus(false)
        .build();
    let scroller = gtk::ScrolledWindow::builder()
        .hscrollbar_policy(gtk::PolicyType::Never)
        .min_content_height(if touch_mode() { 380 } else { 300 })
        .propagate_natural_width(true)
        .child(&grid)
        .build();
    let empty = gtk::Label::builder().wrap(true).justify(gtk::Justification::Center).css_classes(["empty"]).build();
    let stack = gtk::Stack::new();
    stack.add_named(&scroller, Some("grid"));
    stack.add_named(&empty, Some("empty"));
    panel.append(&stack);

    let foot = gtk::Box::builder().spacing(10).css_classes(["foot"]).build();
    let preview = gtk::Label::builder().css_classes(["preview", "emoji"]).build();
    let words =
        gtk::Box::builder().orientation(gtk::Orientation::Vertical).valign(gtk::Align::Center).hexpand(true).build();
    let name = gtk::Label::builder()
        .xalign(0.0)
        .ellipsize(gtk::pango::EllipsizeMode::End)
        .max_width_chars(30)
        .css_classes(["name"])
        .build();
    let hint = gtk::Label::builder()
        .xalign(0.0)
        .label("Enter types it · Shift+Enter copies · Ctrl+D favourite")
        .ellipsize(gtk::pango::EllipsizeMode::End)
        .css_classes(["hint"])
        .build();
    words.append(&name);
    words.append(&hint);
    foot.append(&preview);
    foot.append(&words);
    let tone_box = gtk::Box::builder().spacing(1).valign(gtk::Align::Center).build();
    let tones: Vec<gtk::ToggleButton> = TONE_HANDS
        .iter()
        .zip(TONE_NAMES)
        .map(|(hand, tone_name)| {
            let b = gtk::ToggleButton::builder()
                .label(*hand)
                .tooltip_text(format!("Skin tone: {tone_name} (Ctrl+T)"))
                .css_classes(["tone", "emoji"])
                .can_focus(false)
                .build();
            tone_box.append(&b);
            b
        })
        .collect();
    foot.append(&tone_box);
    panel.append(&foot);

    let all = data::all();
    let index_of = all.iter().enumerate().map(|(i, e)| (e.emoji, i)).collect();
    let state_path = state::path();
    let state = State::load(&state_path);
    let first_tab = if state.recent.is_empty() { FIRST_GROUP } else { RECENT };
    let ui = Rc::new(Ui {
        app: app.clone(),
        win: win.clone(),
        all,
        index_of,
        state: RefCell::new(state),
        state_path,
        tab: Cell::new(first_tab),
        shown: RefCell::new(Vec::new()),
        model,
        selection,
        grid,
        entry,
        tab_row,
        tabs,
        tones,
        heading,
        stack,
        empty,
        preview,
        name,
        pick,
    });
    connect(&ui, &backdrop, &panel);
    ui.refresh();
    ui.show_tone();
    win.present();
    ui.entry.grab_focus();
}

fn connect(ui: &Rc<Ui>, backdrop: &gtk::Box, panel: &gtk::Box) {
    let factory = gtk::SignalListItemFactory::new();
    factory.connect_setup(|_, item| {
        let item = item.downcast_ref::<gtk::ListItem>().unwrap();
        item.set_child(Some(&gtk::Label::builder().css_classes(["cell", "emoji"]).build()));
    });
    factory.connect_bind(|_, item| {
        let item = item.downcast_ref::<gtk::ListItem>().unwrap();
        let text = item.item().and_downcast::<gtk::StringObject>().map(|s| s.string());
        if let (Some(label), Some(text)) = (item.child().and_downcast::<gtk::Label>(), text) {
            label.set_text(&text);
        }
    });
    ui.grid.set_factory(Some(&factory));

    let me = ui.clone();
    ui.grid.connect_activate(move |_, position| me.choose(position, Action::Type));
    let me = ui.clone();
    ui.selection.connect_selected_notify(move |_| me.show_selected());
    let me = ui.clone();
    ui.entry.connect_search_changed(move |_| me.refresh());

    for (i, tab) in ui.tabs.iter().enumerate() {
        let me = ui.clone();
        tab.connect_clicked(move |_| me.set_tab(i));
    }
    for (i, tone) in ui.tones.iter().enumerate() {
        let me = ui.clone();
        tone.connect_clicked(move |_| me.set_tone(i));
    }

    // Right click: favourite or not (the pointer already selected it)
    let right = gtk::GestureClick::builder().button(gdk::BUTTON_SECONDARY).build();
    let me = ui.clone();
    right.connect_pressed(move |_, _, _, _| me.toggle_favourite());
    ui.grid.add_controller(right);

    // A click beside the card closes it
    let outside = gtk::GestureClick::new();
    let (me, card, area) = (ui.clone(), panel.clone(), backdrop.clone());
    outside.connect_pressed(move |_, _, x, y| {
        let inside = area.pick(x, y, gtk::PickFlags::DEFAULT).is_some_and(|w| w == card || w.is_ancestor(&card));
        if !inside {
            me.close();
        }
    });
    backdrop.add_controller(outside);

    let keys = gtk::EventControllerKey::new();
    keys.set_propagation_phase(gtk::PropagationPhase::Capture);
    let me = ui.clone();
    keys.connect_key_pressed(move |_, key, _, mods| me.key(key, mods));
    ui.win.add_controller(keys);
}

impl Ui {
    fn query(&self) -> String {
        self.entry.text().trim().to_string()
    }

    fn indexes(&self, emoji: &[String]) -> Vec<usize> {
        emoji.iter().filter_map(|e| self.index_of.get(e.as_str()).copied()).collect()
    }

    /// Fills the grid from the search, or from the tab when there is none.
    fn refresh(&self) {
        let query = self.query();
        let tab = self.tab.get();
        let shown = if !query.is_empty() {
            crate::search::search(&self.all, &query)
        } else {
            match tab {
                RECENT => self.indexes(&self.state.borrow().recent),
                FAVOURITES => self.indexes(&self.state.borrow().favourites),
                t => (0..self.all.len()).filter(|&i| self.all[i].group == t - FIRST_GROUP).collect(),
            }
        };
        let tone = self.state.borrow().tone;
        let texts: Vec<&str> = shown.iter().map(|&i| self.all[i].with_tone(tone)).collect();
        self.model.splice(0, self.model.n_items(), &texts);
        let count = shown.len();
        *self.shown.borrow_mut() = shown;

        for (i, b) in self.tabs.iter().enumerate() {
            b.set_active(i == tab && query.is_empty());
        }
        if query.is_empty() {
            self.tab_row.remove_css_class("searching");
        } else {
            self.tab_row.add_css_class("searching");
        }
        let heading = match (query.is_empty(), tab) {
            (false, _) => format!("{count} FOUND"),
            (true, RECENT) => "RECENT".into(),
            (true, FAVOURITES) => "FAVOURITES".into(),
            (true, t) => GROUPS[t - FIRST_GROUP].name.to_uppercase(),
        };
        self.heading.set_text(&heading);
        if count == 0 {
            self.empty.set_text(&match (query.is_empty(), tab) {
                (false, _) => format!("No emoji match “{query}”."),
                (true, FAVOURITES) => {
                    "No favourites yet. Right-click an emoji, or press Ctrl+D on it, to keep it here.".into()
                }
                _ => "Nothing picked yet. What you pick shows up here.".into(),
            });
            self.stack.set_visible_child_name("empty");
        } else {
            self.stack.set_visible_child_name("grid");
            self.select(0);
        }
        self.show_selected();
    }

    fn select(&self, position: u32) {
        self.selection.set_selected(position);
        self.grid.scroll_to(position, gtk::ListScrollFlags::NONE, None);
    }

    fn selected(&self) -> Option<&Emoji> {
        let position = self.selection.selected();
        let index = *self.shown.borrow().get(position as usize)?;
        Some(&self.all[index])
    }

    fn show_selected(&self) {
        let tone = self.state.borrow().tone;
        match self.selected() {
            Some(e) => {
                self.preview.set_text(e.with_tone(tone));
                let star = if self.state.borrow().is_favourite(e.emoji) { "  ★" } else { "" };
                self.name.set_text(&format!("{}{star}", capitalise(e.name)));
            }
            None => {
                self.preview.set_text("");
                self.name.set_text("");
            }
        }
    }

    fn set_tab(&self, tab: usize) {
        self.tab.set(tab);
        if self.query().is_empty() {
            self.refresh();
        } else {
            self.entry.set_text(""); // refreshes through search-changed
        }
    }

    fn show_tone(&self) {
        let tone = self.state.borrow().tone;
        for (i, b) in self.tones.iter().enumerate() {
            b.set_active(i == tone);
        }
    }

    fn set_tone(&self, tone: usize) {
        let position = self.selection.selected();
        self.state.borrow_mut().tone = tone;
        self.save();
        self.show_tone();
        self.refresh();
        if position < self.model.n_items() {
            self.select(position);
        }
    }

    fn toggle_favourite(&self) {
        let Some(emoji) = self.selected().map(|e| e.emoji) else { return };
        self.state.borrow_mut().toggle_favourite(emoji);
        self.save();
        if self.tab.get() == FAVOURITES && self.query().is_empty() {
            self.refresh();
        } else {
            self.show_selected();
        }
    }

    fn save(&self) {
        if let Err(e) = self.state.borrow().save(&self.state_path) {
            eprintln!("emoji: could not save {}: {e}", self.state_path.display());
        }
    }

    fn choose(&self, position: u32, action: Action) {
        let Some(index) = self.shown.borrow().get(position as usize).copied() else { return };
        let e = &self.all[index];
        self.state.borrow_mut().picked(e.emoji);
        self.save();
        let emoji = e.with_tone(self.state.borrow().tone).to_string();
        *self.pick.borrow_mut() = Some(Pick { emoji, action });
        self.close();
    }

    fn close(&self) {
        self.win.set_visible(false);
        self.app.quit();
    }

    fn move_by(&self, step: i64) {
        let n = self.model.n_items() as i64;
        if n == 0 {
            return;
        }
        let now = self.selection.selected() as i64;
        let next = (now + step).clamp(0, n - 1);
        // Up from the top row and down from the bottom row stay put, rather than jumping to the ends
        if (step == -(COLUMNS as i64) && now < COLUMNS as i64)
            || (step == COLUMNS as i64 && now + step >= n && now / COLUMNS as i64 == (n - 1) / COLUMNS as i64)
        {
            return;
        }
        self.select(next as u32);
    }

    fn key(&self, key: gdk::Key, mods: gdk::ModifierType) -> glib::Propagation {
        let ctrl = mods.contains(gdk::ModifierType::CONTROL_MASK);
        let shift = mods.contains(gdk::ModifierType::SHIFT_MASK);
        let columns = COLUMNS as i64;
        match key {
            gdk::Key::Escape => self.close(),
            gdk::Key::Return | gdk::Key::KP_Enter | gdk::Key::ISO_Enter => {
                self.choose(self.selection.selected(), if shift { Action::Copy } else { Action::Type })
            }
            gdk::Key::Left => self.move_by(-1),
            gdk::Key::Right => self.move_by(1),
            gdk::Key::Up => self.move_by(-columns),
            gdk::Key::Down => self.move_by(columns),
            gdk::Key::Page_Up => self.move_by(-columns * 5),
            gdk::Key::Page_Down => self.move_by(columns * 5),
            gdk::Key::Tab => self.set_tab((self.tab.get() + 1) % self.tabs.len()),
            gdk::Key::ISO_Left_Tab => self.set_tab((self.tab.get() + self.tabs.len() - 1) % self.tabs.len()),
            gdk::Key::d | gdk::Key::D if ctrl => self.toggle_favourite(),
            gdk::Key::t | gdk::Key::T if ctrl => {
                let tone = self.state.borrow().tone;
                self.set_tone((tone + 1) % TONE_HANDS.len());
            }
            _ => return glib::Propagation::Proceed,
        }
        glib::Propagation::Stop
    }
}

fn capitalise(name: &str) -> String {
    let mut chars = name.chars();
    chars.next().map(|c| c.to_uppercase().chain(chars).collect()).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    #[test]
    fn capitalise() {
        assert_eq!(super::capitalise("grinning face"), "Grinning face");
        assert_eq!(super::capitalise("flag: Japan"), "Flag: Japan");
        assert_eq!(super::capitalise(""), "");
    }
}
