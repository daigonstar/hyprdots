"""The quick tray's copy of your notifications. swaync stays the notification daemon (popups, history, do not disturb)
but has no way to list what it holds, so this listens in on the session bus and keeps a list to draw. It only listens:
closing goes back through swaync, which makes that list and swaync's agree."""

from __future__ import annotations

import html
import re
import time

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

SERVICE = "org.freedesktop.Notifications"
RULES = [f"type='method_call',interface='{SERVICE}',member='Notify'",
         f"type='method_return',sender='{SERVICE}'",
         f"type='signal',interface='{SERVICE}',member='NotificationClosed'"]
TAG = re.compile(r"<[^>]+>")


def plain_text(text: str) -> str:
    """Notification bodies may carry a little HTML-like markup."""
    return html.unescape(TAG.sub("", text)).strip()


def parse_notify(body: GLib.Variant) -> dict:
    """The arguments of a Notify call (susssasa{sv}i)."""
    hints = body.get_child_value(6)
    image, image_path = None, ""
    for key in ("image-data", "image_data", "icon_data"):
        data = hints.lookup_value(key, None)
        if data is not None and data.get_type_string() == "(iiibiiay)":
            image = (*(data.get_child_value(i).unpack() for i in range(3)), data.get_child_value(3).unpack(),
                     data.get_child_value(6).get_data_as_bytes())
            break
    for key in ("image-path", "image_path"):
        path = hints.lookup_value(key, GLib.VariantType("s"))
        if path is not None:
            image_path = path.get_string()
            break
    urgency = hints.lookup_value("urgency", None)
    transient = hints.lookup_value("transient", None)
    return {"app": body.get_child_value(0).get_string(), "replaces": body.get_child_value(1).get_uint32(),
            "icon": image_path or body.get_child_value(2).get_string(), "image": image,
            "summary": plain_text(body.get_child_value(3).get_string()),
            "body": plain_text(body.get_child_value(4).get_string()),
            "critical": urgency is not None and urgency.unpack() == 2,
            "transient": transient is not None and bool(transient.unpack()), "time": time.time()}


def time_ago(then: float, now: float | None = None) -> str:
    minutes = int(((time.time() if now is None else now) - then) // 60)
    if minutes < 1:
        return "now"
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h" if minutes < 1440 else f"{minutes // 1440}d"


class Watcher:
    """Calls added(id, notification) and closed(id) on the main thread."""

    def __init__(self, added, closed):
        self.added, self.closed = added, closed
        self.waiting = {}  # Notify calls whose reply (with the id) has not come yet
        self.bus = None

    def start(self) -> bool:
        """Needs its own connection: one that becomes a monitor can do nothing else."""
        try:
            self.bus = Gio.DBusConnection.new_for_address_sync(
                Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None),
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
            self.bus.set_exit_on_close(False)
            self.bus.add_filter(self._message)
            self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus.Monitoring",
                               "BecomeMonitor", GLib.Variant("(asu)", (RULES, 0)), None, Gio.DBusCallFlags.NONE, 3000, None)
        except GLib.Error:
            return False
        return True

    def _message(self, _bus, message, incoming):
        if not incoming:
            return message  # our own request to start listening
        kind = message.get_message_type()
        if kind == Gio.DBusMessageType.METHOD_CALL and message.get_member() == "Notify":
            if len(self.waiting) > 64:
                self.waiting.clear()
            try:
                self.waiting[(message.get_sender(), message.get_serial())] = parse_notify(message.get_body())
            except (TypeError, ValueError, GLib.Error):
                pass
        elif kind == Gio.DBusMessageType.METHOD_RETURN:
            found = self.waiting.pop((message.get_destination(), message.get_reply_serial()), None)
            if found is not None:
                GLib.idle_add(self.added, message.get_body().get_child_value(0).get_uint32(), found)
        elif kind == Gio.DBusMessageType.SIGNAL and message.get_member() == "NotificationClosed":
            GLib.idle_add(self.closed, message.get_body().get_child_value(0).get_uint32())
        # Calls meant for swaync stop here: GDBus would answer them itself, and a monitor that sends anything is thrown off
        return None if kind == Gio.DBusMessageType.METHOD_CALL else message
