"""SMTP-Versand fuer formelle Einwaende (mit Mock-Fallback)."""

from __future__ import annotations

import base64
import logging
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from fastapi import BackgroundTasks

from app.config import settings
from app.schemas.objection import SendObjectionRequest, SendObjectionResponse

logger = logging.getLogger(__name__)

SUCCESS_MESSAGE = "E-Mail erfolgreich versendet!"
SUCCESS_MESSAGE_WITH_ATTACHMENT = "E-Mail mit Rechnungsanhang erfolgreich versendet!"
_MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024

_MIME_BY_SUFFIX = {
    ".jpg": ("image", "jpeg"),
    ".jpeg": ("image", "jpeg"),
    ".png": ("image", "png"),
    ".gif": ("image", "gif"),
    ".webp": ("image", "webp"),
    ".pdf": ("application", "pdf"),
}


def _decode_invoice_attachment(
    payload: SendObjectionRequest,
) -> tuple[bytes, str, str, str] | None:
    raw_b64 = (payload.invoice_image_base64 or "").strip()
    if not raw_b64:
        return None
    if raw_b64.lower().startswith("data:") and "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]
    try:
        data = base64.b64decode(raw_b64, validate=False)
    except Exception:
        logger.warning("Rechnungsanhang konnte nicht dekodiert werden.")
        return None
    if not data or len(data) > _MAX_ATTACHMENT_BYTES:
        logger.warning("Rechnungsanhang fehlt oder ist zu gross (%s Bytes).", len(data) if data else 0)
        return None

    filename = Path(payload.invoice_filename or "rechnung.jpg").name or "rechnung.jpg"
    suffix = Path(filename).suffix.lower()
    maintype, subtype = _MIME_BY_SUFFIX.get(suffix, ("application", "octet-stream"))
    return data, filename, maintype, subtype


def _send_smtp_email(
    to_addr: str,
    subject: str,
    body_html: str,
    attachment: tuple[bytes, str, str, str] | None = None,
) -> None:
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_addr

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(
        "Bitte oeffnen Sie diese Nachricht in einem HTML-faehigen E-Mail-Programm.",
        "plain",
        "utf-8",
    ))
    alternative.attach(MIMEText(body_html, "html", "utf-8"))
    msg.attach(alternative)

    if attachment:
        data, filename, maintype, subtype = attachment
        part = MIMEBase(maintype, subtype)
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(msg)
    logger.info(
        "Einwand-E-Mail an %s versendet%s.",
        to_addr,
        f" (Anhang: {attachment[1]})" if attachment else "",
    )


def dispatch_objection_email(
    payload: SendObjectionRequest,
    background_tasks: BackgroundTasks,
) -> SendObjectionResponse:
    """Versendet die Einwand-Mail oder gibt einen erfolgreichen Mock zurueck."""
    attachment = _decode_invoice_attachment(payload)
    success_message = SUCCESS_MESSAGE_WITH_ATTACHMENT if attachment else SUCCESS_MESSAGE

    if not settings.smtp_configured:
        logger.info(
            "SMTP nicht konfiguriert – Mock-Versand an %s (Rechnung %s, %s%s).",
            payload.recipient_email,
            payload.invoice_number or "–",
            payload.practice_name or "–",
            f", Anhang {attachment[1]}" if attachment else "",
        )
        return SendObjectionResponse(success=True, message=success_message)

    background_tasks.add_task(
        _send_smtp_email,
        payload.recipient_email,
        payload.subject,
        payload.body_html,
        attachment,
    )
    return SendObjectionResponse(success=True, message=success_message)
