from typing import Annotated

from pydantic import BeforeValidator, StringConstraints

# Lowercase letters and digits, with single hyphens between parts: "acme", "acme-payments-2".
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


def _clean_slug(value):
    # Runs before the checks, so "  Acme-Pay " is accepted and stored as "acme-pay".
    return value.strip().lower() if isinstance(value, str) else value


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Slug = Annotated[
    str,
    StringConstraints(min_length=3, max_length=50, pattern=SLUG_PATTERN),
    BeforeValidator(_clean_slug),  # listed last, it wraps the checks above and runs first
]