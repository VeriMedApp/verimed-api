"""Alembic-Umgebung fuer Project VeriMed.

Nutzt die synchrone DB-URL aus der Anwendungskonfiguration und die gemeinsame
`Base.metadata`, damit Autogenerate alle Modelle erkennt.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Anwendungskonfiguration und Metadata einbinden.
from app.config import settings
from app.database import Base
from app import models  # noqa: F401  (registriert alle Modelle bei der Metadata)
# WP-01: Reference-Core-Modelle werden NUR fuer Alembic registriert, nicht in
# app.models.__init__ (der Anwendungsstart/create_all bleibt unveraendert).
from app.models import reference_core  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.effective_sync_database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Migrationen im 'offline'-Modus (nur URL, keine Engine)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Migrationen im 'online'-Modus mit aktiver Engine."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
