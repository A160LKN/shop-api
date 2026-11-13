"""CORS: браузер пускает к API только известные фронтенды."""
import pytest

pytestmark = pytest.mark.api

PREFLIGHT = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"}


def test_known_frontend_is_allowed(client):
    response = client.options("/orders", headers={"Origin": "http://localhost:5173", **PREFLIGHT})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_unknown_site_is_not_allowed(client):
    response = client.options("/orders", headers={"Origin": "https://evil.example", **PREFLIGHT})

    assert "access-control-allow-origin" not in response.headers


def test_simple_request_from_frontend_gets_cors_header(client):
    response = client.get("/products", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
