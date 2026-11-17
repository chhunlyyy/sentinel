"""Where the server may listen and who may talk to it: the container exception to the loopback-only rule.

Outside a container the server binds 127.0.0.1 and nothing else. Inside the Sentinel container image it may bind 0.0.0.0
(Docker needs that to publish a port), and then it answers only a loopback peer or the container's default gateway, which
is where a port published as `-p 127.0.0.1:PORT:PORT` arrives from. `--allow-peer IP` adds addresses for set-ups where
the gateway differs (rootless Docker, Docker Desktop).
"""
import ipaddress
import os
import socket
import struct

MARKERS = ("/.dockerenv", "/run/.containerenv")
ROUTE_FILE = "/proc/net/route"


def _hook(name):
    """A test-only override (only with SENTINEL_TEST_MODE=1), the same rule as the other test settings."""
    if os.environ.get("SENTINEL_TEST_MODE") == "1":
        return os.environ.get(name)
    return None


def container_ok():
    """SENTINEL_CONTAINER=1 and evidence that this process really runs in a container."""
    if os.environ.get("SENTINEL_CONTAINER") != "1":
        return False
    hooked = _hook("SENTINEL_TEST_CONTAINER_MARKERS")
    markers = hooked.split(os.pathsep) if hooked is not None else MARKERS
    return any(m and os.path.exists(m) for m in markers)


def default_gateways():
    """The IPv4 addresses of the default routes in the route table (empty when it cannot be read)."""
    path = _hook("SENTINEL_TEST_ROUTE_FILE") or ROUTE_FILE
    out = set()
    try:
        with open(path, encoding="ascii") as f:
            rows = f.read().splitlines()[1:]
    except (OSError, UnicodeDecodeError):
        return out
    for row in rows:
        f = row.split()
        try:
            if len(f) >= 8 and int(f[1], 16) == 0 and int(f[7], 16) == 0:
                out.add(socket.inet_ntoa(struct.pack("<L", int(f[2], 16))))
        except (ValueError, struct.error, OverflowError):
            continue
    return out


def _addr(text):
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None
    return ip.ipv4_mapped if getattr(ip, "ipv4_mapped", None) else ip


def is_loopback(text):
    ip = _addr(text)
    return bool(ip and ip.is_loopback)


def peer_allowed(peer, allow=()):
    ip = _addr(peer)
    if ip is None:
        return False
    if is_loopback(peer):
        return True
    wanted = {a for a in map(_addr, allow) if a}
    wanted |= {a for a in map(_addr, default_gateways()) if a}
    return ip in wanted
