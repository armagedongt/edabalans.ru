"""Windows per-connection VPN bypass; usable as an OpenSSH ProxyCommand."""
from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import os
import socket
import ssl
import struct
import subprocess
import sys
import threading
from urllib.parse import urlsplit


def physical_interface() -> tuple[int, str]:
    if os.name != "nt":
        raise RuntimeError("Direct interface selection is supported on Windows only")
    script = r"""
$ErrorActionPreference = 'Stop'
$candidates = @(Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | ForEach-Object {
    $config = Get-NetIPConfiguration -InterfaceIndex $_.ifIndex
    $route = Get-NetRoute -AddressFamily IPv4 -InterfaceIndex $_.ifIndex -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1
    if ($config.IPv4Address -and $config.IPv4DefaultGateway -and $route) {
        $ipif = Get-NetIPInterface -AddressFamily IPv4 -InterfaceIndex $_.ifIndex
        [pscustomobject]@{ index = $_.ifIndex; address = @($config.IPv4Address)[0].IPAddress; metric = [int]$ipif.InterfaceMetric + [int]$route.RouteMetric }
    }
})
$chosen = $candidates | Sort-Object metric,index | Select-Object -First 1
if (-not $chosen) { throw 'No connected physical IPv4 interface with a default gateway' }
$chosen | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", timeout=25, check=True,
    )
    selected = json.loads(result.stdout)
    index, address = int(selected["index"]), str(selected["address"])
    if index <= 0 or ipaddress.ip_address(address).version != 4:
        raise RuntimeError("Invalid physical IPv4 interface")
    return index, address


def direct_socket(host: str, port: int, *, timeout: float = 20) -> socket.socket:
    index, address = physical_interface()
    peer = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4]
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        connection.settimeout(timeout)
        # Windows IP_UNICAST_IF expects the interface index in network byte order.
        connection.setsockopt(socket.IPPROTO_IP, 31, struct.pack("!I", index))
        connection.bind((address, 0))
        connection.connect(peer)
        return connection
    except BaseException:
        connection.close()
        raise


def https_get(url: str) -> tuple[int, dict[str, str], bytes]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an HTTPS URL without embedded credentials")
    host = parsed.hostname.encode("idna").decode("ascii")
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    if any(c in path for c in "\r\n"):
        raise ValueError("Invalid request path")
    connection = direct_socket(host, port)
    try:
        with ssl.create_default_context().wrap_socket(connection, server_hostname=host) as tls:
            authority = host if port == 443 else f"{host}:{port}"
            tls.sendall(f"GET {path} HTTP/1.1\r\nHost: {authority}\r\nConnection: close\r\n\r\n".encode("ascii"))
            with http.client.HTTPResponse(tls) as response:
                response.begin()
                return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def proxy(host: str, port: int) -> None:
    with direct_socket(host, port) as connection:
        connection.settimeout(None)

        def upload() -> None:
            try:
                while chunk := os.read(sys.stdin.fileno(), 65536):
                    connection.sendall(chunk)
            except OSError:
                pass
            finally:
                try:
                    connection.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        threading.Thread(target=upload, daemon=True).start()
        while chunk := connection.recv(65536):
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", nargs="?")
    parser.add_argument("port", nargs="?", type=int, default=22)
    parser.add_argument("--https", metavar="URL", help="GET through the physical interface; raw body on stdout")
    args = parser.parse_args()
    try:
        if args.https:
            status, _, body = https_get(args.https)
            if not 200 <= status < 300:
                raise RuntimeError(f"HTTP status {status}")
            sys.stdout.buffer.write(body)
        elif args.host:
            proxy(args.host, args.port)
        else:
            parser.error("Provide a host or --https URL")
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Direct connection failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
