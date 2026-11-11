"""The player's own rulebooks, for the Dungeon Master to look things up in.

A PDF is read once with pdftotext and its text kept in a search index in the state folder, on this PC only. Nothing is
uploaded, the PDF itself is not copied, and this lives apart from the campaign so a new game keeps the books. PDFs that
are locked against copying text are refused, not worked around.
"""
import hashlib
import os
import re
import sqlite3
import subprocess
import time

DIR = [None]    # set by attach()
CHUNK_CHARS = 1000
RESULT_CHARS = 900


class BookError(Exception):
    """Why a book could not be added, in words for the player."""


def attach(state_dir):
    DIR[0] = os.path.join(state_dir, "dnd_library")


def _db():
    os.makedirs(DIR[0], mode=0o700, exist_ok=True)
    db = sqlite3.connect(os.path.join(DIR[0], "library.sqlite"), timeout=30)
    db.execute("CREATE TABLE IF NOT EXISTS books (id INTEGER PRIMARY KEY, title TEXT, file TEXT, pages INTEGER, passages INTEGER, sha TEXT UNIQUE, added REAL)")
    db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(book_id UNINDEXED, page UNINDEXED, text, tokenize='porter unicode61')")
    return db


def _sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _title(path):
    """The PDF's own title if it has a sensible one, otherwise its file name."""
    try:
        info = subprocess.run(["pdfinfo", path], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        info = ""
    found = re.search(r"^Title:\s*(.+)$", info, re.M)
    title = found.group(1).strip() if found else ""
    if len(title) < 3 or title.lower().startswith(("untitled", "microsoft")) or title.lower().endswith((".pdf", ".indd")):
        title = re.sub(r"[_-]+", " ", os.path.splitext(os.path.basename(path))[0]).strip()
    return title


def extract_pages(path):
    """The text of each page. Raises BookError in plain words if it cannot be read."""
    try:
        done = subprocess.run(["pdftotext", "-enc", "UTF-8", path, "-"], capture_output=True, timeout=600)
    except FileNotFoundError:
        raise BookError("pdftotext is not installed (package poppler)") from None
    except subprocess.TimeoutExpired:
        raise BookError("the PDF took too long to read") from None
    message = done.stderr.decode("utf-8", errors="replace")
    if done.returncode != 0:
        if "not allowed" in message.lower() or "permission" in message.lower():
            raise BookError("this PDF is locked against copying its text, so it can't be added")
        if "password" in message.lower():
            raise BookError("this PDF needs a password")
        raise BookError("it could not be read as a PDF")
    pages = done.stdout.decode("utf-8", errors="replace").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def _chunks(text):
    """Splits a page into passages at paragraph breaks."""
    out, current = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = re.sub(r"[ \t]+", " ", para.replace("-\n", "").replace("\n", " ")).strip()
        if not para:
            continue
        while len(para) > CHUNK_CHARS:  # a very long paragraph
            cut = para.rfind(". ", 0, CHUNK_CHARS) + 1 or CHUNK_CHARS
            out.append(((current + " ").lstrip() + para[:cut]).strip())
            current, para = "", para[cut:].strip()
        if len(current) + len(para) > CHUNK_CHARS:
            out.append(current.strip())
            current = ""
        current = f"{current} {para}".strip()
    if current:
        out.append(current)
    return out


def add_book(path, progress=lambda _text: None):
    """Indexes a PDF. Returns (title, pages, pages without text). Raises BookError."""
    if not path.lower().endswith(".pdf"):
        raise BookError("only PDF files can be added")
    try:
        sha = _sha(path)
    except OSError as e:
        raise BookError(f"it could not be opened ({e.strerror})") from None
    db = _db()
    try:
        if (row := db.execute("SELECT title FROM books WHERE sha = ?", (sha,)).fetchone()):
            raise BookError(f"it is already in your library as {row[0]}")
        progress("Reading the pages…")
        pages = extract_pages(path)
        empty = sum(1 for p in pages if len(p.strip()) < 40)
        if not pages or empty == len(pages):
            raise BookError("it has no text to read, probably because it is made of scanned pictures")
        progress(f"Indexing {len(pages)} pages…")
        title = _title(path)
        with db:
            book_id = db.execute("INSERT INTO books (title, file, pages, passages, sha, added) VALUES (?, ?, ?, 0, ?, ?)",
                                 (title, os.path.basename(path), len(pages), sha, time.time())).lastrowid
            rows = [(book_id, number, chunk) for number, page in enumerate(pages, 1) for chunk in _chunks(page)]
            db.executemany("INSERT INTO chunks (book_id, page, text) VALUES (?, ?, ?)", rows)
            db.execute("UPDATE books SET passages = ? WHERE id = ?", (len(rows), book_id))
        return title, len(pages), empty
    finally:
        db.close()


def books():
    """Every book, as dicts, in the order added."""
    if not DIR[0] or not os.path.exists(os.path.join(DIR[0], "library.sqlite")):
        return []
    db = _db()
    try:
        return [{"id": r[0], "title": r[1], "file": r[2], "pages": r[3], "passages": r[4]}
                for r in db.execute("SELECT id, title, file, pages, passages FROM books ORDER BY added")]
    finally:
        db.close()


def remove_book(book_id):
    db = _db()
    try:
        with db:
            db.execute("DELETE FROM chunks WHERE book_id = ?", (book_id,))
            db.execute("DELETE FROM books WHERE id = ?", (book_id,))
    finally:
        db.close()


def search(query, limit=4):
    """The passages that best match, as dicts with book, page and text. All the words first, then any of them."""
    if not DIR[0] or not os.path.exists(os.path.join(DIR[0], "library.sqlite")):
        return []
    words = [w for w in re.findall(r"[^\W_]+", str(query).lower()) if len(w) > 1][:12]
    if not words:
        return []
    db = _db()
    try:
        sql = ("SELECT books.title, chunks.page, chunks.text FROM chunks JOIN books ON books.id = chunks.book_id WHERE chunks MATCH ? "
               "ORDER BY bm25(chunks) LIMIT ?")
        quoted = [f'"{w}"' for w in words]
        rows = db.execute(sql, (" AND ".join(quoted), limit)).fetchall()
        if not rows:
            rows = db.execute(sql, (" OR ".join(quoted), limit)).fetchall()
        return [{"book": r[0], "page": r[1], "text": r[2][:RESULT_CHARS]} for r in rows]
    finally:
        db.close()
