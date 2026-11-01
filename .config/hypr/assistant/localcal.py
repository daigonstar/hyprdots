"""Events kept on this PC: one .ics file that the clock popup, the assistant and Settings all read.

Nothing here talks to Google or any other server, so events added here stay on this computer. The file is
ordinary iCalendar, so it can also be imported into another calendar app. Only the standard library is used,
so the GTK3 popup, the GTK4 settings window and the assistant can all import it.
"""
import datetime
import os
import signal
import uuid

PATH = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "hypr-calendar", "local.ics")
NAME = "This PC"
REPEATS = {"": "Never", "DAILY": "Every day", "WEEKLY": "Every week", "MONTHLY": "Every month", "YEARLY": "Every year"}
POPUP_LOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "waybar-calendar.pid")


# ---- reading -------------------------------------------------------------------------------------------------
def _unescape(text):
    out, i = [], 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            out.append({"n": "\n", "N": "\n"}.get(text[i + 1], text[i + 1]))
            i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _parse_dt(value):
    """(date or naive local datetime, all_day). UTC times (…Z) become local time."""
    value = value.strip()
    if "T" not in value:
        return datetime.datetime.strptime(value[:8], "%Y%m%d").date(), True
    dt = datetime.datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        dt = dt.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
    return dt, False


def events():
    """Every event in the file, sorted by start: dicts with uid, title, start, end, all_day, repeat, notes."""
    try:
        with open(PATH, encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return []
    lines = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        elif line:
            lines.append(line)
    found, cur = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            if "DTSTART" in cur:
                try:
                    start, all_day = _parse_dt(cur["DTSTART"])
                    end = _parse_dt(cur["DTEND"])[0] if "DTEND" in cur else None
                except ValueError:
                    start = None
                if start is not None:
                    rule = dict(p.split("=", 1) for p in cur.get("RRULE", "").split(";") if "=" in p)
                    found.append({"uid": cur.get("UID", ""), "title": _unescape(cur.get("SUMMARY", "")) or "(no title)",
                                  "start": start, "end": end, "all_day": all_day, "repeat": rule.get("FREQ", ""),
                                  "notes": _unescape(cur.get("DESCRIPTION", ""))})
            cur = None
        elif cur is not None and ":" in line:
            name, _, value = line.partition(":")
            cur[name.split(";", 1)[0].upper()] = value
    found.sort(key=lambda e: (e["start"] if isinstance(e["start"], datetime.datetime)
                              else datetime.datetime.combine(e["start"], datetime.time())))
    return found


def describe(ev):
    """'Mon 3 Nov 2026, 09:00–10:00 · every week' for lists."""
    start, end = ev["start"], ev["end"]
    if ev["all_day"]:
        text = start.strftime("%a %-d %b %Y") + ", all day"
        last = end - datetime.timedelta(days=1) if end and end > start else start
        if last != start:
            text = start.strftime("%a %-d %b") + " – " + last.strftime("%a %-d %b %Y")
    else:
        text = start.strftime("%a %-d %b %Y, %H:%M") + (("–" + end.strftime("%H:%M")) if end and end != start else "")
    if ev["repeat"]:
        text += " · " + REPEATS.get(ev["repeat"], ev["repeat"].lower()).lower()
    return text


# ---- writing ------------------------------------------------------------------------------------------------
def _escape(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n").replace("\n", "\\n")


def _fold(line):
    """iCalendar lines are at most 75 octets; longer ones continue on lines starting with a space."""
    out, data = [], line.encode("utf-8")
    while len(data) > 75:
        cut = 75 if not out else 74
        while cut and (data[cut] & 0xC0) == 0x80:  # never split a UTF-8 character
            cut -= 1
        out.append(data[:cut].decode("utf-8"))
        data = data[cut:]
    out.append(data.decode("utf-8"))
    return "\r\n ".join(out)


def _fmt(value):
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y%m%dT%H%M%S")
    return value.strftime("%Y%m%d")


def _write(evs):
    os.makedirs(os.path.dirname(PATH), mode=0o700, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//hyprdots//local calendar//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{NAME}"]
    for ev in evs:
        date_param = ";VALUE=DATE" if ev["all_day"] else ""  # times without a zone are "floating": this PC's local time
        lines += ["BEGIN:VEVENT", f"UID:{ev['uid']}", f"DTSTAMP:{stamp}",
                  f"DTSTART{date_param}:{_fmt(ev['start'])}", f"DTEND{date_param}:{_fmt(ev['end'])}",
                  f"SUMMARY:{_escape(ev['title'])}"]
        if ev.get("notes"):
            lines.append(f"DESCRIPTION:{_escape(ev['notes'])}")
        if ev.get("repeat"):
            lines.append(f"RRULE:FREQ={ev['repeat']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(_fold(line) for line in lines) + "\r\n")
    os.replace(tmp, PATH)
    reload_popup()


def add(title, day, start_time=None, end_time=None, repeat="", notes="", end_day=None):
    """Adds an event and returns its uid. No times means all day; end_day lets an all-day event span several days.
    Raises ValueError with a message meant for people."""
    title = title.strip()
    if not title:
        raise ValueError("Give the event a name.")
    if repeat not in REPEATS:
        raise ValueError("Unknown repeat.")
    if start_time is None:
        last = end_day or day
        if last < day:
            raise ValueError("The last day is before the first day.")
        start, end, all_day = day, last + datetime.timedelta(days=1), True
    else:
        start = datetime.datetime.combine(day, start_time)
        end = datetime.datetime.combine(end_day or day, end_time) if end_time else start + datetime.timedelta(hours=1)
        if end <= start:
            if end_day is None and end_time:  # 22:00–01:00 runs past midnight
                end += datetime.timedelta(days=1)
            else:
                raise ValueError("The event ends before it starts.")
        all_day = False
    ev = {"uid": f"{uuid.uuid4()}@hyprdots", "title": title, "start": start, "end": end, "all_day": all_day,
          "repeat": repeat, "notes": notes.strip()}
    _write([*events(), ev])
    return ev["uid"]


def remove(uid):
    """Removes an event (every repeat of it). Returns False if it was not found."""
    evs = events()
    keep = [e for e in evs if e["uid"] != uid]
    if len(keep) == len(evs):
        return False
    _write(keep)
    return True


def reload_popup():
    """Tells an open clock popup to read the calendars again."""
    try:
        with open(POPUP_LOCK) as f:
            os.kill(int(f.read().strip()), signal.SIGUSR1)
    except (OSError, ValueError):
        pass


# ---- reading what people type --------------------------------------------------------------------------------
def parse_date(text, today=None):
    """'2026-11-03', '3/11/2026', '3 Nov', 'today', 'tomorrow' -> date. Raises ValueError."""
    text = text.strip().lower()
    today = today or datetime.date.today()
    if text in ("", "today"):
        return today
    if text == "tomorrow":
        return today + datetime.timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d %B %Y", "%d %b %Y", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    for fmt in ("%d %B", "%d %b", "%d/%m"):
        try:
            d = datetime.datetime.strptime(f"{text} {today.year}", fmt + " %Y").date()
            return d if d >= today else d.replace(year=today.year + 1)
        except ValueError:
            pass
    raise ValueError(f"'{text}' is not a date. Try 2026-11-03 or 3/11/2026.")


def parse_time(text):
    """'9', '9:30', '09.30', '14:00', '2pm', '2:30 pm' -> time. Raises ValueError."""
    raw = text.strip().lower().replace(".", ":").replace(" ", "")
    pm, am = raw.endswith("pm"), raw.endswith("am")
    raw = raw[:-2] if pm or am else raw
    try:
        h, _, m = raw.partition(":")
        hour, minute = int(h), int(m or 0)
        if pm and hour < 12:
            hour += 12
        if am and hour == 12:
            hour = 0
        return datetime.time(hour, minute)
    except ValueError:
        raise ValueError(f"'{text.strip()}' is not a time. Try 09:30 or 2pm.") from None
