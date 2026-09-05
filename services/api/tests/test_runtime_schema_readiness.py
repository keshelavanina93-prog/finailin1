from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import Response

from finai_api.api import routes


@pytest.mark.parametrize("missing", [None, 4, routes.REQUIRED_SCHEMA_VERSION])
def test_readiness_requires_complete_migration_chain(
    monkeypatch: pytest.MonkeyPatch, missing: int | None
) -> None:
    class Database:
        def execute(self, query: str) -> Any:
            return self

        def fetchall(self) -> list[tuple[int]]:
            return [
                (value,)
                for value in range(1, routes.REQUIRED_SCHEMA_VERSION + 1)
                if value != missing
            ]

    @contextmanager
    def connect(*args: Any, **kwargs: Any) -> Any:
        yield Database()

    monkeypatch.setenv("FINAI_DATABASE_URL", "postgresql://unused")
    routes.get_settings.cache_clear()
    monkeypatch.setattr(routes.psycopg, "connect", connect)
    monkeypatch.setattr(routes, "check_ready", lambda: None)
    response = Response()
    try:
        result = routes.readiness(response)
        assert response.status_code == (200 if missing is None else 503)
        assert result["schema"] == ("ready" if missing is None else "migration_required")
    finally:
        routes.get_settings.cache_clear()
