"""Outgoing email.

Messages can carry single-use links, so bodies are never logged. The file
backend (development) writes ``.eml`` files to ``MAIL_FILE_DIR``; the memory
backend (tests) keeps them in ``outbox``; smtp delivers; disabled drops them.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from app.config import Settings, get_settings

logger = logging.getLogger("saqient.mail")


class MailError(RuntimeError):
    """Delivery failed (message safe to store; no credentials or bodies)."""


@dataclass
class Mail:
    to: str
    subject: str
    text: str


outbox: list[Mail] = []  # memory backend (tests)


def _message(settings: Settings, mail: Mail) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = mail.to
    msg["Subject"] = mail.subject
    msg["Message-ID"] = make_msgid(domain="saqient.local")
    msg.set_content(mail.text)
    return msg


def send(mail: Mail, settings: Settings | None = None) -> bool:
    """Send one message. Returns False when mail is disabled; raises MailError on failure."""
    s = settings or get_settings()
    if "\n" in mail.to or "\r" in mail.to or "\n" in mail.subject or "\r" in mail.subject:
        raise MailError("Header values cannot contain line breaks.")
    domain = mail.to.rsplit("@", 1)[-1]
    if s.mail_backend == "disabled":
        logger.info("mail disabled; not sent", extra={"to_domain": domain})
        return False
    if s.mail_backend == "memory":
        if s.app_env != "test":
            raise MailError("The memory mail backend is for tests only.")
        outbox.append(mail)
        return True
    if s.mail_backend == "file":
        if s.is_production:
            raise MailError("The file mail backend is not allowed in production.")
        folder = Path(s.mail_file_dir)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{uuid.uuid4().hex}.eml"
        path.write_bytes(bytes(_message(s, mail)))
        logger.info("mail written to file", extra={"to_domain": domain, "file": path.name})
        return True
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds) as smtp:
            if s.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if s.smtp_username:
                smtp.login(s.smtp_username, s.smtp_password)
            smtp.send_message(_message(s, mail))
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning(
            "smtp delivery failed", extra={"to_domain": domain, "error_class": type(exc).__name__}
        )
        raise MailError(f"Delivery failed ({type(exc).__name__}).") from exc
    logger.info("mail sent", extra={"to_domain": domain})
    return True
