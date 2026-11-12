from pathlib import Path
from app import create_app
from app.config import TestConfig


class PushConfig(TestConfig):
    TESTING = True
    VAPID_PUBLIC_KEY = ""
    VAPID_PRIVATE_KEY = ""


def test_push_public_key_is_empty_when_not_configured():
    app = create_app(PushConfig)
    with app.test_client() as client:
        response = client.get("/push/vapid-public-key")
        assert response.status_code == 200
        assert response.get_json() == {"publicKey": ""}


def test_service_worker_has_push_handler():
    sw = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "sw.js"
    source = sw.read_text()
    assert 'addEventListener("push"' in source
    assert 'addEventListener("notificationclick"' in source
