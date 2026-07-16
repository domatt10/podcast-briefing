"""Politico newsletters via Gmail IMAP (agent brief A.1).

Reuses the one existing credential: the Gmail address + app password that
already send the briefing (BRIEFING_FROM / GMAIL_APP_PASSWORD). Deliberately
IMAP, not the Gmail API — no OAuth machinery.

Mechanism: open the Gmail label READ-ONLY, fetch everything from the last few
days regardless of read status, and dedupe by Message-ID hash in the filename.
(The original design fetched UNSEEN mail and marked it read — but Dom reads
Playbook before the pipeline runs, so his own reading hid emails from the
archive. Read status is his; the filename is ours.) Some boilerplate survives
the HTML strip — acceptable for reference material (brief's watch-outs).
"""

import email
import hashlib
import imaplib
import os
from datetime import date, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path

from bs4 import BeautifulSoup


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            text = text.decode(charset or "utf-8", errors="replace")
        out.append(text)
    return "".join(out).strip()


def _body_text(msg) -> str:
    """Prefer the HTML part (newsletters are HTML-first), stripped to text."""
    html, plain = None, None
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/html", "text/plain"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if ctype == "text/html" and html is None:
            html = text
        elif ctype == "text/plain" and plain is None:
            plain = text
    if html:
        return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    return plain or ""


def fetch_politico(cfg: dict, archive: Path, days: int | None = None) -> int:
    """Save Politico-labelled emails from the last `days` days (default from
    config lookback_days); returns count of new files. Idempotent via
    Message-ID-hash filenames; never changes read/unread flags (BODY.PEEK +
    read-only mailbox). Raises on connection/label problems — the caller
    treats this stage as non-fatal.
    """
    user = os.environ["BRIEFING_FROM"]
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    label = cfg["politico"]["gmail_label"]
    window = days if days is not None else cfg["politico"].get("lookback_days", 3)
    since = (date.today() - timedelta(days=window)).strftime("%d-%b-%Y")
    out_dir = archive / "news" / "politico"

    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        imap.login(user, password)
        status, _ = imap.select(f'"{label}"', readonly=True)
        if status != "OK":
            raise RuntimeError(f"Gmail label not found via IMAP: {label}")
        _, data = imap.search(None, f'(SINCE "{since}")')
        msg_ids = data[0].split()

        saved = skipped = 0
        for msg_id in msg_ids:
            _, msg_data = imap.fetch(msg_id, "(BODY.PEEK[])")
            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode(msg.get("Subject")) or "(no subject)"
            sender = _decode(msg.get("From"))
            when = ""
            if msg.get("Date"):
                when = parsedate_to_datetime(msg["Date"]).date().isoformat()
            stamp = hashlib.sha256((msg.get("Message-ID") or subject + when).encode()).hexdigest()[:8]
            dest = out_dir / f"{when}_{stamp}.md"
            if dest.exists():
                skipped += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(
                f"# {subject}\n\n"
                f"- **Source:** Politico newsletter (reported news / reported speculation)\n"
                f"- **From:** {sender}\n"
                f"- **Date:** {when}\n\n"
                f"{_body_text(msg)}\n",
                encoding="utf-8",
            )
            saved += 1
        print(f"[politico] window {window}d: {saved} new, {skipped} already archived")
        return saved
    finally:
        try:
            imap.logout()
        except Exception:
            pass
