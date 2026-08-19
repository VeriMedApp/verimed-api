"""Pydantic-Schemas fuer den direkten Einwand-Versand."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SendObjectionRequest(BaseModel):
    """Payload fuer POST /api/v1/send-objection."""

    recipient_email: str = Field(..., min_length=3, max_length=320)
    subject: str = Field(..., min_length=1, max_length=300)
    body_html: str = Field(..., min_length=1)
    invoice_number: str = ""
    practice_name: str = ""
    invoice_image_base64: str = ""
    invoice_filename: str = ""

    @field_validator("recipient_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not _EMAIL_RE.match(cleaned):
            raise ValueError("Ungueltige Empfaenger-E-Mail")
        return cleaned

    @field_validator("subject", "invoice_number", "practice_name", "invoice_filename")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return (value or "").strip()


class SendObjectionResponse(BaseModel):
    success: bool
    message: str
