# WhatsApp-first ordering (replaces COD / online payment)

Flow: place order on the site -> "Order placed" page opens WhatsApp with the order already written -> owner takes payment on
WhatsApp -> owner confirms the order in the owner panel (optionally ticking "Payment already received") -> Packed / Shipped / Delivered.

## Setup
1. In `.env` set `ADMIN_WHATSAPP_NUMBER` (country code, digits only, e.g. 919876543210). Optional: `DEFAULT_COUNTRY_CODE`, `SHOP_NAME`.
2. No database migration is needed (`upi_manual` was already an allowed payment method).
3. Run the tests: `pytest tests/test_whatsapp_orders.py tests/test_step6_shop.py tests/test_step8_prodcheck.py`.

## What changed
New:
- `app/services/whatsapp.py`       wa.me links and the written messages (customer -> owner, owner -> customer)
- `app/templates/shop/order_placed.html`   big "Send order on WhatsApp" button, message preview, Copy message
- `tests/test_whatsapp_orders.py`

Changed:
- `app/services/checkout.py`   one payment method (`upi_manual`), payment provider `upi_manual`
- `app/services/orders.py`     `change_status(..., mark_paid=)`, new `set_payment()` (Paid / Not paid, history, audit, notification)
- `app/shop/checkout.py`       stub gateway routes (/pay, /pay/.../simulate) removed; new `/order-placed/<order_number>`
- `app/owner/orders.py`        paid flag on confirm, `POST /owner/orders/<id>/payment`, "Not paid only" filter, first tab renamed "Awaiting confirmation"
- templates: `shop/checkout.html`, `shop/order.html`, `shop/orders.html`, `owner/order_detail.html`, `owner/orders.html`,
  `owner/_macros.html` (Paid / Not paid badge), `admin/orders.html`, `admin/order_detail.html` (Payment column + WhatsApp button)
- `app/config.py`, `.env*.example`, `app/prodcheck.py` (`ONLINE_PAYMENT_MODE` removed; warns if the WhatsApp number is empty)
- `app/static/js/shop.js` (Copy message), `app/static/css/shop.css` (green WhatsApp button)
- `app/__init__.py` (template helpers `wa_owner_link`, `wa_customer_link`, `wa_order_text`)
- `README.md`, `RR-FOODS-README.md`, and the affected tests

Removed: `app/templates/shop/pay.html`.

Old orders placed as cash on delivery or online still display and work.

## Later (optional)
WhatsApp Cloud API buttons can call `services.orders.change_status` and `set_payment` from a webhook with no other change.
