import click

from .extensions import db


def register_cli(app):
    _register_combo_seed(app)

    @app.cli.command("import-rr-foods")
    @click.option("--path", default="app/seed_data/seed_products.csv", show_default=True,
                  type=click.Path(exists=True, dir_okay=False, readable=True))
    @click.option("--archive-others", is_flag=True,
                  help="Also archive (soft-delete, never hard-delete) every product and empty category that is not in the file.")
    @click.option("--dry-run", is_flag=True, help="Check the file and list what would change, then roll everything back.")
    @click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
    def import_rr_foods_command(path, archive_others, dry_run, yes):
        """Import the 20 RR FOODS products (app/seed_data/seed_products.csv) into the configured database."""
        import csv
        import io
        from pathlib import Path
        from sqlalchemy import func, select
        from .admin.csvio import import_csv
        from .models import Category, Product
        raw = Path(path).read_bytes()
        keep_skus = {r["sku"].strip().upper() for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))) if r.get("sku")}
        keep_categories = {r["category"].strip().lower() for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))) if r.get("category")}
        with_stock = db.session.scalars(select(Product).where(func.upper(Product.sku).in_(keep_skus), Product.stock_qty > 0)).all()
        if with_stock:
            click.echo(f"WARNING: {len(with_stock)} of these products currently have stock; this import sets their stock to 0 "
                       "(the file says stock 0). Run the import once, before you enter real stock.", err=True)
        if not (yes or dry_run):
            click.confirm("Import the RR FOODS product records? Existing matching SKUs will be updated"
                          + (" and every other product will be archived." if archive_others else "."), abort=True)
        result = import_csv(raw, create_categories=True, default_stock=0)
        if result.errors:
            db.session.rollback()
            for error in result.errors:
                click.echo(f"ERROR: {error}", err=True)
            raise click.ClickException("No products were imported. Fix the CSV errors and retry.")
        click.echo(f"RR FOODS import {'check' if dry_run else 'complete'}: {result.created} created/{result.updated} updated, 0 errors "
                   f"({result.created + result.updated} products).")
        if archive_others:
            others = db.session.scalars(select(Product).where(Product.is_deleted.is_(False), func.upper(Product.sku).not_in(keep_skus))
                                        .order_by(Product.sku)).all()
            click.echo(f"Products not in the file ({len(others)}) -> archived (orders and history are kept, they can be restored in Admin):")
            for product in others:
                product.archive()
                click.echo(f"  {product.sku}  {product.name}")
            db.session.flush()
            empty = []
            for category in db.session.scalars(select(Category).where(Category.is_deleted.is_(False))).all():
                if category.name.strip().lower() in keep_categories:
                    continue
                if not db.session.scalar(select(func.count(Product.id)).where(Product.category_id == category.id, Product.is_deleted.is_(False))):
                    category.archive()
                    empty.append(category.name)
            click.echo(f"Empty categories archived ({len(empty)}): " + (", ".join(empty) or "none"))
        if dry_run:
            db.session.rollback()
            click.echo("Dry run: nothing was saved.")
            return
        db.session.commit()
        click.echo("All imported stock quantities are zero; enter verified inventory before enabling sales.")

    @app.cli.command("create-user")
    @click.argument("email")
    @click.argument("name")
    @click.option("--role", type=click.Choice(["user", "owner", "admin"]), default="user")
    @click.password_option()
    def create_user_command(email, name, role, password):
        """Create one account."""
        from .models import User
        from .models.base import utcnow
        from .security import hash_password

        db.session.add(User(email=email, name=name, role=role, password_hash=hash_password(password), email_verified_at=utcnow()))
        db.session.commit()
        click.echo(f"Created {role} {email}")

    @app.cli.command("reset-password")
    @click.argument("email")
    @click.password_option(prompt="New password")
    def reset_password_command(email, password):
        """Set a new password for an existing account (use this if you are locked out of admin)."""
        from sqlalchemy import func, select

        from .auth.passwords import password_problems
        from .models import User
        from .security import hash_password

        user = db.session.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
        if user is None:
            raise click.ClickException(f"No account with the email {email}.")
        problems = password_problems(password, user.email, user.name)
        if problems:
            raise click.ClickException(" ".join(problems))
        user.password_hash = hash_password(password)
        user.failed_login_count = 0
        user.locked_until = None
        db.session.commit()
        click.echo(f"Password updated for {user.role} {user.email}. Every device signed in as this account is now signed out.")


def register_settings_cli(app):
    @app.cli.command("set-setting")
    @click.argument("key")
    @click.argument("value")
    def set_setting_command(key, value):
        """Change a site setting. VALUE is JSON: flask set-setting tax_percent 5 | header_carousel_autoplay true"""
        import json

        from .models import SiteSetting

        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = value
        row = db.session.get(SiteSetting, key)
        if row is None:
            db.session.add(SiteSetting(key=key, value=parsed))
        else:
            row.value = parsed
        db.session.commit()
        click.echo(f"{key} = {parsed!r}")


def register_mail_cli(app):
    @app.cli.command("send-emails")
    def send_emails_command():
        """Send queued emails (order updates, password resets). Run every minute from cron: * * * * * flask send-emails"""
        from .services.mailer import deliver_pending

        sent, failed = deliver_pending()
        click.echo(f"sent {sent}, failed {failed}")


def register_stock_alert_cli(app):
    @app.cli.command("send-stock-alerts")
    def send_stock_alerts_command():
        """Tell customers when a product they asked about is back in stock. Run every 5 minutes from cron (catches every way stock can change)."""
        from .services.stock_alerts import notify_restocked

        click.echo(f"notified {notify_restocked()}")


def register_order_request_cli(app):
    @app.cli.command("expire-order-requests")
    @click.option("--hours", default=48, show_default=True, help="Close requests never sent on WhatsApp after this many hours.")
    def expire_order_requests_command(hours):
        """Close checkout requests whose WhatsApp message never reached the shop. They hold no stock, so nothing is given back."""
        from .extensions import db
        from .services.orders import expire_stale_requests

        n = expire_stale_requests(hours)
        db.session.commit()
        click.echo(f"closed {n}")


def register_check_cli(app):
    @app.cli.command("check-config")
    def check_config_command():
        """Check .env for unsafe production settings. Exit code 1 if something must be fixed."""
        from .prodcheck import config_problems, is_production

        fatal, advice = config_problems(app)
        if not is_production(app):
            click.echo("Note: FLASK_ENV is not 'production', so these are what WOULD be refused in production.")
        for m in fatal:
            click.echo(f"[FIX]    {m}")
        for m in advice:
            click.echo(f"[ADVICE] {m}")
        click.echo(f"{len(fatal)} to fix, {len(advice)} advice.")
        raise SystemExit(1 if fatal else 0)


def _register_combo_seed(app):
    @app.cli.command("seed-combo")
    def seed_combo():
        """Create the Rs 999 RR FOODS combo bundle from the 7 catalogue products (safe to run again).

        Also removes the old Children's Day bundle if an earlier version of this project created it.
        """
        from sqlalchemy import select
        from .models import Bundle, Product
        from .services.product_catalogue import CATALOGUE_COMBO_OFFER
        from .shop.catalog import COMBO_BUNDLE_SLUG, ensure_catalogue_combo_bundle

        old = db.session.scalar(select(Bundle).where(Bundle.slug == "childrens-day-special-combo-opening-day-combo"))
        if old is not None:
            db.session.delete(old)
            db.session.commit()
            click.echo("Removed the old Children's Day bundle.")
        had = db.session.scalar(select(Bundle.id).where(Bundle.slug == COMBO_BUNDLE_SLUG)) is not None
        bundle = ensure_catalogue_combo_bundle()
        if bundle is None:
            raise click.ClickException("Combo not created: none of its products are in the database. Run flask import-rr-foods --yes first.")
        skus = [i["sku"] for i in CATALOGUE_COMBO_OFFER["items"]]
        prods = {p.sku: p for p in db.session.scalars(select(Product).where(Product.sku.in_(skus)))}
        missing = [s for s in skus if s not in prods]
        mrp = sum(float(prods[s].mrp) for s in skus if s in prods)
        click.echo(("Combo already exists; left unchanged." if had else "Created the combo bundle.")
                   + f" Products found {len(skus) - len(missing)}/7, total MRP Rs {mrp:.2f}, bundle price Rs {bundle.bundle_price:.2f}.")
        if missing:
            click.echo("[WARN] Missing SKUs (bundle is hidden until fixed): " + ", ".join(missing))


def register_stock_notification_sync_cli(app):
    @app.cli.command("sync-stock-notifications")
    def sync_stock_notifications_command():
        from .services.inventory import sync_stock_notifications
        from .extensions import db
        count = sync_stock_notifications()
        db.session.commit()
        print(f"Checked {count} products for stock notifications.")


def register_guest_cart_cli(app):
    @app.cli.command("purge-guest-carts")
    @click.option("--days", default=14, show_default=True, type=click.IntRange(min=1), help="Delete guest cart lines older than this many days.")
    def purge_guest_carts_command(days):
        """Delete anonymous (not signed-in) cart lines untouched for N days. Run daily from cron."""
        from .services.cart import purge_guest_carts

        click.echo(f"deleted {purge_guest_carts(days)} guest cart line(s) older than {days} days")


def register_image_cli(app):
    @app.cli.command("optimize-images")
    @click.option("--dry-run", is_flag=True, help="Only report what would change.")
    @click.option("--static", "include_static", is_flag=True,
                  help="Also the images bundled in app/static/img (run it in your checkout and commit the result).")
    def optimize_images_command(dry_run, include_static):
        """Bring images under 100 KB and add the 800 px (and, for bundled photos, 400 px) copies used in srcset.

        Safe to repeat. Product photos in the upload folder get a missing `_m` copy; any image over 100 KB is re-encoded."""
        from pathlib import Path

        from PIL import Image, ImageOps

        from . import imaging
        from .uploads import upload_root

        roots = [(upload_root(), False)]
        if include_static:
            roots.append((Path(app.static_folder) / "img", True))
        saved = shrunk = made = 0
        for root, is_static in roots:
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in {".webp", ".jpg", ".jpeg"}:
                    continue
                before, after = imaging.optimize_file(path, dry_run=dry_run)
                if after < before:
                    shrunk += 1
                    saved += before - after
                    click.echo(f"  {path.relative_to(root)}: {before // 1024} KB -> {after // 1024} KB")
                if imaging.is_variant(path) or path.parent.name != "products" or path.suffix.lower() != ".webp":
                    continue
                if dry_run:
                    continue
                with Image.open(path) as im:
                    im.load()
                    img = ImageOps.exif_transpose(im)
                made += len(imaging.write_variants(img, path, overwrite=False, want_thumb=is_static))
        click.echo(f"{'would shrink' if dry_run else 'shrunk'} {shrunk} image(s), saving {saved // 1024} KB; created {made} responsive copy(ies)")


def register_check_images_cli(app):
    @app.cli.command("check-images")
    @click.option("--all", "include_inactive", is_flag=True, help="Also products that are switched off.")
    @click.option("--strict", is_flag=True, help="Exit with status 1 when any product has no real photo (for CI or cron).")
    def check_images_command(include_inactive, strict):
        """List products that would show the placeholder because they have no real photo."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from .models import Product
        from .placeholders import product_has_real_photo

        stmt = select(Product).options(selectinload(Product.images)).order_by(Product.slug)
        if not include_inactive:
            stmt = stmt.where(Product.is_active.is_(True))
        products = db.session.execute(stmt).scalars().all()
        missing = [p for p in products if not product_has_real_photo(app, p)]
        for p in missing:
            click.echo(f"  {p.slug}  ({p.name})" + ("" if p.is_active else "  [inactive]"))
        click.echo(f"{len(missing)} of {len(products)} product(s) have no real photo (they show the placeholder).")
        if strict and missing:
            raise SystemExit(1)
