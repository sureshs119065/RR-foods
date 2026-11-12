r"""Add or update deliverable pincodes in the database that DATABASE_URL points to.

Usage (PowerShell, inside the nk-platform folder):
  $env:DATABASE_URL = "<External Database URL>"
  .\.venv\Scripts\python.exe add_pincodes.py 641001 641002 641003 --eta 2 --fee 0
  .\.venv\Scripts\python.exe add_pincodes.py --list
  .\.venv\Scripts\python.exe add_pincodes.py 641099 --disable      (stop delivering there)
"""
import argparse
import re

from app import create_app
from app.extensions import db
from app.models import DeliveryZone

ap = argparse.ArgumentParser()
ap.add_argument("pincodes", nargs="*", help="6 digit pincodes")
ap.add_argument("--eta", type=int, default=None, help="delivery days (new pincodes default to 2)")
ap.add_argument("--fee", type=float, default=None, help="delivery fee in rupees (new pincodes default to 0)")
ap.add_argument("--disable", action="store_true", help="mark these pincodes as not deliverable")
ap.add_argument("--city", default=None, help="optional city returned by the pincode helper")
ap.add_argument("--state", default=None, help="optional state returned by the pincode helper")
ap.add_argument("--list", action="store_true", help="show current pincodes and exit")
args = ap.parse_args()

app = create_app()
with app.app_context():
    if args.list or not args.pincodes:
        rows = db.session.scalars(db.select(DeliveryZone).order_by(DeliveryZone.pincode)).all()
        print(f"{len(rows)} pincode(s) in database")
        for z in rows:
            print(z.pincode, "deliverable" if z.is_serviceable else "DISABLED", f"eta={z.eta_days}d", f"fee={z.delivery_fee}")
        raise SystemExit(0)

    bad = [p for p in args.pincodes if not re.fullmatch(r"[1-9][0-9]{5}", p)]
    if bad:
        raise SystemExit("Not valid 6 digit pincodes: " + ", ".join(bad))
    added = updated = 0
    for pin in dict.fromkeys(args.pincodes):
        zone = db.session.get(DeliveryZone, pin)
        if zone is None:
            db.session.add(DeliveryZone(pincode=pin, is_serviceable=not args.disable, eta_days=2 if args.eta is None else args.eta, delivery_fee=0 if args.fee is None else args.fee, city=args.city, state=args.state))
            added += 1
        else:
            zone.is_serviceable = not args.disable
            if args.eta is not None:
                zone.eta_days = args.eta
            if args.fee is not None:
                zone.delivery_fee = args.fee
            if args.city is not None:
                zone.city = args.city.strip()[:80]
            if args.state is not None:
                zone.state = args.state.strip()[:80]
            updated += 1
    db.session.commit()
    print(f"Done: {added} added, {updated} updated.")