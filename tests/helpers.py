import io
import re

from PIL import Image

from app.models import User
from app.security import hash_password

PW = "Sup3rSecret!"


def make_user(session, role, email=None):
    u = User(email=email or f"{role}@test.com", name=role.title(), role=role, password_hash=hash_password(PW))
    session.add(u)
    session.commit()
    return u


def token(client, url):
    html = client.get(url).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1)


def checkout_token(client):
    """The one-time token the checkout page embeds (guards against double submits). Empty if the page did not render one."""
    html = client.get("/checkout").get_data(as_text=True)
    m = re.search(r'name="checkout_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


def checkout_post(client, data=None, page=None, follow=False):
    """POST /checkout the way a browser does: load the checkout page first to receive its token."""
    data = dict(data or {})
    data.setdefault("checkout_token", checkout_token(client))
    return post(client, "/checkout", data, page=page, follow=follow)


def signup(client, monkeypatch, data):
    """Create an account the way a person does: fill the form, read the emailed 6 digit code, type it in.

    Returns the response of the final /register/verify POST (302 to /account on success). If the form itself is
    refused, that response is returned instead and no code is ever sent.
    """
    import app.auth.otp as otp
    sent = []
    monkeypatch.setattr(otp, "send_now", lambda to, subject, text, html=None: sent.append((to, subject, text, html)))
    r = post(client, "/register", data, page="/register")
    if r.status_code != 302:
        return r
    code = re.search(r"code is (\d{6})", sent[-1][2]).group(1)
    return post(client, "/register/verify", {"code": code}, page="/register/verify")


def sign_in(client, role="admin"):
    url = {"user": "/login", "owner": "/owner/login", "admin": "/admin/login"}[role]
    return client.post(url, data={"email": f"{role}@test.com", "password": PW, "csrf_token": token(client, url)})


def post(client, url, data=None, page=None, files=None, follow=False):
    """POST with a valid CSRF token taken from `page` (default: the same URL, or the admin dashboard)."""
    data = dict(data or {})
    data["csrf_token"] = token(client, page or "/admin/")
    if files:
        data.update(files)
        return client.post(url, data=data, content_type="multipart/form-data", follow_redirects=follow)
    return client.post(url, data=data, follow_redirects=follow)


def png_bytes(size=(800, 600), color=(200, 30, 30), fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    buf.seek(0)
    return buf


def img(name="a.png", **kw):
    return (png_bytes(**kw), name)


def confirm_requests(session):
    """Play the shop's side of the WhatsApp step: confirm every checkout request whose message "arrived". Returns the orders."""
    from sqlalchemy import select

    from app.models import Order
    from app.services import orders as order_svc

    owner = session.scalar(select(User).where(User.role == "owner")) or make_user(session, "owner", "auto-owner@x.com")
    done = []
    for o in session.scalars(select(Order).where(Order.status == "pending_whatsapp").order_by(Order.id)).all():
        done.append(order_svc.confirm_whatsapp_received(o.id, owner))
    session.commit()
    session.expire_all()
    return done
