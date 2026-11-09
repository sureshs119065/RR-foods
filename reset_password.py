import getpass
from app import create_app
from app.extensions import db
from app.models import User
from app.security import hash_password

email = input("Account email: ").strip().lower()
app = create_app()
with app.app_context():
    user = db.session.scalar(db.select(User).where(db.func.lower(User.email) == email))
    if not user:
        raise SystemExit("No account with that email.")
    pw = getpass.getpass("New password: ")
    if len(pw) < 10 or pw != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords differ or are shorter than 10 characters.")
    user.password_hash = hash_password(pw)
    user.failed_login_count = 0
    user.locked_until = None
    db.session.commit()
    print("Password updated for", user.email, "(" + user.role + ")")
