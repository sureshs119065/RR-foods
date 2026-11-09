import click

from .extensions import db


def register_cli(app):
    _register_diwali_seed(app)
    @app.cli.command("seed")
    def seed_command():
        """Create sample admin, owner, customer, categories, products, coupon, banners and settings."""
        from .seed import seed_all

        result = seed_all()
        click.echo(f"Products: {result['products']}  Header banners added: {result['header_banners']}")
        click.echo("Accounts (save these passwords now, they are not shown again):")
        for email, pw in result["passwords"].items():
            click.echo(f"  {email}  {pw}")

    @app.cli.command("import-products-csv")
    @click.argument("path", required=False)
    def import_csv_command(path):
        """Import products from the old site's CSV (default: app/seed_data/products.csv)."""
        from .seed import import_products_csv

        click.echo(import_products_csv(path))

    @app.cli.command("import-rr-foods")
    @click.option("--path", default="app/seed_data/seed_products.csv", show_default=True,
                  type=click.Path(exists=True, dir_okay=False, readable=True))
    @click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
    def import_rr_foods_command(path, yes):
        """Import the supplied RR FOODS catalogue into the configured database."""
        from pathlib import Path
        from .admin.csvio import import_csv
        raw = Path(path).read_bytes()
        if not yes:
            click.confirm("Import the RR FOODS product records? Existing matching SKUs will be updated.", abort=True)
        result = import_csv(raw, create_categories=True, default_stock=0)
        if result.errors:
            db.session.rollback()
            for error in result.errors:
                click.echo(f"ERROR: {error}", err=True)
            raise click.ClickException("No products were imported. Fix the CSV errors and retry.")
        db.session.commit()
        click.echo(f"RR FOODS import complete: {result.created} created, {result.updated} updated.")
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


def register_settings_cli(app):
    @app.cli.command("set-setting")
    @click.argument("key")
    @click.argument("value")
    def set_setting_command(key, value):
        """Change a site setting. VALUE is JSON: flask set-setting tax_percent 5 | free_delivery_min_cart 499 | header_carousel_autoplay true"""
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


def register_check_cli(app):
    @app.cli.command("check-config")
    def check_config_command():
        """Check .env for unsafe production settings. Exit code 1 if something must be fixed."""
        from .prodcheck import config_problems, example_accounts_advice, is_production

        fatal, advice = config_problems(app)
        try:
            extra = example_accounts_advice()
            if extra:
                advice.append(extra)
        except Exception as exc:  # noqa: BLE001  database may not be reachable yet
            advice.append(f"Could not look for example accounts ({type(exc).__name__}). Is the database reachable and migrated?")
        if not is_production(app):
            click.echo("Note: FLASK_ENV is not 'production', so these are what WOULD be refused in production.")
        for m in fatal:
            click.echo(f"[FIX]    {m}")
        for m in advice:
            click.echo(f"[ADVICE] {m}")
        click.echo(f"{len(fatal)} to fix, {len(advice)} advice.")
        raise SystemExit(1 if fatal else 0)


def _register_diwali_seed(app):
    @app.cli.command("seed-diwali-combos")
    def seed_diwali_combos():
        """Create three sample Diwali combo records using existing active catalogue products."""
        from decimal import Decimal
        from sqlalchemy import select
        from .models import Bundle, Combo, Product, SiteSetting
        from .seed import slugify
        from .services.storefront import active_variants
        rows = db.session.scalars(select(Product).where(Product.is_active.is_(True), Product.is_deleted.is_(False), Product.final_price > 0, Product.stock_qty > 0).order_by(Product.name)).all()
        products = [p for p in rows if not active_variants(p)]
        if len(products) < 2:
            raise click.ClickException("Import and activate at least two products before seeding Diwali combos.")
        if db.session.scalar(select(Combo.id).limit(1)):
            click.echo("Diwali combos already exist; no duplicate samples were created.")
            return
        plans = [
            ("Biotin Laddu Festive Box", "A festive RR FOODS laddu selection.", ("laddu",)),
            ("Healthy Snack Combo", "A shareable mix of millet and wholesome pantry favourites.", ("muesli", "moringa", "soup")),
            ("Traditional Pantry Gift Hamper", "Traditional RR FOODS pantry favourites, curated for gifting.", ("idli podi", "pickle", "vathal")),
        ]
        used_ids = set()
        for name, description, keywords in plans:
            chosen = []
            for keyword in keywords:
                match = next((p for p in products if keyword in p.name.lower() and p.id not in used_ids), None)
                if match and len(chosen) < 3:
                    chosen.append(match); used_ids.add(match.id)
            if not chosen:
                chosen = [p for p in products if p.id not in used_ids][:2]
                used_ids.update(p.id for p in chosen)
            if not chosen:
                chosen = products[:2]
            original = sum((Decimal(str(p.final_price)) for p in chosen), Decimal("0"))
            if original <= 0: original = Decimal("200.00")
            price = (original * Decimal("0.85")).quantize(Decimal("0.01"))
            slug = slugify(name)
            from .admin.helpers import unique_slug
            bundle = Bundle(name=name, slug=unique_slug(Bundle, f"diwali-{slug}-cart"), description=description,
                product_quantities=[{"product_id": p.id, "quantity": 1} for p in chosen], bundle_price=float(price), is_active=True)
            db.session.add(bundle); db.session.flush()
            db.session.add(Combo(name=name, slug=f"diwali-{slug}", description=description,
                items=[{"product_id": p.id, "quantity": 1} for p in chosen], price=price,
                original_price=original, festival_tag="diwali", is_active=True, bundle=bundle))
        setting = db.session.get(SiteSetting, "diwali_end_at")
        if not setting: db.session.add(SiteSetting(key="diwali_end_at", value="2026-11-12T23:59"))
        db.session.commit()
        click.echo("Created 3 Diwali combos using existing active catalogue products.")

