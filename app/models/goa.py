"""ORM-Modelle rund um den GOAE-Katalog (Gebuehrenordnung fuer Aerzte)."""

from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GOAZiffer(Base):
    """Ein Katalogeintrag der Gebuehrenordnung fuer Aerzte (GOAE).

    Jede Ziffer beschreibt eine abrechenbare aerztliche Leistung inklusive der
    fuer die Plausibilitaetspruefung relevanten Regelzeit und der
    gegenseitigen Ausschluss-Ziffern.
    """

    __tablename__ = "goa_ziffern"

    ziffer: Mapped[str] = mapped_column(String(16), primary_key=True)
    title_official: Mapped[str] = mapped_column(String(512), nullable=False)
    title_patient: Mapped[str] = mapped_column(String(512), nullable=False)
    rule_time_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # Liste von Ziffern, die nicht gemeinsam abgerechnet werden duerfen.
    exclusion_ziffern: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )

    def __repr__(self) -> str:  # pragma: no cover - reine Debug-Hilfe
        return (
            f"<GOAZiffer ziffer={self.ziffer!r} "
            f"rule_time_minutes={self.rule_time_minutes}>"
        )
