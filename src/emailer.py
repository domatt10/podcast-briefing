"""Send the briefing over Gmail SMTP (app password).

Addresses and the password come from the environment only (.env locally,
GitHub Secrets in CI) — they are never in config or code because the repo
will be public. LOG DISCIPLINE: never print addresses or message content.
"""

import os
import smtplib
from email.message import EmailMessage


def send_email(subject: str, text: str, html: str, email_cfg: dict) -> None:
    from_addr = os.environ["BRIEFING_FROM"]
    to_addr = os.environ["BRIEFING_TO"]
    # Google displays app passwords in spaced groups; the spaces aren't part of it.
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(email_cfg["smtp_host"], email_cfg["smtp_port"], timeout=60) as smtp:
        smtp.starttls()
        smtp.login(from_addr, password)
        smtp.send_message(msg)
    print("[email] sent")
