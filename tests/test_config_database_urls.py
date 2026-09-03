from app.config import Settings


def _settings(database_url: str, sync_database_url: str | None = None) -> Settings:
    return Settings(
        _env_file=None,
        DATABASE_URL=database_url,
        SYNC_DATABASE_URL=sync_database_url,
    )


def test_effective_sync_url_normalizes_legacy_postgres_scheme() -> None:
    settings = _settings("postgres://u:p@h/db")

    assert (
        settings.effective_sync_database_url
        == "postgresql+psycopg2://u:p@h/db"
    )


def test_effective_sync_url_normalizes_asyncpg_scheme() -> None:
    settings = _settings("postgresql+asyncpg://u:p@h/db")

    assert (
        settings.effective_sync_database_url
        == "postgresql+psycopg2://u:p@h/db"
    )


def test_effective_sync_url_accepts_standard_postgresql_scheme() -> None:
    settings = _settings("postgresql://u:p@h/db")

    assert settings.effective_sync_database_url == "postgresql://u:p@h/db"


def test_sync_database_url_override_normalizes_legacy_postgres_scheme() -> None:
    settings = _settings(
        "sqlite+aiosqlite:///./verimed.db",
        sync_database_url="postgres://u:p@h/db",
    )

    assert (
        settings.effective_sync_database_url
        == "postgresql+psycopg2://u:p@h/db"
    )
