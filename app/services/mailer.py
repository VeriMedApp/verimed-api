"""SMTP-Versand fuer formelle Einwaende (mit Mock-Fallback)."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from fastapi import BackgroundTasks

from app.config import settings
from app.schemas.objection import SendObjectionRequest, SendObjectionResponse

logger = logging.getLogger(__name__)

SUCCESS_MESSAGE = "E-Mail erfolgreich versendet!"


def _send_smtp_email(to_addr: str, subject: str, body_html: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_addr
    msg.set_content("Bitte oeffnen Sie diese Nachricht in einem HTML-faehigen E-Mail-Programm.")
    msg.add_alternative(body_html, subtype="html")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(msg)
    logger.info("Einwand-E-Mail an %s versendet.", to_addr)


def dispatch_objection_email(
    payload: SendObjectionRequest,
    background_tasks: BackgroundTasks,
) -> SendObjectionResponse:
    """Versendet die Einwand-Mail oder gibt einen erfolgreichen Mock zurueck."""
    if not settings.smtp_configured:
        logger.info(
            "SMTP nicht konfiguriert – Mock-Versand an %s (Rechnung %s, %s).",
            payload.recipient_email,
            payload.invoice_number or "–",
            payload.practice_name or "–",
        )
        return SendObjectionResponse(success=True, message=SUCCESS_MESSAGE)

    background_tasks.add_task(
        _send_smtp_email,
        payload.recipient_email,
        payload.subject,
        payload.body_html,
    )
    return SendObjectionResponse(success=True, message=SUCCESS_MESSAGE)
