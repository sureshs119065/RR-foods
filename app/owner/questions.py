"""Questions & Feedback (product questions + customer messages) for the owner. Shared with the admin: see app/staff_feedback.py."""
from ..staff_feedback import register
from . import bp

register(bp, "owner")
