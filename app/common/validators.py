import re

def validate_password_complexity(value: str) -> str:
    """Shared password rule for any request that sets a user's password
    (login, verify/set-password, ...). Keeping this in one place means the
    password a user is allowed to *set* can never be stricter/looser than
    what they're later required to *log in* with.
    """
    if len(value) < 8 or len(value) > 20:
        raise ValueError("Password must be 8-20 characters long")
    if not re.search(r"[A-Z]", value):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", value):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", value):
        raise ValueError("Password must contain at least one digit")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_]", value):
        raise ValueError("Password must contain at least one special character")
    return value
