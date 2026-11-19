"""Shared input rules for every customer-facing form and query string (step 5.4).

Each checker takes the raw string, returns the cleaned value and, when it is not acceptable, records a message in `errors`
under `field` (the same dict-of-messages the existing forms already show). Nothing here silently truncates a value that
a person typed into a form: too long is an error. Only read-only query strings (search) are trimmed.

Output is escaped by Jinja autoescape. A test fails the build if a template uses |safe, Markup or {% autoescape false %}.
"""
import re
import unicodedata

CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
PINCODE_RE = re.compile(r"[1-9]\d{5}")          # Indian PIN codes never start with 0
PHONE_RE = re.compile(r"[6-9]\d{9}")
COUPON_RE = re.compile(r"[A-Z0-9][A-Z0-9_-]{0,39}")
NAME_PUNCTUATION = set(" .'’-")

MAX = {"name": 120, "label": 40, "line": 200, "city": 80, "state": 80, "subject": 160, "email": 255, "phone_raw": 30,
       "notes": 500, "message": 4000, "search": 80, "password": 128}


def strip_controls(value) -> str:
    """Text with NUL, other control characters and invisible direction overrides removed (newline and tab are kept)."""
    return CONTROL.sub("", value if isinstance(value, str) else "")


def one_line(value) -> str:
    return " ".join(strip_controls(value).split())


def _check_length(text, field, errors, min_, max_, label):
    if len(text) < min_:
        errors[field] = f"{label} must be at least {min_} characters." if min_ > 1 else f"Enter {label.lower()}."
        return False
    if len(text) > max_:
        errors[field] = f"{label} must be {max_} characters or fewer."
        return False
    return True


def text_line(value, field, errors, *, label="This field", min_=0, max_=200, required=True) -> str:
    """One line of free text (address line, subject, label)."""
    text = one_line(value)
    if not text:
        if required:
            errors[field] = f"Enter {label.lower()}."
        return ""
    if "<" in text or ">" in text:
        errors[field] = f"{label} cannot contain < or >."
        return text
    _check_length(text, field, errors, min_, max_, label)
    return text


def person_name(value, field, errors, *, label="Name", min_=2, max_=MAX["name"], required=True) -> str:
    """Letters in any script (including Tamil vowel signs), spaces and . ' - only."""
    text = one_line(value)
    if not text:
        if required:
            errors[field] = f"Enter {label.lower()}."
        return ""
    if not all(unicodedata.category(ch)[0] in ("L", "M") or ch in NAME_PUNCTUATION for ch in text):
        errors[field] = f"{label} can only use letters, spaces and . ' -"
        return text
    _check_length(text, field, errors, min_, max_, label)
    return text


def phone(value, field, errors, *, required=True) -> str:
    """Indian mobile: 10 digits starting 6-9. A leading 0, 91 or +91 is accepted. Other characters must be spaces, - or ()."""
    raw = strip_controls(value)
    if len(raw) > MAX["phone_raw"] or re.search(r"[^\d\s+()-]", raw):
        errors[field] = "Enter a 10 digit mobile number."
        return ""
    digits = re.sub(r"\D", "", raw)
    if not digits:
        if required:
            errors[field] = "Enter a 10 digit mobile number."
        return ""
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not PHONE_RE.fullmatch(digits):
        errors[field] = "Enter a 10 digit mobile number."
        return ""
    return digits


def pincode(value, field, errors) -> str:
    text = re.sub(r"\s", "", strip_controls(value))
    if not PINCODE_RE.fullmatch(text):
        errors[field] = "Enter a 6 digit pincode."
        return text[:12]
    return text


def is_pincode(value) -> bool:
    return isinstance(value, str) and bool(PINCODE_RE.fullmatch(value))


def multiline(value, field, errors, *, label="Message", min_=0, max_=MAX["message"], required=False) -> str:
    """Several lines of free text (order notes, enquiry message). Line breaks are kept, other control characters removed."""
    text = "\n".join(line.rstrip() for line in strip_controls(value).replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()
    if not text:
        if required:
            errors[field] = f"Enter {label.lower()}."
        return ""
    _check_length(text, field, errors, min_, max_, label)
    return text


def coupon_code(value, field, errors) -> str:
    """Upper-case, spaces removed, then letters, digits, - and _ only (max 40)."""
    code = "".join(strip_controls(value).upper().split())
    if not code:
        errors[field] = "Enter a coupon code."
        return ""
    if not COUPON_RE.fullmatch(code):
        errors[field] = "A coupon code uses only letters, numbers, - and _ (up to 40 characters)."
        return code[:40]
    return code


def search_query(value, limit=MAX["search"]) -> str:
    """Search text from the URL: controls removed, spaces collapsed, cut to `limit`. Never an error, so a long paste still searches."""
    return one_line(value)[:limit]


def email_address(value, field, errors, valid) -> str:
    """`valid` is the existing auth.passwords.valid_email, passed in to keep this module free of imports."""
    text = strip_controls(value).strip().lower()
    if len(text) > MAX["email"] or not valid(text):
        errors[field] = "Enter a valid email address."
    return text
