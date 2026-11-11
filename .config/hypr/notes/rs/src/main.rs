//! Notes: a scratchpad that drops down from the top of the screen you are on (Super+I), like a drop-down terminal.
//! The Rust build of notes.py, with the same behaviour and the same files; notes.py stays as the fallback.
//!
//!   hyprdots-notes                 the window, in the background until notes.sh signals it (the hyprdots-notes service)
//!   hyprdots-notes --append TEXT   add a line to the Inbox tab, with or without the window open
//!   hyprdots-notes --version       print the version (also shows the binary still links: the build script checks this)

mod app;
mod markdown;
mod notebook;
mod theme;

use gtk::glib;

fn main() -> glib::ExitCode {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("--append") => match notebook::Notebook::new(None).append(&args[2..].join(" ")) {
            Ok(path) => {
                println!("{}", path.display());
                glib::ExitCode::SUCCESS
            }
            Err(e) => {
                eprintln!("Could not add to the inbox: {e}");
                glib::ExitCode::FAILURE
            }
        },
        Some("--version") => {
            println!("hyprdots-notes {} (gtk {}.{})", env!("CARGO_PKG_VERSION"), gtk::major_version(), gtk::minor_version());
            glib::ExitCode::SUCCESS
        }
        _ => app::run(),
    }
}
