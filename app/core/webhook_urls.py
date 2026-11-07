"""Checks a webhook URL when it is registered.

This is the FIRST line of defence against SSRF (tricking our server into calling things on a private network,
such as the cloud metadata address 169.254.169.254). It only looks at the text of the URL. It cannot stop a
hostname that is *later* pointed at a private address (DNS rebinding), so the delivery worker must check the
real IP address again at the moment it connects. That second check is the one that matters most.
"""

import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlunsplit

MAX_URL_LENGTH = 2048

_BLOCKED_NAMES = {"localhost", "ip6-localhost", "ip6-loopback"}
# Names that only make sense inside a private network.
_BLOCKED_SUFFIXES = (
    ".localhost", ".local", ".localdomain", ".internal", ".intranet", ".private", ".corp", ".home", ".lan",
)
_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class UnsafeUrl(ValueError):
    """The URL is not allowed. The message says why and never repeats the URL."""


def _looks_like_ip(host: str) -> bool:
    """True for any text a network library might read as an IP address, including odd forms such as
    2130706433, 0x7f.1 or 127.1 (all of which mean 127.0.0.1)."""
    if ":" in host:  # IPv6
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    try:
        socket.inet_aton(host)  # the old, lenient IPv4 parser used by the operating system
        return True
    except OSError:
        return False


def validate_webhook_url(raw_url: str, *, allow_unsafe: bool = False) -> str:
    """Return the cleaned-up URL, or raise UnsafeUrl."""
    if not raw_url or len(raw_url) > MAX_URL_LENGTH:
        raise UnsafeUrl(f"URL must be between 1 and {MAX_URL_LENGTH} characters")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in raw_url):
        raise UnsafeUrl("URL must not contain spaces or control characters")
    if "\\" in raw_url:
        raise UnsafeUrl("URL must not contain backslashes")

    try:
        parts = urlsplit(raw_url)
        port = parts.port
    except ValueError:
        raise UnsafeUrl("URL is not valid") from None

    scheme = parts.scheme.lower()
    allowed_schemes = {"https", "http"} if allow_unsafe else {"https"}
    if scheme not in allowed_schemes:
        raise UnsafeUrl("URL must start with https://")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise UnsafeUrl("URL must not contain a username or password")
    if parts.fragment:
        raise UnsafeUrl("URL must not contain a # fragment")

    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise UnsafeUrl("URL must contain a host name")

    if not allow_unsafe:
        if not host.isascii():
            raise UnsafeUrl("Host name must use ASCII letters (write international names in punycode)")
        if _looks_like_ip(host):
            raise UnsafeUrl("IP addresses are not allowed, use a host name")
        if host in _BLOCKED_NAMES or host.endswith(_BLOCKED_SUFFIXES):
            raise UnsafeUrl("This host name points to a private network")
        labels = host.split(".")
        if len(host) > 253 or len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
            raise UnsafeUrl("Host must be a public domain name such as hooks.example.com")
        if labels[-1].isdigit():
            raise UnsafeUrl("Host must be a public domain name such as hooks.example.com")
        # 443 is normal. Ports below 1024 other than 443 belong to services such as SSH and SMTP.
        if port is not None and port != 443 and not 1024 <= port <= 65535:
            raise UnsafeUrl("Port must be 443 or between 1024 and 65535")

    netloc = host if port is None or (scheme == "https" and port == 443) else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path, parts.query, ""))