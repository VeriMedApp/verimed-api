"""WP-INFRA-1: API-/APK-Vertrag und Startverhalten (C1-C7).

Der Vertrag wurde bei Commit 9311abe (vor WP-INFRA-1) eingefroren:
tests/fixtures/api_contract_baseline.json (Routen + OpenAPI).
"""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from starlette.routing import Mount

from app.schema_guard import SchemaGuardError
from tests.conftest import REPO_ROOT, _make_engine, dispose_app_engine

BASELINE_PATH = REPO_ROOT / "tests" / "fixtures" / "api_contract_baseline.json"
BASELINE = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _route_inventory(app) -> list[dict]:  # noqa: ANN001
    return [
        {
            "path": getattr(r, "path", ""),
            "methods": sorted(getattr(r, "methods", None) or []),
            "kind": "mount" if isinstance(r, Mount) else "route",
            "name": getattr(r, "name", None),
        }
        for r in app.routes
    ]


@pytest.fixture
def client(migrated_engine) -> Iterator[TestClient]:  # noqa: ARG001
    """TestClient mit Lifespan (Guard + Seed) gegen eine migrierte Testdatenbank."""
    from app.main import app

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        dispose_app_engine()


# ---------------------------------------------------------------------------
# C1/C2 - Startverhalten
# ---------------------------------------------------------------------------


def test_c1_startup_and_health_at_head(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "project": "ProofMed"}


def test_c2_startup_fails_closed_when_unmigrated(clean_db) -> None:  # noqa: ARG001
    from app.main import app

    try:
        with pytest.raises(SchemaGuardError):
            with TestClient(app):
                pass
    finally:
        dispose_app_engine()
    probe = _make_engine()
    try:
        assert set(sa.inspect(probe).get_table_names()) == set(), (
            "Fehlgeschlagener Start darf kein Schema (auch nicht alembic_version) anlegen"
        )
    finally:
        probe.dispose()


# ---------------------------------------------------------------------------
# C3/C4 - Routen- und OpenAPI-Vertrag unveraendert
# ---------------------------------------------------------------------------


def test_c3_route_inventory_unchanged() -> None:
    from app.main import app

    assert _route_inventory(app) == BASELINE["routes"]


def test_c4_openapi_unchanged() -> None:
    from app.main import app

    assert app.openapi() == BASELINE["openapi"]


# ---------------------------------------------------------------------------
# C5 - Kein create_all mehr im Anwendungscode; Reference-Core-Isolation bleibt
# ---------------------------------------------------------------------------


def _calls_attribute(path: Path, attribute: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.Attribute) and node.attr == attribute for node in ast.walk(tree)
    )


def test_c5_no_create_all_in_application_code() -> None:
    offenders = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in (REPO_ROOT / "app").rglob("*.py")
        if _calls_attribute(p, "create_all")
    ]
    assert offenders == [], f"create_all im Anwendungscode gefunden: {offenders}"
    # Der Guard darf keine Migrationen ausfuehren; create_all ist durch den
    # AST-Scan oben bereits fuer app/schema_guard.py ausgeschlossen.
    guard_src = (REPO_ROOT / "app" / "schema_guard.py").read_text(encoding="utf-8")
    for forbidden in ("command.upgrade", "command.downgrade"):
        assert forbidden not in guard_src, f"Guard darf {forbidden!r} nicht enthalten"


# ---------------------------------------------------------------------------
# C6 - GOAE-Seed/-Katalog unveraendert
# ---------------------------------------------------------------------------


def test_c6_goa_catalog_seeded_and_served(client: TestClient) -> None:
    from app.goa_catalog import GOA_CATALOG

    response = client.get("/api/v1/claims/catalog")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == len(GOA_CATALOG) == 26
    served = {entry["ziffer"] for entry in payload}
    assert served == {row["ziffer"] for row in GOA_CATALOG}


# ---------------------------------------------------------------------------
# C7 - encrypted_backups Round-Trip unveraendert
# ---------------------------------------------------------------------------


def test_c7_backup_round_trip(client: TestClient) -> None:
    payload = {
        "user_id_hash": "a" * 64,
        "ciphertext_base64": "Y2lwaGVydGV4dA==",
        "iv_base64": "aXZpdml2aXZpdg==",
        "salt_base64": "c2FsdHNhbHRzYWx0",
    }
    saved = client.post("/api/v1/backup/save", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["success"] is True
    assert saved.json()["timestamp"]

    restored = client.post("/api/v1/backup/restore", json={"user_id_hash": payload["user_id_hash"]})
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["success"] is True
    assert body["ciphertext_base64"] == payload["ciphertext_base64"]
    assert body["iv_base64"] == payload["iv_base64"]
    assert body["salt_base64"] == payload["salt_base64"]
    assert body["timestamp"] == saved.json()["timestamp"]

    missing = client.post("/api/v1/backup/restore", json={"user_id_hash": "b" * 64})
    assert missing.status_code == 404
