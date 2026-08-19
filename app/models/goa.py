"""ORM-Modelle rund um den GOAE-Katalog (Gebuehrenordnung fuer Aerzte)."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GOAZiffer(Base):
    """Ein Katalogeintrag der Gebuehrenordnung fuer Aerzte (GOAE).

    Jede Ziffer beschreibt eine abrechenbare aerztliche Leistung inklusive der
    fuer die Plausibilitaetspruefung relevanten Regelzeit, Kategorie
    (persoenlich / technisch / Zuschlag) und der gegenseitigen Ausschluss-Ziffern.
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
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="personal"
    )
    threshold_multiplier: Mapped[float] = mapped_column(
        Float, nullable=False, default=2.3
    )
    max_multiplier: Mapped[float] = mapped_column(
        Float, nullable=False, default=3.5
    )
    fee_simple: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fee_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fee_max: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_per_session: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:  # pragma: no cover - reine Debug-Hilfe
        return (
            f"<GOAZiffer ziffer={self.ziffer!r} category={self.category!r} "
            f"rule_time_minutes={self.rule_time_minutes}>"
        )
