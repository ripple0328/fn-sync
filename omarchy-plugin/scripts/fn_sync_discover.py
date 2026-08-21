#!/usr/bin/env python3
"""Find likely fnOS hosts on directly connected private IPv4 networks.

The official fnOS clients advertise LAN discovery, but fnOS does not document
the discovery wire protocol.  This helper therefore performs a deliberately
bounded, read-only scan of the official management and WebDAV ports.  It never
authenticates, changes NAS settings, or scans arbitrary ports.
"""

from __future__ import annotations

import concurrent.futures
import http.client
import ipaddress
import json
import re
import socket
import ssl
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass

CONNECT_TIMEOUT = 0.28
HTTP_TIMEOUT = 0.9
MAX_HOSTS_PER_NETWORK = 254
MAX_WORKERS = 128

MANAGEMENT_PORTS = (
    (5667, "https"),
    (5666, "http"),
    (8001, "https"),
    (8000, "http"),
)
WEBDAV_PORTS = (
    (5006, "https"),
    (5005, "http"),
)
SCAN_PORTS = tuple(port for port, _scheme in MANAGEMENT_PORTS + WEBDAV_PORTS)

FNOS_MARKERS = (
    b"fnos",
    b"fn nas",
    "飞牛".encode(),
    b"fn-connect",
    b"trim-nas",
)


@dataclass(frozen=True)
class ProbeResult:
    status: int = 0
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes = b""

    def header(self, name: str) -> str:
        wanted = name.lower()
        return ", ".join(value for key, value in self.headers if key.lower() == wanted)


def _run_ip_json(args: list[str]) -> list[dict]:
    try:
        completed = subprocess.run(
            ["ip", "-j", *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        payload = json.loads(completed.stdout or "[]")
        return payload if isinstance(payload, list) else []
    except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError):
        return []


def local_private_networks() -> list[ipaddress.IPv4Network]:
    """Return bounded directly connected private IPv4 networks."""
    networks: list[ipaddress.IPv4Network] = []
    seen: set[str] = set()
    routes = _run_ip_json(["-4", "route", "show", "scope", "link"])
    for route in routes:
        destination = str(route.get("dst") or "")
        source = str(route.get("prefsrc") or route.get("src") or "")
        if destination in ("", "default"):
            continue
        try:
            network = ipaddress.ip_network(destination, strict=False)
        except ValueError:
            continue
        if not isinstance(network, ipaddress.IPv4Network) or not network.is_private or network.is_loopback:
            continue

        # A large corporate/private route is not permission to sweep it.  Scan
        # only the source address's /24 when the connected prefix is broader.
        if network.num_addresses - 2 > MAX_HOSTS_PER_NETWORK:
            try:
                address = ipaddress.ip_address(source)
            except ValueError:
                continue
            network = ipaddress.ip_network(f"{address}/24", strict=False)
        key = str(network)
        if key not in seen:
            seen.add(key)
            networks.append(network)
    return networks


def _tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT):
            return True
    except OSError:
        return False


def _request(host: str, port: int, scheme: str, method: str) -> ProbeResult:
    headers = {
        "Accept": "text/html,application/json,*/*",
        "Connection": "close",
        "User-Agent": "fn-sync-lan-discovery/0.6",
    }
    connection: http.client.HTTPConnection
    if scheme == "https":
        context = ssl._create_unverified_context()
        connection = http.client.HTTPSConnection(host, port, timeout=HTTP_TIMEOUT, context=context)
    else:
        connection = http.client.HTTPConnection(host, port, timeout=HTTP_TIMEOUT)
    try:
        connection.request(method, "/", headers=headers)
        response = connection.getresponse()
        body = response.read(65536) if method != "OPTIONS" else response.read(4096)
        return ProbeResult(response.status, tuple(response.getheaders()), body)
    except (OSError, http.client.HTTPException, ssl.SSLError):
        return ProbeResult()
    finally:
        try:
            connection.close()
        except OSError:
            pass


def _looks_like_fnos(result: ProbeResult) -> bool:
    material = result.body.lower()
    material += result.header("server").lower().encode(errors="ignore")
    material += result.header("set-cookie").lower().encode(errors="ignore")
    return any(marker in material for marker in FNOS_MARKERS)


def _looks_like_webdav(result: ProbeResult) -> bool:
    dav = result.header("dav").strip()
    allow = result.header("allow").upper()
    return bool(dav) or "PROPFIND" in allow


def _page_title(body: bytes) -> str:
    match = re.search(br"<title[^>]*>(.*?)</title>", body, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    title = re.sub(br"\s+", b" ", match.group(1)).decode("utf-8", errors="replace").strip()
    if not title or len(title) > 80:
        return ""
    return title


def _url(host: str, port: int, scheme: str) -> str:
    return f"{scheme}://{host}:{port}/"


def inspect_host(host: str, open_ports: set[int]) -> dict | None:
    management: tuple[int, str] | None = next(
        ((port, scheme) for port, scheme in MANAGEMENT_PORTS if port in open_ports),
        None,
    )
    webdav: tuple[int, str] | None = next(
        ((port, scheme) for port, scheme in WEBDAV_PORTS if port in open_ports),
        None,
    )

    management_result = ProbeResult()
    management_fingerprint = False
    if management:
        management_result = _request(host, management[0], management[1], "GET")
        management_fingerprint = _looks_like_fnos(management_result)

    webdav_result = ProbeResult()
    webdav_fingerprint = False
    if webdav:
        webdav_result = _request(host, webdav[0], webdav[1], "OPTIONS")
        webdav_fingerprint = _looks_like_webdav(webdav_result)

    # Official management ports are sufficiently specific to report as a
    # possible fnOS device; WebDAV-only hosts require an actual DAV response.
    if management is None and not webdav_fingerprint:
        return None

    if webdav:
        webdav_port, webdav_scheme = webdav
        webdav_url = _url(host, webdav_port, webdav_scheme)
    else:
        webdav_port, webdav_scheme = 5006, "https"
        webdav_url = ""

    title = _page_title(management_result.body)
    name = title if management_fingerprint and title else f"fnOS NAS {host}"
    management_url = _url(host, management[0], management[1]) if management else ""
    confidence = "verified" if management_fingerprint or webdav_fingerprint else "possible"
    return {
        "name": name,
        "address": host,
        "url": webdav_url,
        "suggested_url": _url(host, webdav_port, webdav_scheme),
        "allow_http": bool(webdav_url) and webdav_scheme == "http",
        "insecure_skip_verify": bool(webdav_url) and webdav_scheme == "https",
        "webdav_verified": webdav_fingerprint,
        "webdav_port_open": webdav is not None,
        "management_url": management_url,
        "confidence": confidence,
    }


def _addresses(networks: Iterable[ipaddress.IPv4Network]) -> list[str]:
    return [str(address) for network in networks for address in network.hosts()]


def discover() -> dict:
    networks = local_private_networks()
    addresses = _addresses(networks)
    open_by_host: dict[str, set[int]] = {}
    checks = [(host, port) for host in addresses for port in SCAN_PORTS]
    if checks:
        workers = min(MAX_WORKERS, len(checks))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_target = {
                executor.submit(_tcp_open, host, port): (host, port) for host, port in checks
            }
            for future in concurrent.futures.as_completed(future_to_target):
                host, port = future_to_target[future]
                try:
                    opened = future.result()
                except Exception:
                    opened = False
                if opened:
                    open_by_host.setdefault(host, set()).add(port)

    devices = []
    for host in sorted(open_by_host, key=ipaddress.ip_address):
        device = inspect_host(host, open_by_host[host])
        if device:
            devices.append(device)
    return {
        "networks": [str(network) for network in networks],
        "devices": devices,
        "ports": list(SCAN_PORTS),
    }


def main() -> int:
    try:
        print(json.dumps(discover(), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"networks": [], "devices": [], "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
