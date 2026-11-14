from sqlalchemy import select

from app.models import User
from app.security import verify_password
from tests.helpers import make_user


def test_reset_password_command(app, session):
    user = make_user(session, "admin")
    user.failed_login_count = 5
    session.commit()
    r = app.test_cli_runner().invoke(args=["reset-password", user.email], input="NewPass2026x\nNewPass2026x\n")
    assert r.exit_code == 0 and "Password updated" in r.output
    session.expire_all()
    u = session.scalar(select(User).where(User.id == user.id))
    assert verify_password(u.password_hash, "NewPass2026x") and u.failed_login_count == 0


def test_reset_password_rejects_weak_and_unknown(app, session):
    user = make_user(session, "admin")
    session.commit()
    weak = app.test_cli_runner().invoke(args=["reset-password", user.email], input="abc\nabc\n")
    assert weak.exit_code != 0 and "at least 8" in weak.output
    nobody = app.test_cli_runner().invoke(args=["reset-password", "nobody@x.com"], input="NewPass2026x\nNewPass2026x\n")
    assert nobody.exit_code != 0 and "No account" in nobody.output
