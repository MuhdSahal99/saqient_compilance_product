"""Email notifications: rendering (English and Arabic) and the notification log."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app import mail
from app.config import get_settings
from app.models import NotificationKind, NotificationLog, NotificationStatus, Role

logger = logging.getLogger("saqient.notifications")

ROLE_LABELS = {
    Role.ORG_ADMIN: ("organisation admin", "مسؤول المؤسسة"),
    Role.REVIEWER: ("reviewer", "مراجع"),
    Role.ANALYST: ("analyst", "محلل"),
    Role.VIEWER: ("viewer", "مشاهد"),
}


def link(path: str, token: str) -> str:
    # The token goes in the fragment so it never reaches server logs or Referer headers.
    return f"{get_settings().app_base_url.rstrip('/')}{path}#token={token}"


def invitation_mail(
    to: str, org_name: str, inviter: str | None, role: Role, url: str, expires: datetime
) -> mail.Mail:
    en_role, ar_role = ROLE_LABELS[role]
    who = inviter or "An administrator"
    when = expires.strftime("%Y-%m-%d %H:%M")
    text = (
        f"{who} invited you to join {org_name} on Saqient as {en_role}.\n\n"
        f"Accept the invitation: {url}\n\n"
        f"The link works once and expires on {when} UTC. If you were not expecting this, "
        "you can ignore this email.\n\n"
        "—\n"
        f"تمت دعوتك للانضمام إلى {org_name} على Saqient بدور {ar_role}.\n\n"
        f"لقبول الدعوة: {url}\n\n"
        f"يعمل الرابط مرة واحدة وتنتهي صلاحيته في {when} بالتوقيت العالمي. "
        "إذا لم تكن تتوقع هذه الرسالة، يمكنك تجاهلها.\n"
    )
    return mail.Mail(to=to, subject=f"You're invited to {org_name} on Saqient", text=text)


def password_reset_mail(to: str, url: str, minutes: int) -> mail.Mail:
    text = (
        "Someone asked to reset the password for your Saqient account.\n\n"
        f"Reset your password: {url}\n\n"
        f"The link works once and expires in {minutes} minutes. If you did not ask for this, "
        "ignore this email; your password stays the same.\n\n"
        "—\n"
        "طلب أحدهم إعادة تعيين كلمة المرور لحسابك على Saqient.\n\n"
        f"لإعادة تعيين كلمة المرور: {url}\n\n"
        f"يعمل الرابط مرة واحدة وتنتهي صلاحيته خلال {minutes} دقيقة. "
        "إذا لم تطلب ذلك، تجاهل هذه الرسالة وستبقى كلمة المرور كما هي.\n"
    )
    return mail.Mail(to=to, subject="Reset your Saqient password", text=text)


def send_logged(
    db: Session,
    message: mail.Mail,
    *,
    org_id: uuid.UUID,
    kind: NotificationKind,
    object_type: str,
    object_id: uuid.UUID | None,
    recipient_user_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
) -> NotificationLog:
    """Send and record the attempt (without the body). The caller commits."""
    try:
        sent = mail.send(message)
        status, error = (NotificationStatus.SENT if sent else NotificationStatus.DISABLED), None
    except mail.MailError as exc:
        status, error = NotificationStatus.FAILED, str(exc)[:300]
    entry = NotificationLog(
        org_id=org_id,
        kind=kind,
        recipient_user_id=recipient_user_id,
        recipient_email=message.to,
        subject=message.subject[:300],
        object_type=object_type,
        object_id=object_id,
        dedupe_key=dedupe_key,
        status=status,
        error=error,
    )
    db.add(entry)
    return entry
