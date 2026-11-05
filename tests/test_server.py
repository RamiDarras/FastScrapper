"""API response regressions without starting the scraper or scheduler."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src import server
from src.exceptions import StorageError
from src.models import ScrapedData


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "config", SimpleNamespace(api_key="test-api-key"))
    # Do not enter the context: lifespan would start real scraping jobs.
    client = TestClient(server.app, raise_server_exceptions=False)
    yield client
    client.close()


def test_storage_error_returns_json_500(client, monkeypatch):
    storage = SimpleNamespace(load=AsyncMock(side_effect=StorageError("invalid stored JSON")))
    monkeypatch.setattr(server, "storage", storage)

    response = client.get("/api/data/example", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Internal server error: invalid stored JSON"}
    storage.load.assert_awaited_once_with("example")


def test_missing_target_keeps_json_404(client, monkeypatch):
    monkeypatch.setattr(server, "storage", SimpleNamespace(load=AsyncMock(return_value=None)))

    response = client.get("/api/data/missing", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 404
    assert response.json() == {"detail": "No data found for target 'missing'"}


def test_successful_data_response(client, monkeypatch):
    data = ScrapedData(target_name="example", url="https://example.com", success=True,
                       data={"title": "Example"})
    monkeypatch.setattr(server, "storage", SimpleNamespace(load=AsyncMock(return_value=data)))

    response = client.get("/api/data/example", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 200
    assert response.json() == data.model_dump(mode="json")
