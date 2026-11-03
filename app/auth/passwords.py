"""Password and input rules for sign up, password change and (later) reset."""
import re

COMMON = {
    "password", "password1", "password123", "12345678", "123456789", "1234567890", "qwerty123", "qwertyuiop",
    "iloveyou", "admin123", "welcome1", "welcome123", "letmein123", "abc12345", "11111111", "00000000",
}
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}$")


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match(value)) and len(value) <= 255


def normalize_phone(value: str) -> str | None:
    """Indian mobile number: 10 digits starting 6-9 (a leading 91 or +91 is accepted). Empty is allowed."""
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        return None
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits if re.fullmatch(r"[6-9]\d{9}", digits) else ""


def password_problems(password: str, email: str = "", name: str = "") -> list[str]:
    problems = []
    if len(password) < 8:
        problems.append("Use at least 8 characters.")
    if len(password) > 128:
        problems.append("Use 128 characters or fewer.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        problems.append("Include at least one letter and one number.")
    low = password.lower()
    if low in COMMON:
        problems.append("That password is too common.")
    if email and low == email.lower() or (email and email.split("@")[0] and len(email.split("@")[0]) >= 4 and low == email.split("@")[0].lower()):
        problems.append("Do not use your email as your password.")
    return problems
