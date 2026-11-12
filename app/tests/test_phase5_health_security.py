from app import create_app
from app.config import TestConfig


class HealthConfig(TestConfig):
    TESTING = True


def test_health_route_is_public_and_reports_database():
    app = create_app(HealthConfig)
    with app.test_client() as client:
        response = client.get("/health")
        assert response.status_code in (200, 503)
        assert response.is_json
        assert "version" in response.get_json()


def test_security_headers_and_request_id():
    app = create_app(HealthConfig)
    with app.test_client() as client:
        response = client.get("/health", headers={"X-Request-ID": "phase5-test-123"})
        assert response.headers["X-Request-ID"] == "phase5-test-123"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" in response.headers


def test_vapid_public_key_endpoint_does_not_expose_private_key():
    app = create_app(HealthConfig)
    app.config["VAPID_PUBLIC_KEY"] = "public-demo"
    app.config["VAPID_PRIVATE_KEY"] = "private-secret"
    with app.test_client() as client:
        data = client.get("/push/vapid-public-key").get_json()
        assert data == {"publicKey": "public-demo"}
        assert "private-secret" not in str(data)
