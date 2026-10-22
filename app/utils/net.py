"""Outbound network helpers.

Some Linux hosts resolve public hostnames to IPv6 addresses first but have no
working IPv6 route to the internet. Python's socket layer tries the addresses
in the order the resolver returns them and raises ``ConnectError`` on the
first failure instead of falling back to IPv4, so every Gemini call dies even
though IPv4 works perfectly.

Browsers hide this because they implement Happy Eyeballs (racing IPv4/IPv6),
which is why the same machine can load google.com in Brave while the backend
cannot reach the API.

``prefer_ipv4`` makes outbound connections deterministic by ordering IPv4
addresses ahead of IPv6 ones during DNS resolution. It is a no-op on hosts
where IPv6 works or is absent, and it never disables IPv6 outright — it only
reorders candidates so a broken IPv6 route cannot mask a healthy IPv4 one.
"""

from __future__ import annotations

import logging
import socket

logger = logging.getLogger("companion.net")

_APPLIED = False


def _install() -> None:
    original = socket.getaddrinfo

    def getaddrinfo_ipv4_first(host, port, family=0, type=0, proto=0, flags=0):
        results = original(host, port, family, type, proto, flags)
        if family != socket.AF_UNSPEC or not results:
            return results
        # Stable partition: all IPv4 entries first, then everything else.
        ipv4 = [r for r in results if r[0] == socket.AF_INET]
        rest = [r for r in results if r[0] != socket.AF_INET]
        return ipv4 + rest if ipv4 and rest else results

    socket.getaddrinfo = getaddrinfo_ipv4_first  # type: ignore[assignment]


def prefer_ipv4() -> bool:
    """Install IPv4-first DNS ordering once. Returns True if it was applied.

    Controlled by COMPANION_PREFER_IPV4 (default on); set it to 0 to opt out on a
    host with fully working IPv6.
    """
    global _APPLIED
    if _APPLIED:
        return True

    import os

    if os.getenv("COMPANION_PREFER_IPV4", "1").strip().lower() in {"0", "false", "no", "off"}:
        logger.info("IPv4 preference disabled via COMPANION_PREFER_IPV4")
        return False

    # Only reorder when IPv6 is actually unusable — avoids changing behaviour
    # on healthy dual-stack machines.
    if _ipv6_usable():
        logger.debug("IPv6 reachable; leaving resolver order untouched")
        return False

    _install()
    _APPLIED = True
    logger.info("IPv6 looks unreachable; preferring IPv4 for outbound connections")
    return True


def _ipv6_usable(timeout: float = 1.5) -> bool:
    """Cheap probe: can we open any IPv6 connection to the outside world?"""
    try:
        infos = socket.getaddrinfo("dns.google", 443, socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        return False
    for _family, _type, _proto, _canon, sockaddr in infos:
        try:
            with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect(sockaddr)
                return True
        except OSError:
            continue
    return False
