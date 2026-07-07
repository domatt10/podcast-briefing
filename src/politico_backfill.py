"""One-off Politico backfill: pull labelled emails from a date window into the
archive, regardless of read status (the daily pipeline only takes UNSEEN).

Run locally: ARCHIVE_DIR=<archive clone> python src/politico_backfill.py --days 90

Idempotent: filenames reuse the daily pipeline's message-id hash scheme, so
existing files are skipped and re-runs never duplicate. Uses BODY.PEEK so it
never changes read/unread flags in the mailbox.
"""

import argparse
import email
import hashlib
import imaplib
import os
from datetime import date, timedelta
from email.utils import parsedate_to_datetime

from config import archive_dir, load_config
from politico import _body_text, _decode


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()

    cfg = load_config()
    label = cfg["politico"]["gmail_label"]
    out_dir = archive_dir(cfg) / "news" / "politico"
    user = os.environ["BRIEFING_FROM"]
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    since = (date.today() - timedelta(days=args.days)).strftime("%d-%b-%Y")

    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        imap.login(user, password)
        status, _ = imap.select(f'"{label}"', readonly=True)
        if status != "OK":
            raise RuntimeError(f"Gmail label not found via IMAP: {label}")
        _, data = imap.search(None, f'(SINCE "{since}")')
        msg_ids = data[0].split()
        print(f"[politico-backfill] {len(msg_ids)} email(s) under '{label}' since {since}")

        saved = skipped = 0
        oldest = None
        for msg_id in msg_ids:
            _, msg_data = imap.fetch(msg_id, "(BODY.PEEK[])")
            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode(msg.get("Subject")) or "(no subject)"
            sender = _decode(msg.get("From"))
            when = ""
            if msg.get("Date"):
                when = parsedate_to_datetime(msg["Date"]).date().isoformat()
                oldest = when if oldest is None or when < oldest else oldest
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
        print(f"[politico-backfill] saved {saved}, skipped {skipped} already archived; oldest: {oldest}")
    finally:
        try:
            imap.logout()
        except Exception:
            pass


if __name__ == "__main__":
    main()
