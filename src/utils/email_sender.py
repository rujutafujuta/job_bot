"""Gmail SMTP email sender with attachment support."""

import os
import smtplib
import mimetypes
from email.message import EmailMessage
from pathlib import Path


def _smtp_credentials() -> tuple[str, str, str, int]:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    if not user or not password:
        raise EnvironmentError(
            "SMTP_USER and SMTP_PASSWORD must be set in .env\n"
            "For Gmail, use an App Password (not your account password)."
        )
    return host, port, user, password


def send_email(
    to: str,
    subject: str,
    body: str,
    attachments: list[str | Path] | None = None,
    dry_run: bool = False,
) -> None:
    """
    Send an email via Gmail SMTP.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain-text email body.
        attachments: Optional list of file paths to attach.
        dry_run: If True, log the email but do not send.
    """
    host, port, user, password = _smtp_credentials()

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    for path in (attachments or []):
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Attachment not found: {path}")
        mime_type, _ = mimetypes.guess_type(str(path))
        maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
        msg.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )

    if dry_run:
        print(f"[email][DRY RUN] Would send to={to} subject='{subject}'")
        return

    try:
        with smtplib.SMTP(host, port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            f"[email] Gmail authentication failed — ensure SMTP_PASSWORD is an App Password "
            f"(not your account password). Error: {exc}"
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise RuntimeError(f"[email] Failed to send email to {to}: {exc}") from exc

    print(f"[email] Sent to {to}: {subject}")
