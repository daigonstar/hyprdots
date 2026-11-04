// An on-screen keyboard inside the gtklock lock screen, for a touchscreen with no keyboard attached. A locked session
// shows nothing but the lock screen's own surface, so a separate keyboard app such as squeekboard cannot appear there.
// gtklock keeps the lock and checks the password: these keys only type into its password field, which is all they touch.
// Built by install/surface.sh; loaded by scripts/lock-screen.sh, which sets GTKLOCK_KEYBOARD=show when no keyboard is attached.
#include <gmodule.h>
#include <gtk/gtk.h>

G_MODULE_EXPORT const guint module_major_version = MAJOR_VERSION;
G_MODULE_EXPORT const guint module_minor_version = MINOR_VERSION;

// The start of gtklock's struct Window (include/window.h), fixed within a major version
struct Window {
	GdkMonitor *monitor;
	GtkWidget *window;
	GtkWidget *overlay;
	GtkWidget *window_box;
	GtkWidget *body_revealer;
	GtkWidget *body_grid;
	GtkWidget *input_label;
	GtkWidget *input_field;
};

#define ROWS 3
#define MAX_KEYS 10

enum page { LOWER, UPPER, SYMBOLS, MORE_SYMBOLS, PAGES };

// One string per key, separated by spaces, so that a key can be a character of more than one byte
static const char *const LAYOUT[PAGES][ROWS] = {
	[LOWER] = { "q w e r t y u i o p", "a s d f g h j k l", "z x c v b n m" },
	[UPPER] = { "Q W E R T Y U I O P", "A S D F G H J K L", "Z X C V B N M" },
	[SYMBOLS] = { "1 2 3 4 5 6 7 8 9 0", "! \" £ $ % ^ & * ( )", "- _ = + @ # ?" },
	[MORE_SYMBOLS] = { "~ ` | \\ / [ ] { } €", "< > : ; ' , ¬ ¦ ° §", "¡ ¿ « » × ÷ ·" },
};

struct keyboard {
	GtkWidget *entry;
	GtkWidget *panel;
	GtkWidget *keys[ROWS][MAX_KEYS];
	GtkWidget *shift;
	GtkWidget *mode;
	enum page page;
};

static void show_page(struct keyboard *kb, enum page page) {
	kb->page = page;
	for(int row = 0; row < ROWS; row++) {
		char **labels = g_strsplit(LAYOUT[page][row], " ", -1);
		gboolean more = TRUE;
		for(int col = 0; col < MAX_KEYS && kb->keys[row][col]; col++) {
			more = more && labels[col];
			gtk_button_set_label(GTK_BUTTON(kb->keys[row][col]), more ? labels[col] : "");
			gtk_widget_set_visible(kb->keys[row][col], more);
		}
		g_strfreev(labels);
	}
	gtk_button_set_label(GTK_BUTTON(kb->shift), page >= SYMBOLS ? (page == SYMBOLS ? "More" : "Back") : "Shift");
	gtk_button_set_label(GTK_BUTTON(kb->mode), page >= SYMBOLS ? "abc" : "123");
}

static void refocus(struct keyboard *kb) {
	gtk_entry_grab_focus_without_selecting(GTK_ENTRY(kb->entry));
}

static void type_key(GtkButton *button, struct keyboard *kb) {
	if(gtk_widget_get_sensitive(kb->entry)) {  // not while the password is being checked
		gint position = gtk_editable_get_position(GTK_EDITABLE(kb->entry));
		gtk_editable_insert_text(GTK_EDITABLE(kb->entry), gtk_button_get_label(button), -1, &position);
		gtk_editable_set_position(GTK_EDITABLE(kb->entry), position);
	}
	if(kb->page == UPPER) show_page(kb, LOWER);  // Shift lasts for one letter
	refocus(kb);
}

static void press_shift(GtkButton *button, struct keyboard *kb) {
	(void)button;
	static const enum page next[PAGES] = { [LOWER] = UPPER, [UPPER] = LOWER, [SYMBOLS] = MORE_SYMBOLS, [MORE_SYMBOLS] = SYMBOLS };
	show_page(kb, next[kb->page]);
	refocus(kb);
}

static void press_mode(GtkButton *button, struct keyboard *kb) {
	(void)button;
	show_page(kb, kb->page >= SYMBOLS ? LOWER : SYMBOLS);
	refocus(kb);
}

static void press_space(GtkButton *button, struct keyboard *kb) {
	(void)button;
	if(gtk_widget_get_sensitive(kb->entry)) {
		gint position = gtk_editable_get_position(GTK_EDITABLE(kb->entry));
		gtk_editable_insert_text(GTK_EDITABLE(kb->entry), " ", -1, &position);
		gtk_editable_set_position(GTK_EDITABLE(kb->entry), position);
	}
	refocus(kb);
}

static void press_backspace(GtkButton *button, struct keyboard *kb) {
	(void)button;
	if(gtk_widget_get_sensitive(kb->entry)) g_signal_emit_by_name(kb->entry, "backspace");
	refocus(kb);
}

static void press_enter(GtkButton *button, struct keyboard *kb) {
	(void)button;
	if(gtk_widget_get_sensitive(kb->entry)) gtk_widget_activate(kb->entry);
}

static void toggle_panel(GtkButton *button, struct keyboard *kb) {
	(void)button;
	gtk_widget_set_visible(kb->panel, !gtk_widget_get_visible(kb->panel));
	refocus(kb);
}

static GtkWidget *add_key(GtkWidget *row, const char *label, const char *name, GCallback pressed, struct keyboard *kb, gboolean grow) {
	GtkWidget *key = gtk_button_new_with_label(label);
	gtk_widget_set_name(key, name);
	gtk_widget_set_can_focus(key, FALSE);  // the password field keeps the focus, and with it a real keyboard's typing
	gtk_widget_set_hexpand(key, grow);
	g_signal_connect(key, "clicked", pressed, kb);
	gtk_box_pack_start(GTK_BOX(row), key, grow, grow, 0);
	gtk_widget_show(key);
	return key;
}

static GtkWidget *add_row(GtkWidget *panel) {
	GtkWidget *row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
	gtk_widget_set_halign(row, GTK_ALIGN_CENTER);
	gtk_box_pack_start(GTK_BOX(panel), row, FALSE, FALSE, 0);
	gtk_widget_show(row);
	return row;
}

G_MODULE_EXPORT void on_window_create(gpointer gtklock, struct Window *win) {
	(void)gtklock;
	struct keyboard *kb = g_new0(struct keyboard, 1);
	kb->entry = win->input_field;

	kb->panel = gtk_box_new(GTK_ORIENTATION_VERTICAL, 6);
	gtk_widget_set_name(kb->panel, "keyboard-panel");
	gtk_widget_set_halign(kb->panel, GTK_ALIGN_CENTER);
	gtk_widget_set_valign(kb->panel, GTK_ALIGN_END);
	gtk_widget_set_no_show_all(kb->panel, TRUE);  // gtklock shows the whole window: this stays as chosen below
	g_object_set_data_full(G_OBJECT(kb->panel), "keyboard", kb, g_free);

	static const int row_keys[ROWS] = { 10, 10, 7 };
	for(int row = 0; row < ROWS; row++) {
		GtkWidget *box = add_row(kb->panel);
		if(row == 2) kb->shift = add_key(box, "Shift", "keyboard-function", G_CALLBACK(press_shift), kb, FALSE);
		for(int col = 0; col < row_keys[row]; col++)
			kb->keys[row][col] = add_key(box, "", "keyboard-key", G_CALLBACK(type_key), kb, FALSE);
		if(row == 2) add_key(box, "⌫", "keyboard-function", G_CALLBACK(press_backspace), kb, FALSE);
	}
	GtkWidget *bottom = add_row(kb->panel);
	kb->mode = add_key(bottom, "123", "keyboard-function", G_CALLBACK(press_mode), kb, FALSE);
	GtkWidget *space = add_key(bottom, "", "keyboard-space", G_CALLBACK(press_space), kb, FALSE);
	gtk_widget_set_size_request(space, 360, -1);
	add_key(bottom, "Unlock", "keyboard-enter", G_CALLBACK(press_enter), kb, FALSE);

	show_page(kb, LOWER);
	gtk_widget_set_visible(kb->panel, g_strcmp0(g_getenv("GTKLOCK_KEYBOARD"), "show") == 0);
	gtk_overlay_add_overlay(GTK_OVERLAY(win->overlay), kb->panel);

	// Always there, so that a wrong guess about whether a keyboard is attached can never leave you unable to type
	GtkWidget *toggle = gtk_button_new_with_label("Keyboard");
	gtk_widget_set_name(toggle, "keyboard-toggle");
	gtk_widget_set_can_focus(toggle, FALSE);
	gtk_widget_set_halign(toggle, GTK_ALIGN_END);
	gtk_widget_set_valign(toggle, GTK_ALIGN_START);
	g_signal_connect(toggle, "clicked", G_CALLBACK(toggle_panel), kb);
	gtk_overlay_add_overlay(GTK_OVERLAY(win->overlay), toggle);
	gtk_widget_show(toggle);
}
