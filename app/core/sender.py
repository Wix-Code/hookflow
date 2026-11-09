"""Sends one signed webhook request, safely. Knows nothing about the database.

Safety rules applied here:
  * the stored URL is checked again (rules can change after an endpoint was registered)
  * the host name is looked up ONCE; every address must be public (netsafety.py)
  * we connect to that checked address, not to the name, so no second lookup can be tricked
  * the name is still used for the Host header and for checking the HTTPS certificate
  * redirects are never followed (a redirect could point at a private address)
  * proxy environment variables are ignored (a proxy would do its own, unchecked, lookup)
  * the response body is never read or stored; we only need the status code
  * errors are reported as short codes, never as exception text (that can contain addresses or URLs)
"""

import socket
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings
from app.core.netsafety import BlockedDestination, DnsFailure, is_public_ip, resolve_public_addresses
from app.core.webhook_urls import UnsafeUrl, validate_webhook_url


class Outcome(StrEnum):
    SUCCESS = "success"
    RETRY = "retry"  # try again later
    PERMANENT = "permanent"  # trying again will not help


@dataclass(frozen=True)
class SendResult:
    outcome: Outcome
    status_code: int | None
    error: str | None  # a short safe code such as "timeout" or "http_500"
    duration_ms: int


def classify_status(status_code: int) -> tuple[Outcome, str | None]:
    if 200 <= status_code < 300:
        return Outcome.SUCCESS, None
    if 300 <= status_code < 400:
        return Outcome.PERMANENT, "redirect_not_followed"
    if status_code in (408, 429) or status_code >= 500:
        return Outcome.RETRY, f"http_{status_code}"
    return Outcome.PERMANENT, f"http_{status_code}"


def _allow_everything(_address: str) -> bool:
    return True


def _is_tls_problem(exc: BaseException) -> bool:
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, ssl.SSLError):
            return True
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return False


def send_webhook(
    url: str,
    body: bytes,
    headers: dict[str, str],
    settings: Settings,
    *,
    resolver: Callable = socket.getaddrinfo,
    is_allowed: Callable[[str], bool] | None = None,
    ssl_context: ssl.SSLContext | None = None,
) -> SendResult:
    """The last three arguments exist so tests can use a fake DNS, a local server and a test certificate."""
    started = time.monotonic()

    def result(outcome: Outcome, status_code: int | None, error: str | None) -> SendResult:
        return SendResult(outcome, status_code, error, int((time.monotonic() - started) * 1000))

    development = settings.allow_unsafe_webhook_urls
    try:
        clean = validate_webhook_url(url, allow_unsafe=development)
    except UnsafeUrl:
        return result(Outcome.PERMANENT, None, "url_not_allowed")

    parts = urlsplit(clean)
    host, scheme = parts.hostname, parts.scheme
    port = parts.port or (443 if scheme == "https" else 80)
    policy = is_allowed or (_allow_everything if development else is_public_ip)

    try:
        addresses = resolve_public_addresses(host, port, is_allowed=policy, resolver=resolver)
    except BlockedDestination:
        return result(Outcome.PERMANENT, None, "destination_blocked")
    except DnsFailure:
        return result(Outcome.RETRY, None, "dns_failure")

    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    send_headers = {**headers, "Host": parts.netloc}  # the real name, even though we connect to an address
    extensions = {"sni_hostname": host} if scheme == "https" else {}
    timeout = httpx.Timeout(settings.delivery_timeout_seconds, connect=min(5.0, settings.delivery_timeout_seconds))

    last_error = "connect_error"
    for address in addresses:  # normally one; more only if an address cannot be connected to at all
        literal = f"[{address}]" if ":" in address else address
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                verify=ssl_context if ssl_context is not None else True,
            ) as client:
                with client.stream(
                    "POST",
                    f"{scheme}://{literal}:{port}{target}",
                    content=body,
                    headers=send_headers,
                    extensions=extensions,
                ) as response:
                    outcome, error = classify_status(response.status_code)
                    return result(outcome, response.status_code, error)
        except httpx.ConnectTimeout:
            last_error = "timeout"
        except httpx.ConnectError as exc:
            last_error = "tls_error" if _is_tls_problem(exc) else "connect_error"
        except httpx.TimeoutException:
            return result(Outcome.RETRY, None, "timeout")  # connected, so the request may have arrived: do not try another address
        except httpx.TransportError:
            return result(Outcome.RETRY, None, "network_error")
    return result(Outcome.RETRY, None, last_error)