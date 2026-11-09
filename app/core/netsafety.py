"""Decides whether a network address is safe to send a webhook to, and looks host names up safely.

This is the SECOND and stronger SSRF defence. The URL check at registration (webhook_urls.py) only reads text.
Here we look at the real IP addresses a host name points to, at the moment we are about to connect, and we
connect to the exact address we checked (see sender.py). Nothing looks the name up a second time, so a name
that changes its answer between the check and the connection (DNS rebinding) gets no chance.
"""

import ipaddress
import socket
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

DNS_TIMEOUT_SECONDS = 5.0
MAX_ADDRESSES_TRIED = 3

# Ranges that can hide or reach private addresses even though they look public.
_EXTRA_BLOCKED = [
    ipaddress.ip_network(net)
    for net in (
        "64:ff9b::/96",  # NAT64: can carry any IPv4 address, including private ones
        "64:ff9b:1::/48",
        "2002::/16",  # 6to4
        "2001::/32",  # Teredo
        "::/96",  # old IPv4-compatible IPv6
        "100.64.0.0/10",  # shared address space used inside carrier networks
        "192.88.99.0/24",  # retired 6to4 relay
    )
]

# The operating system's lookup cannot be given a time limit, so it runs in a helper thread we can stop waiting for.
_dns_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="dns")


class DnsFailure(Exception):
    """The host name could not be looked up (worth retrying later)."""


class BlockedDestination(Exception):
    """At least one address the name points to is not a public address (not worth retrying)."""


def is_public_ip(value: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    try:
        ip = ipaddress.ip_address(value) if isinstance(value, str) else value
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 is really 127.0.0.1
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        return False
    return not any(ip.version == net.version and ip in net for net in _EXTRA_BLOCKED)


def resolve_public_addresses(
    host: str,
    port: int,
    *,
    is_allowed: Callable[[str], bool] = is_public_ip,
    resolver: Callable = socket.getaddrinfo,
) -> list[str]:
    """Look the host up once. Return its addresses only if EVERY one of them is allowed.

    One bad address in the answer blocks the whole name: a name that sometimes points at a private address
    is exactly what an attacker would set up.
    """
    future = _dns_pool.submit(resolver, host, port, type=socket.SOCK_STREAM)
    try:
        infos = future.result(timeout=DNS_TIMEOUT_SECONDS)
    except FutureTimeout:
        raise DnsFailure("dns_timeout") from None
    except OSError:
        raise DnsFailure("dns_failure") from None

    addresses = list(dict.fromkeys(str(info[4][0]) for info in infos))
    if not addresses:
        raise DnsFailure("dns_failure")
    if not all(is_allowed(address) for address in addresses):
        raise BlockedDestination("destination_blocked")
    return addresses[:MAX_ADDRESSES_TRIED]