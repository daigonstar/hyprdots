//! Emoji picker (Super+.): search or browse, and the emoji you pick is copied and typed into the window you were in.
//! Recent picks, favourites and a skin tone are remembered. Replaces rofimoji, which scripts/emoji.sh still falls back to.
//!
//!   hyprdots-emoji             the picker
//!   hyprdots-emoji --version   print the version (also shows the binary still links: the build script checks this)

mod app;
mod data;
mod search;
mod state;
mod theme;

use app::{Action, Pick};
use gtk::glib;
use std::cell::RefCell;
use std::process::Command;
use std::rc::Rc;
use std::time::Duration;

fn main() -> glib::ExitCode {
    if std::env::args().nth(1).as_deref() == Some("--version") {
        println!(
            "hyprdots-emoji {} (gtk {}.{})",
            env!("CARGO_PKG_VERSION"),
            gtk::major_version(),
            gtk::minor_version()
        );
        return glib::ExitCode::SUCCESS;
    }
    let pick = Rc::new(RefCell::new(None));
    let code = app::run(pick.clone());
    if let Some(p) = pick.borrow_mut().take() {
        deliver(p);
    }
    code
}

/// What the picker starts must not inherit the layer-shell preload that emoji.sh gives the picker itself.
fn command(program: &str) -> Command {
    let mut c = Command::new(program);
    c.env_remove("LD_PRELOAD");
    c
}

/// Every pick goes on the clipboard, and Enter or a click also types it. Some apps (Electron ones, such as the Claude
/// app) ignore what wtype types, so Ctrl+V is always there as well.
fn deliver(pick: Pick) {
    let copied = command("wl-copy").arg("--").arg(&pick.emoji).status().is_ok_and(|s| s.success());
    if pick.action == Action::Type {
        // The window you were in gets the keyboard back once the picker has gone
        std::thread::sleep(Duration::from_millis(120));
        if command("wtype").arg("--").arg(&pick.emoji).status().is_ok_and(|s| s.success()) {
            return;
        }
    }
    let (title, body) = match (copied, pick.action) {
        (true, Action::Copy) => (format!("{} copied", pick.emoji), "Paste it with Ctrl+V"),
        (true, Action::Type) => {
            (format!("{} copied", pick.emoji), "It could not be typed here (is wtype installed?): paste it with Ctrl+V")
        }
        (false, Action::Copy) => ("Emoji picker".to_string(), "Could not copy it: needs wl-clipboard"),
        (false, Action::Type) => {
            ("Emoji picker".to_string(), "Could not type or copy it: needs wtype and wl-clipboard")
        }
    };
    let _ = command("notify-send").args(["-a", "Emoji picker", "-t", "2500", "--", &title, body]).status();
}
