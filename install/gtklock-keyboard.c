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
#define HALVES 2
#define MAX_KEYS 5  // in a row's half

enum page { LOWER, UPPER, NUMBERS, SYMBOLS, PAGES };

// One string per key, separated by spaces, so that a key can be a character of more than one byte. The same layout as the
// desktop's and the login screen's: install/tests/test_keyboards.py checks they agree.
static const char *const LAYOUT[PAGES][HALVES][ROWS] = {
	[LOWER] = { { "q w e r t", "a s d f g", "z x c v" }, { "y u i o p", "h j k l '", "b n m ," } },
	[UPPER] = { { "Q W E R T", "A S D F G", "Z X C V" }, { "Y U I O P", "H J K L '", "B N M ," } },
	[NUMBERS] = { { "1 2 3 4 5", "@ # $ % &", ", \" ' :" }, { "6 7 8 9 0", "- _ + ( )", "; ! ? /" } },
	[SYMBOLS] = { { "~ ` | · √", "© ® £ € ¥", "\\ / < >" }, { "π τ ÷ × ¶", "^ ° * { }", "= [ ] ¬" } },
};

struct keyboard {
	GtkWidget *entry;
	GtkWidget *panel;
	GtkWidget *keys[HALVES][ROWS][MAX_KEYS];
	GtkWidget *shift;
	GtkWidget *mode;
	enum page page;
};

static void show_page(struct keyboard *kb, enum page page) {
	kb->page = page;
	for(int half = 0; half < HALVES; half++) for(int row = 0; row < ROWS; row++) {
		char **labels = g_strsplit(LAYOUT[page][half][row], " ", -1);
		gboolean more = TRUE;
		for(int col = 0; col < MAX_KEYS && kb->keys[half][row][col]; col++) {
			more = more && labels[col];
			gtk_button_set_label(GTK_BUTTON(kb->keys[half][row][col]), more ? labels[col] : "");
			gtk_widget_set_visible(kb->keys[half][row][col], more);
		}
		g_strfreev(labels);
	}
	gtk_button_set_label(GTK_BUTTON(kb->shift), page >= NUMBERS ? (page == NUMBERS ? "*/=" : "123") : "\u21e7");
	gtk_button_set_label(GTK_BUTTON(kb->mode), page >= NUMBERS ? "ABC" : "123");
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
	static const enum page next[PAGES] = { [LOWER] = UPPER, [UPPER] = LOWER, [NUMBERS] = SYMBOLS, [SYMBOLS] = NUMBERS };
	show_page(kb, next[kb->page]);
	refocus(kb);
}

static void press_mode(GtkButton *button, struct keyboard *kb) {
	(void)button;
	show_page(kb, kb->page >= NUMBERS ? LOWER : NUMBERS);
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

static void add_gap(GtkWidget *row, int width) {
	GtkWidget *gap = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
	gtk_widget_set_size_request(gap, width, -1);
	gtk_box_pack_start(GTK_BOX(row), gap, FALSE, FALSE, 0);
	gtk_widget_show(gap);
}

static GtkWidget *add_half(GtkWidget *row, gboolean start) {
	GtkWidget *half = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
	gtk_widget_set_halign(half, start ? GTK_ALIGN_END : GTK_ALIGN_START);
	gtk_box_pack_start(GTK_BOX(row), half, TRUE, TRUE, 0);
	gtk_widget_show(half);
	return half;
}

static GtkWidget *add_row(GtkWidget *panel) {
	GtkWidget *row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
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
	gtk_widget_set_halign(kb->panel, GTK_ALIGN_FILL);
	gtk_widget_set_valign(kb->panel, GTK_ALIGN_END);
	gtk_widget_set_no_show_all(kb->panel, TRUE);  // gtklock shows the whole window: this stays as chosen below
	g_object_set_data_full(G_OBJECT(kb->panel), "keyboard", kb, g_free);

	// Split in two for the thumbs on a wide screen, as the desktop's is
	GdkRectangle screen;
	gdk_monitor_get_geometry(win->monitor, &screen);
	int gap = screen.width > screen.height * 6 / 5 ? MAX(0, screen.width - 1000) : 6;

	static const int half_keys[HALVES][ROWS] = { { 5, 5, 4 }, { 5, 5, 4 } };
	for(int row = 0; row < ROWS; row++) {
		GtkWidget *box = add_row(kb->panel);
		GtkWidget *left = add_half(box, TRUE);
		add_gap(box, gap);
		GtkWidget *right = add_half(box, FALSE);
		if(row == 2) kb->shift = add_key(left, "", "keyboard-function", G_CALLBACK(press_shift), kb, FALSE);
		for(int col = 0; col < half_keys[0][row]; col++)
			kb->keys[0][row][col] = add_key(left, "", "keyboard-key", G_CALLBACK(type_key), kb, FALSE);
		for(int col = 0; col < half_keys[1][row]; col++)
			kb->keys[1][row][col] = add_key(right, "", "keyboard-key", G_CALLBACK(type_key), kb, FALSE);
		if(row == 2) add_key(right, "\u232b", "keyboard-function", G_CALLBACK(press_backspace), kb, FALSE);
	}
	GtkWidget *bottom = add_row(kb->panel);
	GtkWidget *left = add_half(bottom, TRUE);
	add_gap(bottom, gap);
	GtkWidget *right = add_half(bottom, FALSE);
	kb->mode = add_key(left, "123", "keyboard-function", G_CALLBACK(press_mode), kb, FALSE);
	add_key(left, "Hide", "keyboard-function", G_CALLBACK(toggle_panel), kb, FALSE);
	// So that each half ends level with the rows above
	gtk_widget_set_size_request(add_key(left, "", "keyboard-space", G_CALLBACK(press_space), kb, FALSE), 207, -1);
	gtk_widget_set_size_request(add_key(right, "", "keyboard-space", G_CALLBACK(press_space), kb, FALSE), 246, -1);
	add_key(right, ".", "keyboard-key", G_CALLBACK(type_key), kb, FALSE);
	add_key(right, "Unlock", "keyboard-enter", G_CALLBACK(press_enter), kb, FALSE);

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
