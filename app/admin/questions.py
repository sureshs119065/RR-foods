"""Questions & Feedback (product questions + customer messages) for the admin. Shared with the owner: see app/staff_feedback.py."""
from ..staff_feedback import register
from . import bp

register(bp, "admin")
