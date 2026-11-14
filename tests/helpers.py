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
