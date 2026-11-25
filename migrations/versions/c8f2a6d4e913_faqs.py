"""customer FAQs (table + starter questions)

Revision ID: c8f2a6d4e913
Revises: b9e4d2a6c715
"""
from alembic import op
import sqlalchemy as sa

revision = "c8f2a6d4e913"
down_revision = "b9e4d2a6c715"
branch_labels = None
depends_on = None

# Starter questions. They describe how the shop works today (WhatsApp ordering, no online returns); the admin can edit them.
SEED = [
    ("How does delivery work?",
     "We deliver to the pincodes we serve. Add your address at checkout and we show whether we deliver there, the delivery charge "
     "and the expected delivery time before you place your request."),
    ("How do I pay for my order?",
     "Payment is settled on WhatsApp. Nothing is charged on the website. After the shop confirms your order it shares the payment "
     "details with you, and your order is marked paid once the shop receives your payment."),
    ("Can I return or exchange a product?",
     "Returns are not available online at the moment. If something is damaged, wrong or not as expected, message us on WhatsApp "
     "or use the contact page and the team will look into it with you."),
    ("How can I track my order?",
     "Sign in and open My orders, then choose your order. The page shows each step and updates by itself. When the order is "
     "dispatched, the courier name and tracking ID appear there too."),
    ("How do you keep your products fresh and good quality?",
     "Ingredients are sourced from trusted farmers, cleaned and sorted, processed in small batches and packed in food-grade "
     "packaging. We add no preservatives to our recipes. You can read the full journey on our About page."),
    ("How does ordering on WhatsApp work?",
     "Choose your products, add your delivery details and place your order request. Then tap the WhatsApp button and press Send "
     "in WhatsApp. Your order is placed only after the shop receives your message and confirms it."),
    ("What if my order message did not go through on WhatsApp?",
     "Nothing is ordered and nothing is charged until the shop receives your message. If WhatsApp did not open or the message "
     "failed, copy the message from the order page and send it again, or contact us for help."),
]


def upgrade():
    faqs = op.create_table(
        "faqs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question", sa.String(length=300), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_faqs_active_order", "faqs", ["is_active", "sort_order"])
    op.bulk_insert(faqs, [{"question": q, "answer": a, "sort_order": (i + 1) * 10, "is_active": True} for i, (q, a) in enumerate(SEED)])


def downgrade():
    op.execute("DELETE FROM site_settings WHERE key = 'home_faq'")
    op.drop_index("ix_faqs_active_order", table_name="faqs")
    op.drop_table("faqs")
