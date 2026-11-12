from app.auth.service import _lockout_hash


def test_lockout_hash_is_stable_and_hashed(app):
    with app.app_context():
        first = _lockout_hash("127.0.0.1")
        second = _lockout_hash("127.0.0.1")
        assert first == second
        assert len(first) == 64
        assert first != "127.0.0.1"
