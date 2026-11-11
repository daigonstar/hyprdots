//! The window: the same as notes.py, method for method, so behaviour stays the same.
//!
//! It runs in the background as the hyprdots-notes service and shows or hides on a signal from notes.sh (SIGUSR1), so it
//! opens at once. click_away.lua sends SIGUSR2, which hides it unless it is pinned; SIGTERM saves and quits.

use crate::markdown;
use crate::notebook::{self, Notebook, State};
use crate::theme;
use gtk::prelude::*;
use gtk::{gdk, gio, glib, pango};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use serde_json::{Map, Value};
use std::cell::{Cell, RefCell};
use std::fs;
use std::io::{Read, Write};
use std::path::PathBuf;
use std::rc::Rc;
use std::time::Duration;

const WIDTH: f64 = 0.62; // of the screen
const HEIGHT: f64 = 0.55;
const SAVE_AFTER_MS: u64 = 700;
const FORMAT_AFTER_MS: u64 = 120;
const UNTITLED: &str = "New note";
const KEEP_HINT: &str = "Closing a tab deletes it. Ctrl+Shift+S saves a copy to keep";
const SIGUSR1: i32 = 10;
const SIGUSR2: i32 = 12;
const SIGTERM: i32 = 15;

const WELCOME: &str = "# Notes

Scratch paper that drops down with **Super + I**. Each tab is saved as you type, so it is still here after a restart.

- **Closing a tab deletes it.** Save a copy first if you want to keep it: **Ctrl + Shift + S**
- **Ctrl + T** new tab, **Ctrl + W** close this one, **Ctrl + Tab** the next one
- **Esc** or a click outside hides this, unless it is pinned
- **Ctrl + B** bold, **Ctrl + I** italic, **Ctrl + 1, 2, 3** headings
- [ ] **Ctrl + Enter** ticks a box like this one
- **Ctrl + +** and **Ctrl + -** change the text size

Lists carry on when you press Enter, and an empty item ends them.
";

// CSS variables, not @define-color: GTK 4.24 ignores those names here
const CSS: &str = "
window.notes { background: transparent; }
.panel { background: var(--tray_solid); color: var(--tray_text); border-radius: 0 0 16px 16px; border: 1px solid var(--tray_accent); border-top: none;
         box-shadow: 0 4px 16px rgba(0,0,0,0.5); margin: 0 12px 14px 12px; }
.panel label, .panel textview, .panel text { color: var(--tray_text); }
.bar { padding: 8px 10px 4px 10px; }
.bar button { background: none; border: none; box-shadow: none; border-radius: 8px; min-height: 30px; min-width: 30px; padding: 2px 8px; color: var(--tray_text); }
.bar button:hover { background: color-mix(in srgb, var(--tray_accent) 25%, transparent); }
.bar button:checked { background: color-mix(in srgb, var(--tray_accent) 45%, transparent); }
.tab { background: var(--tray_card); border-radius: 10px; padding: 0 2px 0 4px; }
.tab.current { background: color-mix(in srgb, var(--tray_accent) 45%, transparent); }
.tab button { min-height: 26px; min-width: 22px; padding: 0 6px; }
.tab button.close { min-width: 18px; padding: 0 4px; opacity: 0.7; }
.tab button.close:hover { opacity: 1; }
.dim { color: var(--tray_muted); font-size: 0.9em; }
textview, textview text { background: none; font-size: 1.05em; }
textview { padding: 4px 18px 14px 18px; caret-color: var(--tray_accent); }
textview text selection { background: color-mix(in srgb, var(--tray_accent) 45%, transparent); }
scrollbar { background: none; }
";
const TOUCH_CSS: &str = "
.bar button { min-height: 46px; min-width: 46px; }
.tab button { min-height: 42px; }
textview, textview text { font-size: 1.3em; }
";

fn runtime_dir() -> PathBuf {
    std::env::var_os("XDG_RUNTIME_DIR").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/tmp"))
}

pub fn ready_path() -> PathBuf {
    runtime_dir().join("hyprdots-notes.ready")
}

fn theme_path() -> PathBuf {
    notebook::home().join(".config/hypr/tray/theme.css")
}

fn gtk4_css_path() -> PathBuf {
    let config = std::env::var_os("XDG_CONFIG_HOME").filter(|c| !c.is_empty()).map(PathBuf::from);
    config.unwrap_or_else(|| notebook::home().join(".config")).join("gtk-4.0/gtk.css")
}

fn touch_mode() -> bool {
    notebook::home().join(".local/state/hyprdots/touch-mode").exists()
}

/// As Python's bool() reads a JSON value, since notes.py wrote these.
fn truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64() != Some(0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

fn rgba(text: &str) -> gdk::RGBA {
    gdk::RGBA::parse(text.trim()).unwrap_or(gdk::RGBA::new(0.0, 0.0, 0.0, 0.0))
}

/// Asked of Hyprland's own socket: the same answer as `hyprctl monitors -j`, without starting a process.
fn focused_monitor_name() -> Option<String> {
    let signature = std::env::var("HYPRLAND_INSTANCE_SIGNATURE").ok()?;
    let path = runtime_dir().join("hypr").join(signature).join(".socket.sock");
    let mut socket = std::os::unix::net::UnixStream::connect(path).ok()?;
    socket.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
    socket.write_all(b"j/monitors").ok()?;
    let mut reply = String::new();
    socket.read_to_string(&mut reply).ok()?;
    let monitors: Value = serde_json::from_str(&reply).ok()?;
    monitors.as_array()?.iter().find(|m| m["focused"] == true)?["name"].as_str().map(str::to_string)
}

fn notify(title: &str, body: &str) {
    let argv = ["notify-send", "-a", "Notes", title, body].map(std::ffi::OsStr::new);
    let _ = gio::Subprocess::newv(&argv, gio::SubprocessFlags::NONE);
}

/// One note: its file, its own text (with its own undo), and what is on disk for it.
struct Tab {
    path: PathBuf,
    saved: RefCell<String>,
    buffer: gtk::TextBuffer,
    save_timer: Cell<Option<glib::SourceId>>,
    format_timer: Cell<Option<glib::SourceId>>,
    widget: gtk::Box,
    label: gtk::Label,
}

impl Tab {
    fn text(&self) -> String {
        let (start, end) = self.buffer.bounds();
        self.buffer.text(&start, &end, true).into()
    }

    fn title(&self) -> String {
        let title = notebook::title_of(&self.text());
        if title.is_empty() { UNTITLED.into() } else { title }
    }

    fn name(&self) -> String {
        self.path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default()
    }

    fn stop_timers(&self) {
        for timer in [&self.save_timer, &self.format_timer] {
            if let Some(id) = timer.take() {
                id.remove();
            }
        }
    }
}

struct Notes {
    book: Notebook,
    state: RefCell<State>,
    tabs: RefCell<Vec<Rc<Tab>>>,
    tab: RefCell<Option<Rc<Tab>>>,
    loading: Cell<bool>,
    pinned: Cell<bool>,
    app: gtk::Application,
    win: gtk::ApplicationWindow,
    text: gtk::TextView,
    status: gtk::Label,
    strip: gtk::Box,
    pin: gtk::ToggleButton,
    table: gtk::TextTagTable,
    css: gtk::CssProvider,
    theme_css: gtk::CssProvider,
    touch_css: gtk::CssProvider,
    live_css: RefCell<Option<gtk::CssProvider>>,
    live_timer: Cell<Option<glib::SourceId>>,
    outside_timer: Cell<Option<glib::SourceId>>,
    keep: RefCell<Vec<gio::FileMonitor>>,
    _hold: gio::ApplicationHoldGuard,
}

pub fn run() -> glib::ExitCode {
    let _ = fs::remove_file(ready_path());
    let app = gtk::Application::new(Some("com.hyprdots.notes"), gio::ApplicationFlags::NON_UNIQUE);
    app.connect_activate(build);
    let argv0 = std::env::args().next().unwrap_or_else(|| "hyprdots-notes".into());
    app.run_with_args(&[argv0])
}

// ---- the window ------------------------------------------------------------------------------------------------------
fn build(app: &gtk::Application) {
    let book = Notebook::new(None);
    let state = book.load_state();
    let pinned = truthy(state.get("pinned"));
    let display = gdk::Display::default().expect("no display");

    // follows a theme override switch while open (livetheme.py): added first, as follow() runs first there
    let live = gtk::CssProvider::new();
    live.load_from_string(&theme::live_block(fs::read_to_string(gtk4_css_path()).ok().as_deref()));
    gtk::style_context_add_provider_for_display(&display, &live, gtk::STYLE_PROVIDER_PRIORITY_USER);

    let win = gtk::ApplicationWindow::builder().application(app).title("Notes").css_classes(["notes", theme::LIVE_CLASS]).build();
    win.init_layer_shell();
    win.set_namespace(Some("hyprdots-notes"));
    win.set_layer(Layer::Overlay);
    win.set_anchor(Edge::Top, true);
    win.set_exclusive_zone(-1); // from the very top of the screen, over the bar
    win.set_keyboard_mode(KeyboardMode::OnDemand);

    let (css, theme_css, touch_css) = (gtk::CssProvider::new(), gtk::CssProvider::new(), gtk::CssProvider::new());
    for (priority, provider) in [(800, &theme_css), (801, &css), (802, &touch_css)] {
        gtk::style_context_add_provider_for_display(&display, provider, priority);
    }
    css.load_from_string(CSS);

    let panel = gtk::Box::builder().orientation(gtk::Orientation::Vertical).css_classes(["panel"]).build();
    let bar = gtk::Box::builder().spacing(6).css_classes(["bar"]).build();
    let strip = gtk::Box::builder().spacing(6).build();
    bar.append(
        &gtk::ScrolledWindow::builder()
            .child(&strip)
            .hexpand(true)
            .vscrollbar_policy(gtk::PolicyType::Never)
            .hscrollbar_policy(gtk::PolicyType::Automatic)
            .propagate_natural_height(true)
            .build(),
    );
    let buttons: Vec<gtk::Button> = [
        ("tab-new-symbolic", "New tab (Ctrl+T)"),
        ("document-save-as-symbolic", "Save a copy to keep (Ctrl+Shift+S)"),
        ("edit-copy-symbolic", "Copy the whole note"),
    ]
    .iter()
    .map(|(icon, tip)| gtk::Button::builder().icon_name(*icon).tooltip_text(*tip).build())
    .collect();
    for button in &buttons {
        bar.append(button);
    }
    let pin = gtk::ToggleButton::builder()
        .icon_name("view-pin-symbolic")
        .active(pinned)
        .tooltip_text("Keep it open while you use other windows (Ctrl+P)")
        .build();
    bar.append(&pin);
    let hide = gtk::Button::builder().icon_name("go-up-symbolic").tooltip_text("Hide (Esc). Your tabs stay").build();
    bar.append(&hide);
    panel.append(&bar);

    let text = gtk::TextView::builder()
        .wrap_mode(gtk::WrapMode::WordChar)
        .hexpand(true)
        .vexpand(true)
        .accepts_tab(true)
        .top_margin(6)
        .bottom_margin(12)
        .build();
    panel.append(&gtk::ScrolledWindow::builder().child(&text).hscrollbar_policy(gtk::PolicyType::Never).vexpand(true).build());
    let status = gtk::Label::builder()
        .xalign(0.0)
        .css_classes(["dim"])
        .margin_start(20)
        .margin_bottom(10)
        .ellipsize(pango::EllipsizeMode::End)
        .build();
    panel.append(&status);
    win.set_child(Some(&panel));

    let me = Rc::new(Notes {
        book,
        state: RefCell::new(state),
        tabs: RefCell::new(Vec::new()),
        tab: RefCell::new(None),
        loading: Cell::new(false),
        pinned: Cell::new(pinned),
        app: app.clone(),
        win: win.clone(),
        text,
        status,
        strip,
        pin: pin.clone(),
        table: gtk::TextTagTable::new(),
        css,
        theme_css,
        touch_css,
        live_css: RefCell::new(Some(live)),
        live_timer: Cell::new(None),
        outside_timer: Cell::new(None),
        keep: RefCell::new(Vec::new()),
        _hold: app.hold(),
    });

    let actions: [fn(&Rc<Notes>); 3] = [Notes::new_tab, Notes::save_as, Notes::copy_all];
    for (button, action) in buttons.iter().zip(actions) {
        let me = me.clone();
        button.connect_clicked(move |_| action(&me));
    }
    let m = me.clone();
    pin.connect_toggled(move |b| m.set_pinned(b.is_active()));
    let m = me.clone();
    hide.connect_clicked(move |_| m.hide());

    let keys = gtk::EventControllerKey::new();
    keys.set_propagation_phase(gtk::PropagationPhase::Capture);
    let m = me.clone();
    keys.connect_key_pressed(move |_, keyval, _code, state| glib::Propagation::from(m.key(keyval, state)));
    win.add_controller(keys);

    me.watch(gio::File::for_path(theme_path()).monitor_file(gio::FileMonitorFlags::NONE, gio::Cancellable::NONE), |me| {
        me.load_theme()
    });
    me.watch(gio::File::for_path(gtk4_css_path()).monitor_file(gio::FileMonitorFlags::WATCH_MOVES, gio::Cancellable::NONE), |me| {
        me.live_theme_soon()
    });
    me.load_theme();
    me.zoom(None);

    let welcomed = truthy(me.state.borrow().get("welcomed"));
    if me.book.tabs().is_empty() && !welcomed {
        let _ = me.book.create(WELCOME);
        me.state.borrow_mut().insert("welcomed".into(), Value::Bool(true));
    }
    for path in me.book.tabs() {
        me.add_tab(path, false);
    }
    if me.tabs.borrow().is_empty() {
        me.add_new_note(false);
    }
    let wanted = me.state.borrow().get("current").and_then(Value::as_str).map(str::to_string);
    let current = {
        let tabs = me.tabs.borrow();
        tabs.iter().find(|t| Some(t.name()) == wanted).unwrap_or_else(|| tabs.last().unwrap()).clone()
    };
    me.select(&current);

    let dir = me.book.dir.clone();
    me.watch(gio::File::for_path(dir).monitor_directory(gio::FileMonitorFlags::WATCH_MOVES, gio::Cancellable::NONE), |me| {
        me.outside_change_soon()
    });
    let actions: [(i32, fn(&Rc<Notes>)); 3] = [(SIGUSR1, Notes::toggle), (SIGUSR2, Notes::click_away), (SIGTERM, Notes::quit_saving)];
    for (number, action) in actions {
        let me = me.clone();
        glib_unix::unix_signal_add_local(number, move || {
            action(&me);
            glib::ControlFlow::Continue
        });
    }
    let _ = fs::write(ready_path(), "");
}

impl Notes {
    fn watch(self: &Rc<Self>, monitor: Result<gio::FileMonitor, glib::Error>, then: fn(&Rc<Notes>)) {
        let Ok(monitor) = monitor else { return };
        let me = Rc::downgrade(self);
        monitor.connect_changed(move |_, _, _, _| {
            if let Some(me) = me.upgrade() {
                then(&me);
            }
        });
        self.keep.borrow_mut().push(monitor);
    }

    fn load_theme(self: &Rc<Self>) {
        let theme_text = fs::read_to_string(theme_path()).ok();
        let colours = theme::colours(theme_text.as_deref());
        let solid = rgba(theme::get(&colours, "tray_bg")).with_alpha(1.0); // solid, so notes read well over anything
        let mut names: Vec<_> = colours.iter().filter(|(k, _)| k != "tray_solid").cloned().collect();
        names.push(("tray_solid".into(), solid.to_string()));
        self.theme_css.load_from_string(&theme::variables_css(&names, theme_text.as_deref()));
        self.touch_css.load_from_string(if touch_mode() { TOUCH_CSS } else { "" });
        self.make_tags(&colours);
        for tab in self.tabs.borrow().clone() {
            self.format(&tab);
        }
    }

    /// gtk.css is written in a few steps: read it once they are done.
    fn live_theme_soon(self: &Rc<Self>) {
        if let Some(id) = self.live_timer.take() {
            id.remove();
        }
        let me = self.clone();
        self.live_timer.set(Some(glib::timeout_add_local_once(Duration::from_millis(250), move || {
            me.live_timer.take();
            let display = gdk::Display::default().unwrap();
            if let Some(old) = me.live_css.borrow_mut().take() {
                gtk::style_context_remove_provider_for_display(&display, &old);
            }
            let provider = gtk::CssProvider::new();
            provider.load_from_string(&theme::live_block(fs::read_to_string(gtk4_css_path()).ok().as_deref()));
            gtk::style_context_add_provider_for_display(&display, &provider, gtk::STYLE_PROVIDER_PRIORITY_USER);
            *me.live_css.borrow_mut() = Some(provider);
        })));
    }

    fn make_tags(&self, c: &[(String, String)]) {
        let (accent, muted, card) =
            (rgba(theme::get(c, "tray_accent")), rgba(theme::get(c, "tray_muted")), rgba(theme::get(c, "tray_card")));
        let tag = |name: &str| {
            self.table.lookup(name).unwrap_or_else(|| {
                let tag = gtk::TextTag::new(Some(name));
                self.table.add(&tag);
                tag
            })
        };
        let bold = 700i32; // pango::Weight::Bold
        let t = tag("h1");
        t.set_property("weight", bold);
        t.set_property("scale", 1.6f64);
        t.set_property("foreground-rgba", &accent);
        let t = tag("h2");
        t.set_property("weight", bold);
        t.set_property("scale", 1.35f64);
        t.set_property("foreground-rgba", &accent);
        let t = tag("h3");
        t.set_property("weight", bold);
        t.set_property("scale", 1.15f64);
        tag("bold").set_property("weight", bold);
        tag("italic").set_property("style", pango::Style::Italic);
        let t = tag("strike");
        t.set_property("strikethrough", true);
        t.set_property("foreground-rgba", &muted);
        let t = tag("code");
        t.set_property("family", "monospace");
        t.set_property("background-rgba", &card);
        let t = tag("fence");
        t.set_property("family", "monospace");
        t.set_property("paragraph-background-rgba", &card);
        let t = tag("quote");
        t.set_property("style", pango::Style::Italic);
        t.set_property("foreground-rgba", &muted);
        t.set_property("left-margin", 24i32);
        tag("rule").set_property("foreground-rgba", &muted);
        let t = tag("bullet");
        t.set_property("foreground-rgba", &accent);
        t.set_property("weight", bold);
        let t = tag("box");
        t.set_property("foreground-rgba", &accent);
        t.set_property("family", "monospace");
        let t = tag("done");
        t.set_property("strikethrough", true);
        t.set_property("foreground-rgba", &muted);
        let t = tag("link");
        t.set_property("foreground-rgba", &accent);
        t.set_property("underline", pango::Underline::Single);
    }

    // ---- showing and hiding --------------------------------------------------------------------------------------
    fn toggle(self: &Rc<Self>) {
        if self.win.is_visible() { self.hide() } else { self.show() }
    }

    /// On the screen you are on, sized to it. It takes the keyboard as it opens, so you can type straight away; pinned,
    /// it gives it back a moment later so you can type in other windows too, and a click on it gets it back.
    fn show(self: &Rc<Self>) {
        let display = gdk::Display::default().unwrap();
        let name = focused_monitor_name();
        let monitors = display.monitors();
        let mut chosen: Option<gdk::Monitor> = None;
        for i in 0..monitors.n_items() {
            let Some(monitor) = monitors.item(i).and_downcast::<gdk::Monitor>() else { continue };
            if monitor.connector().map(|c| c.to_string()) == name || chosen.is_none() {
                chosen = Some(monitor);
            }
        }
        if let Some(monitor) = chosen {
            self.win.set_monitor(Some(&monitor));
            let g = monitor.geometry();
            self.win.set_default_size(
                520.max((g.width() as f64 * WIDTH) as i32),
                360.max((g.height() as f64 * HEIGHT) as i32),
            );
        }
        self.touch_css.load_from_string(if touch_mode() { TOUCH_CSS } else { "" });
        self.win.set_keyboard_mode(KeyboardMode::Exclusive);
        self.win.set_visible(true);
        self.win.present();
        self.text.grab_focus();
        if self.pinned.get() {
            let me = self.clone();
            glib::timeout_add_local_once(Duration::from_millis(400), move || me.share_keyboard());
        }
    }

    fn share_keyboard(&self) {
        if self.pinned.get() && self.win.is_visible() {
            self.win.set_keyboard_mode(KeyboardMode::OnDemand);
        }
    }

    fn hide(self: &Rc<Self>) {
        self.save_all();
        self.win.set_visible(false);
    }

    fn click_away(self: &Rc<Self>) {
        if !self.pinned.get() && self.win.is_visible() {
            self.hide();
        }
    }

    fn set_pinned(self: &Rc<Self>, pinned: bool) {
        self.pinned.set(pinned);
        if self.win.is_visible() {
            self.win.set_keyboard_mode(if pinned { KeyboardMode::OnDemand } else { KeyboardMode::Exclusive });
        }
        self.save_state();
    }

    fn quit_saving(self: &Rc<Self>) {
        self.save_all();
        let _ = fs::remove_file(ready_path());
        self.app.quit();
    }

    // ---- tabs ----------------------------------------------------------------------------------------------------
    fn current(&self) -> Option<Rc<Tab>> {
        self.tab.borrow().clone()
    }

    fn is_current(&self, tab: &Rc<Tab>) -> bool {
        self.tab.borrow().as_ref().is_some_and(|t| Rc::ptr_eq(t, tab))
    }

    fn add_new_note(self: &Rc<Self>, select: bool) {
        match self.book.create("") {
            Ok(path) => {
                self.add_tab(path, select);
            }
            Err(e) => self.status(&format!("Could not make a note: {e}")),
        }
    }

    fn add_tab(self: &Rc<Self>, path: PathBuf, select: bool) -> Rc<Tab> {
        let text = self.book.read(&path);
        let buffer = gtk::TextBuffer::new(Some(&self.table));
        buffer.set_text(&text);
        let widget = gtk::Box::builder().css_classes(["tab"]).build();
        let name = gtk::Button::builder().tooltip_text(KEEP_HINT).build();
        let label = gtk::Label::builder().max_width_chars(18).ellipsize(pango::EllipsizeMode::End).build();
        let tab = Rc::new(Tab {
            path,
            saved: RefCell::new(text),
            buffer,
            save_timer: Cell::new(None),
            format_timer: Cell::new(None),
            widget,
            label,
        });
        tab.label.set_label(&tab.title());
        name.set_child(Some(&tab.label));
        let close = gtk::Button::builder()
            .icon_name("window-close-symbolic")
            .css_classes(["close"])
            .tooltip_text("Close this tab and delete the note (Ctrl+W)")
            .build();
        let middle = gtk::GestureClick::builder().button(2).build(); // a middle click closes a tab, as in a browser

        let (me, t) = (self.clone(), Rc::downgrade(&tab));
        tab.buffer.connect_changed(move |_| {
            if let Some(t) = t.upgrade() {
                me.edited(&t);
            }
        });
        let (me, t) = (self.clone(), tab.clone());
        name.connect_clicked(move |_| me.select(&t));
        let (me, t) = (self.clone(), tab.clone());
        close.connect_clicked(move |_| me.close_tab(&t));
        let (me, t) = (self.clone(), tab.clone());
        middle.connect_released(move |_, _, _, _| me.close_tab(&t));
        tab.widget.add_controller(middle);
        tab.widget.append(&name);
        tab.widget.append(&close);
        self.strip.append(&tab.widget);
        self.tabs.borrow_mut().push(tab.clone());
        self.format(&tab);
        if select {
            self.select(&tab);
        }
        tab
    }

    fn select(self: &Rc<Self>, tab: &Rc<Tab>) {
        if let Some(old) = self.current().filter(|old| !Rc::ptr_eq(old, tab)) {
            self.remember_cursor();
            old.widget.remove_css_class("current");
            self.save(&old);
        }
        *self.tab.borrow_mut() = Some(tab.clone());
        tab.widget.add_css_class("current");
        self.text.set_buffer(Some(&tab.buffer));
        let count = tab.buffer.char_count();
        let cursor = self.state.borrow().get("cursors").and_then(|c| c.get(tab.name())).and_then(Value::as_i64);
        let cursor = cursor.map_or(count, |c| c.min(count as i64) as i32);
        tab.buffer.place_cursor(&tab.buffer.iter_at_offset(cursor));
        let (me, t) = (self.clone(), tab.clone());
        glib::idle_add_local_once(move || {
            if me.text.buffer() == t.buffer {
                // another tab may have been picked since
                me.text.scroll_to_mark(&t.buffer.get_insert(), 0.2, false, 0.0, 0.0);
            }
        });
        self.text.grab_focus();
        self.status("Saved");
        self.save_state();
    }

    fn new_tab(self: &Rc<Self>) {
        self.add_new_note(true);
    }

    /// Deletes the note. The last tab closed leaves a fresh empty one, so there is always somewhere to type.
    fn close_tab(self: &Rc<Self>, tab: &Rc<Tab>) {
        tab.stop_timers();
        self.save(tab); // so what goes to the bin is all of it
        let Some(at) = self.tabs.borrow().iter().position(|t| Rc::ptr_eq(t, tab)) else { return };
        self.tabs.borrow_mut().remove(at);
        self.strip.remove(&tab.widget);
        self.book.close(&tab.path);
        if let Some(Value::Object(cursors)) = self.state.borrow_mut().get_mut("cursors") {
            cursors.remove(&tab.name());
        }
        if self.tabs.borrow().is_empty() {
            self.add_new_note(false);
        }
        if self.is_current(tab) {
            *self.tab.borrow_mut() = None;
            let next = {
                let tabs = self.tabs.borrow();
                tabs.get(at.min(tabs.len().saturating_sub(1))).cloned()
            };
            if let Some(next) = next {
                self.select(&next);
            }
        } else {
            self.save_state();
        }
    }

    fn step(self: &Rc<Self>, by: i64) {
        let next = {
            let tabs = self.tabs.borrow();
            let Some(current) = self.current() else { return };
            let Some(at) = tabs.iter().position(|t| Rc::ptr_eq(t, &current)) else { return };
            tabs[(at as i64 + by).rem_euclid(tabs.len() as i64) as usize].clone()
        };
        self.select(&next);
    }

    // ---- saving --------------------------------------------------------------------------------------------------
    fn edited(self: &Rc<Self>, tab: &Rc<Tab>) {
        if self.loading.get() {
            return;
        }
        if self.is_current(tab) {
            self.status("Editing");
        }
        tab.stop_timers();
        let (me, t) = (self.clone(), tab.clone());
        tab.save_timer.set(Some(glib::timeout_add_local_once(Duration::from_millis(SAVE_AFTER_MS), move || {
            t.save_timer.take();
            me.save(&t);
        })));
        let (me, t) = (self.clone(), tab.clone());
        tab.format_timer.set(Some(glib::timeout_add_local_once(Duration::from_millis(FORMAT_AFTER_MS), move || {
            t.format_timer.take();
            me.format(&t);
        })));
    }

    fn save(self: &Rc<Self>, tab: &Rc<Tab>) {
        if let Some(id) = tab.save_timer.take() {
            id.remove();
        }
        let text = tab.text();
        let listed = self.tabs.borrow().iter().any(|t| Rc::ptr_eq(t, tab));
        if listed && (text != *tab.saved.borrow() || !tab.path.exists()) {
            if let Err(e) = self.book.write(&tab.path, &text) {
                self.status(&format!("Could not save: {e}"));
                return;
            }
            *tab.saved.borrow_mut() = text;
        }
        if self.is_current(tab) {
            self.status("Saved");
        }
    }

    fn save_all(self: &Rc<Self>) {
        self.remember_cursor();
        for tab in self.tabs.borrow().clone() {
            self.save(&tab);
        }
        self.save_state();
    }

    fn outside_change_soon(self: &Rc<Self>) {
        if let Some(id) = self.outside_timer.take() {
            id.remove();
        }
        let me = self.clone();
        self.outside_timer.set(Some(glib::timeout_add_local_once(Duration::from_millis(150), move || {
            me.outside_timer.take();
            me.outside_change();
        })));
    }

    /// Another program changed or added a note (notes.sh --append, say): show it, unless you have edits here it would
    /// overwrite.
    fn outside_change(self: &Rc<Self>) {
        let known: Vec<PathBuf> = self.tabs.borrow().iter().map(|t| t.path.clone()).collect();
        for path in self.book.tabs() {
            if !known.contains(&path) {
                self.add_tab(path, false);
            }
        }
        for tab in self.tabs.borrow().clone() {
            if !tab.path.exists() {
                continue;
            }
            let disk = self.book.read(&tab.path);
            let saved = tab.saved.borrow().clone();
            if disk != saved && tab.text() == saved {
                let offset = tab.buffer.cursor_position();
                *tab.saved.borrow_mut() = disk.clone();
                self.loading.set(true);
                tab.buffer.set_text(&disk);
                self.loading.set(false);
                tab.buffer.place_cursor(&tab.buffer.iter_at_offset(offset.min(tab.buffer.char_count())));
                self.format(&tab);
            }
        }
    }

    /// A copy to keep, as Markdown or plain text, anywhere. The tab stays as it is. The file chooser is a normal window,
    /// which would be under this one, so this hides until it is done.
    fn save_as(self: &Rc<Self>) {
        let Some(tab) = self.current() else { return };
        self.save(&tab);
        let dialog = gtk::FileDialog::builder()
            .title("Save a copy to keep")
            .initial_name(notebook::file_name(&tab.title()))
            .initial_folder(&gio::File::for_path(notebook::home().join("Documents")))
            .build();
        self.win.set_visible(false);
        let me = self.clone();
        dialog.save(None::<&gtk::Window>, gio::Cancellable::NONE, move |result| {
            if let Some(path) = result.ok().and_then(|f| f.path()) {
                match fs::write(&path, tab.text()) {
                    Ok(()) => notify("Saved a copy", &path.to_string_lossy()),
                    Err(e) => notify("Could not save the copy", &e.to_string()),
                }
            }
            me.show();
        });
    }

    fn copy_all(self: &Rc<Self>) {
        let Some(tab) = self.current() else { return };
        self.win.clipboard().set_text(&tab.text());
        self.status("Copied the whole note");
    }

    fn status(&self, word: &str) {
        let Some(tab) = self.current() else { return };
        let words = tab.text().split_whitespace().count();
        let s = if words == 1 { "" } else { "s" };
        self.status.set_label(&format!("{word}  ·  {words} word{s}  ·  {KEEP_HINT}"));
    }

    fn remember_cursor(&self) {
        let Some(tab) = self.current() else { return };
        let mut state = self.state.borrow_mut();
        let cursors = state.entry("cursors").or_insert_with(|| Value::Object(Map::new()));
        if !cursors.is_object() {
            *cursors = Value::Object(Map::new());
        }
        cursors.as_object_mut().unwrap().insert(tab.name(), Value::from(tab.buffer.cursor_position()));
    }

    fn save_state(&self) {
        let names: Vec<String> = self.tabs.borrow().iter().map(|t| t.name()).collect();
        let current = self.current().map(|t| t.name()).unwrap_or_default();
        let mut state = self.state.borrow_mut();
        let cursors: Map<String, Value> = match state.get("cursors") {
            Some(Value::Object(c)) => c.iter().filter(|(k, _)| names.contains(k)).map(|(k, v)| (k.clone(), v.clone())).collect(),
            _ => Map::new(),
        };
        state.insert("tabs".into(), Value::from(names));
        state.insert("current".into(), Value::from(current));
        state.insert("pinned".into(), Value::from(self.pinned.get()));
        state.insert("cursors".into(), Value::Object(cursors));
        let _ = self.book.save_state(&state);
    }

    // ---- Markdown ------------------------------------------------------------------------------------------------
    fn format(&self, tab: &Rc<Tab>) {
        let buffer = &tab.buffer;
        let (start, end) = buffer.bounds();
        buffer.remove_all_tags(&start, &end);
        for (a, b, name) in markdown::spans(&tab.text()) {
            buffer.apply_tag_by_name(name, &buffer.iter_at_offset(a as i32), &buffer.iter_at_offset(b as i32));
        }
        tab.label.set_label(&tab.title());
    }

    /// (start, end) of the line the cursor is on.
    fn line(buffer: &gtk::TextBuffer) -> (gtk::TextIter, gtk::TextIter) {
        let mut start = buffer.iter_at_mark(&buffer.get_insert());
        start.set_line_offset(0);
        let mut end = start;
        if !end.ends_line() {
            end.forward_to_line_end();
        }
        (start, end)
    }

    fn line_text(buffer: &gtk::TextBuffer) -> String {
        let (start, end) = Self::line(buffer);
        buffer.text(&start, &end, true).into()
    }

    fn replace_line(buffer: &gtk::TextBuffer, text: &str) {
        let (mut start, mut end) = Self::line(buffer);
        buffer.begin_user_action();
        buffer.delete(&mut start, &mut end);
        buffer.insert(&mut start, text);
        buffer.end_user_action();
    }

    fn enter(&self) -> bool {
        let Some(tab) = self.current() else { return false };
        let buffer = &tab.buffer;
        if !buffer.iter_at_mark(&buffer.get_insert()).ends_line() {
            return false;
        }
        let (prefix, clear) = markdown::next_item(&Self::line_text(buffer));
        let Some(prefix) = prefix else { return false };
        if clear {
            Self::replace_line(buffer, "");
        } else {
            buffer.insert_at_cursor(&format!("\n{prefix}"));
        }
        self.text.scroll_mark_onscreen(&buffer.get_insert());
        true
    }

    fn wrap_selection(&self, mark: &str) {
        let Some(tab) = self.current() else { return };
        let buffer = &tab.buffer;
        let Some((mut a, mut b)) = buffer.selection_bounds() else {
            buffer.insert_at_cursor(&mark.repeat(2));
            let mut here = buffer.iter_at_mark(&buffer.get_insert());
            here.backward_chars(mark.chars().count() as i32);
            buffer.place_cursor(&here);
            return;
        };
        let (text, offset) = (buffer.text(&a, &b, true), a.offset());
        buffer.begin_user_action();
        buffer.delete(&mut a, &mut b);
        buffer.insert(&mut buffer.iter_at_offset(offset), &markdown::wrap(&text, mark));
        buffer.end_user_action();
    }

    /// by: a step, Some(0) to reset, None to apply the saved size.
    fn zoom(&self, by: Option<f64>) {
        let size = self.state.borrow().get("zoom").and_then(Value::as_f64).unwrap_or(1.0);
        let size = match by {
            Some(b) if b == 0.0 => 1.0,
            Some(b) => (size + b).clamp(0.7, 2.5),
            None => size,
        };
        self.state.borrow_mut().insert("zoom".into(), Value::from(size));
        self.css.load_from_string(&format!("{CSS}textview, textview text {{ font-size: {:.2}em; }}\n", 1.05 * size));
        if by.is_some() {
            self.save_state();
        }
    }

    fn key(self: &Rc<Self>, keyval: gdk::Key, state: gdk::ModifierType) -> bool {
        let ctrl = state.contains(gdk::ModifierType::CONTROL_MASK);
        let shift = state.contains(gdk::ModifierType::SHIFT_MASK);
        let alt = state.contains(gdk::ModifierType::ALT_MASK);
        let key = keyval.name().map(|k| k.to_string()).unwrap_or_default();
        if key == "Escape" {
            self.hide();
            return true;
        }
        if let (true, Ok(n @ 1..=9)) = (alt, key.parse::<usize>()) {
            // Alt+1..9: that tab
            let tab = self.tabs.borrow().get(n - 1).cloned();
            if let Some(tab) = tab {
                self.select(&tab);
            }
            return true;
        }
        if ctrl {
            if key == "Tab" || key == "ISO_Left_Tab" {
                self.step(if shift || key == "ISO_Left_Tab" { -1 } else { 1 });
                return true;
            }
            if shift && key.to_lowercase() == "s" {
                self.save_as();
                return true;
            }
            match key.as_str() {
                "t" | "n" => self.new_tab(),
                "w" => {
                    if let Some(tab) = self.current() {
                        self.close_tab(&tab);
                    }
                }
                "s" => {
                    if let Some(tab) = self.current() {
                        self.save(&tab);
                    }
                }
                "p" => self.pin.set_active(!self.pin.is_active()),
                "b" => self.wrap_selection("**"),
                "i" => self.wrap_selection("*"),
                "plus" | "equal" => self.zoom(Some(0.1)),
                "minus" => self.zoom(Some(-0.1)),
                "0" => self.zoom(Some(0.0)),
                "Page_Up" => self.step(-1),
                "Page_Down" => self.step(1),
                "1" | "2" | "3" => self.heading(key.parse().unwrap()),
                "Return" | "KP_Enter" => self.toggle_box(),
                _ => return false,
            }
            return true;
        }
        if (key == "Return" || key == "KP_Enter") && !shift && self.text.has_focus() {
            return self.enter();
        }
        false
    }

    fn heading(&self, level: usize) {
        let Some(tab) = self.current() else { return };
        Self::replace_line(&tab.buffer, &markdown::heading(&Self::line_text(&tab.buffer), level));
    }

    fn toggle_box(&self) {
        let Some(tab) = self.current() else { return };
        Self::replace_line(&tab.buffer, &markdown::toggle_box(&Self::line_text(&tab.buffer)));
    }
}
