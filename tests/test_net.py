"""Tests for the IPv4-preference shim.

The host this project runs on resolves public names to IPv6 first but has no
working IPv6 route, which made every Gemini call fail with ConnectError while
browsers worked fine. These tests pin the reordering behaviour so a regression
cannot silently reintroduce the outage.
"""

from __future__ import annotations

import socket

import pytest

from app.utils import net


@pytest.fixture(autouse=True)
def _restore_getaddrinfo():
    original = socket.getaddrinfo
    original_applied = net._APPLIED
    yield
    socket.getaddrinfo = original
    net._APPLIED = original_applied


def _fake_results(*families):
    return [
        (fam, socket.SOCK_STREAM, 6, "", ("::1" if fam == socket.AF_INET6 else "127.0.0.1", 443))
        for fam in families
    ]


def test_install_reorders_ipv4_first(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_results(
        socket.AF_INET6, socket.AF_INET
    ))
    net._APPLIED = False
    net._install()

    ordered = socket.getaddrinfo("example.com", 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
    assert ordered[0][0] == socket.AF_INET
    assert ordered[-1][0] == socket.AF_INET6


def test_install_is_noop_when_family_is_explicit(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_results(socket.AF_INET6))
    net._APPLIED = False
    net._install()

    ordered = socket.getaddrinfo("example.com", 443, socket.AF_INET6, socket.SOCK_STREAM)
    assert ordered == _fake_results(socket.AF_INET6)


def test_install_leaves_single_family_untouched(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_results(socket.AF_INET))
    net._APPLIED = False
    net._install()

    assert socket.getaddrinfo("example.com", 443, socket.AF_UNSPEC, socket.SOCK_STREAM) == \
        _fake_results(socket.AF_INET)


def test_prefer_ipv4_respects_opt_out(monkeypatch):
    monkeypatch.setenv("COMPANION_PREFER_IPV4", "0")
    net._APPLIED = False
    assert net.prefer_ipv4() is False


def test_prefer_ipv4_skips_when_ipv6_healthy(monkeypatch):
    monkeypatch.delenv("COMPANION_PREFER_IPV4", raising=False)
    monkeypatch.setattr(net, "_ipv6_usable", lambda timeout=1.5: True)
    net._APPLIED = False
    assert net.prefer_ipv4() is False


def test_prefer_ipv4_installs_when_ipv6_broken(monkeypatch):
    monkeypatch.delenv("COMPANION_PREFER_IPV4", raising=False)
    monkeypatch.setattr(net, "_ipv6_usable", lambda timeout=1.5: False)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_results(socket.AF_INET))
    net._APPLIED = False
    assert net.prefer_ipv4() is True


def test_ipv6_probe_returns_false_without_dns(monkeypatch):
    def boom(*_a, **_k):
        raise socket.gaierror("no AAAA")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    assert net._ipv6_usable() is False
