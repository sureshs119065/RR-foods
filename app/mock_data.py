"""Mock orders for the dashboard charts (sales trend, top products, categories, order counts).

    flask seed-mock-analytics                  # 300 orders over the last 365 days
    flask seed-mock-analytics --orders 600 --days 180
    flask seed-mock-analytics --clear          # remove only the mock data

Everything it creates is tagged (order numbers start with MOCK-, customers are mock.*@example.test),
so --clear never touches real orders or customers. Stock is not changed.
"""
import random
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from .extensions import db
from .models import Address, Order, OrderItem, OrderStatusHistory, Product, User
from .models.base import utcnow
from .security import hash_password
from .services.storefront import money_setting
from .services.delivery import zone_for as delivery_zone_for

IST = ZoneInfo("Asia/Kolkata")
PREFIX = "MOCK-"
EMAIL_LIKE = "mock.%@example.test"

NAMES = ["Arun Kumar", "Divya Lakshmi", "Karthik Raja", "Meena Sundaram", "Prakash V", "Revathi S", "Suresh Babu", "Anitha Mohan",
         "Vignesh R", "Priya Dharshini", "Gokul Nath", "Lavanya K", "Senthil Murugan", "Nandhini P", "Harish Kumar", "Kavitha R",
         "Manoj Prabhu", "Swathi M", "Bala Subramani", "Deepa Rani", "Ramesh Chandran", "Janani V", "Saravanan T", "Pooja Shree"]
PLACES = [("Coimbatore", "641001"), ("Coimbatore", "641035"), ("Tiruppur", "641601"), ("Erode", "638001"), ("Salem", "636001"),
          ("Madurai", "625001"), ("Chennai", "600040"), ("Chennai", "600017"), ("Tiruchirappalli", "620001"), ("Tirunelveli", "627001")]
# (status, weight): mostly delivered so revenue charts look real
STATUSES = [("delivered", 62), ("out_for_delivery", 4), ("shipped", 6), ("packed", 4), ("confirmed", 5),
            ("placed", 4), ("cancelled", 6), ("rejected", 2), ("returned", 3), ("refunded", 4)]
FLOW = ["placed", "confirmed", "packed", "shipped", "out_for_delivery", "delivered"]
DEAD = {"cancelled": 1, "rejected": 1, "returned": 5, "refunded": 5}  # index in FLOW where the branch leaves


def q2(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def clear_mock() -> tuple[int, int]:
    ids = db.session.scalars(select(Order.id).where(Order.order_number.like(PREFIX + "%"))).all()
    if ids:
        db.session.execute(delete(Order).where(Order.id.in_(ids)))
    uids = db.session.scalars(select(User.id).where(User.email.like(EMAIL_LIKE))).all()
    if uids:
        db.session.execute(delete(Address).where(Address.user_id.in_(uids)))
        db.session.execute(delete(User).where(User.id.in_(uids)))
    db.session.commit()
    return len(ids), len(uids)


def _day_weight(day, idx, total_days) -> float:
    w = 1 + 1.2 * idx / max(total_days - 1, 1)      # business grows over the period
    w *= 1.35 if day.weekday() >= 5 else 1           # weekends are busier
    if (day.month, day.day) in {(11, d) for d in range(8, 15)} or (day.month == 1 and day.day <= 16):
        w *= 1.8                                      # festival bumps (Diwali / Pongal season)
    return w


def seed_mock(orders: int = 300, days: int = 365, seed: int = 7) -> dict:
    rnd = random.Random(seed)
    products = db.session.scalars(select(Product).where(Product.is_active.is_(True), Product.is_deleted.is_(False))).all()
    products = [p for p in products if Decimal(p.final_price or 0) > 0]
    if not products:
        raise RuntimeError("No active products. Run `flask seed` or `flask import-rr-foods` first.")
    # a few bestsellers get most of the sales, so the "top products" chart has a clear shape
    rnd.shuffle(products)
    pweights = [1 / (i + 1) ** 0.8 for i in range(len(products))]

    clear_mock()
    pw = hash_password("Mock-" + str(rnd.random()))
    customers = []
    for i, name in enumerate(NAMES):
        city, pin = PLACES[i % len(PLACES)]
        u = User(email=f"mock.customer{i + 1}@example.test", name=name, role="user", password_hash=pw,
                 phone=f"98{rnd.randint(10000000, 99999999)}", email_verified_at=utcnow())
        u.addresses.append(Address(label="Home", full_name=name, phone=u.phone, line1=f"{rnd.randint(1, 120)}, Gandhi Nagar",
                                   city=city, state="Tamil Nadu", pincode=pin, is_default=True))
        db.session.add(u)
        customers.append(u)
    db.session.flush()

    today = datetime.now(IST).date()
    day_list = [today - timedelta(days=days - 1 - i) for i in range(days)]
    dweights = [_day_weight(d, i, days) for i, d in enumerate(day_list)]
    rate = money_setting("tax_percent", "0")
    seq: dict = {}
    made = 0
    for _ in range(orders):
        day = rnd.choices(day_list, dweights)[0]
        when = datetime.combine(day, datetime.min.time(), IST) + timedelta(hours=rnd.randint(8, 21), minutes=rnd.randint(0, 59))
        if when > datetime.now(IST):
            when = datetime.now(IST) - timedelta(minutes=rnd.randint(5, 600))
        status = rnd.choices([s for s, _ in STATUSES], [w for _, w in STATUSES])[0]
        if (datetime.now(IST) - when) < timedelta(days=3) and status in ("delivered", "returned", "refunded"):
            status = rnd.choice(["confirmed", "packed", "shipped", "out_for_delivery"])  # recent orders can't be finished yet
        user = rnd.choice(customers)
        a = user.addresses[0]
        picks = {}
        for p in rnd.choices(products, pweights, k=rnd.choices([1, 2, 3, 4], [45, 30, 17, 8])[0]):
            picks[p.id] = (p, picks.get(p.id, (p, 0))[1] + rnd.choice([1, 1, 1, 2, 3]))
        subtotal = Decimal(0)
        items = []
        for p, qty in picks.values():
            price = q2(p.final_price)
            line = q2(price * qty)
            subtotal += line
            items.append(OrderItem(product_id=p.id, name=p.name, sku=p.sku, unit_price=price, mrp=q2(p.mrp or price), quantity=qty, line_total=line))
        discount = q2(subtotal * Decimal(rnd.choice([5, 10, 15])) / 100) if rnd.random() < 0.18 else Decimal(0)
        zone = delivery_zone_for(a.pincode)
        delivery = q2(Decimal(str(zone.delivery_fee or 0))) if zone is not None else Decimal(0)
        total = q2(subtotal - discount + delivery)
        tax = q2((subtotal - discount) * rate / (Decimal(100) + rate)) if rate > 0 else Decimal(0)
        method = rnd.choices(["cod", "online", "upi_manual"], [40, 35, 25])[0]
        paid = status in ("delivered", "out_for_delivery", "shipped", "packed", "confirmed") and (method != "cod" or status == "delivered")
        pay_status = "refunded" if status in ("refunded",) else "failed" if status == "rejected" and method == "online" and rnd.random() < .3 else "paid" if paid else "pending"
        n = seq[day] = seq.get(day, 0) + 1
        o = Order(order_number=f"{PREFIX}{day:%y%m%d}-{n:04d}", user_id=user.id, status=status,
                  rejection_reason="Out of stock (mock)" if status == "rejected" else None,
                  shipping_address={"full_name": a.full_name, "phone": a.phone, "line1": a.line1, "line2": None, "city": a.city,
                                    "state": a.state, "pincode": a.pincode},
                  subtotal=q2(subtotal), discount_total=discount, delivery_fee=delivery, tax_total=tax, total=total,
                  payment_method=method, payment_status=pay_status, created_at=when.astimezone(timezone.utc),
                  updated_at=when.astimezone(timezone.utc))
        o.items = items
        steps = FLOW[: FLOW.index(status) + 1] if status in FLOW else FLOW[: DEAD[status]] + [status]
        t = when
        prev = None
        for s in steps:
            o.history.append(OrderStatusHistory(from_status=prev, to_status=s, note="Mock data", created_at=t.astimezone(timezone.utc)))
            prev, t = s, t + timedelta(hours=rnd.randint(2, 20))
        db.session.add(o)
        made += 1
    db.session.commit()
    return {"orders": made, "customers": len(customers), "products": len(products), "days": days}
