"""
Local HTTP CONNECT proxy that chains through an upstream SOCKS5 proxy.

Chromium/Playwright cannot do SOCKS5 authentication natively.
This module runs a lightweight local HTTP proxy that accepts CONNECT
requests and forwards them through the upstream SOCKS5 proxy (e.g. PIA)
using a raw-socket SOCKS5 handshake for authentication.

Usage from the app:
    from roombooker.proxy_forwarder import start_forwarder, stop_forwarder
    local_port = start_forwarder(socks_host, socks_port, socks_user, socks_pass)
    # Playwright uses http://127.0.0.1:{local_port} as proxy
    stop_forwarder()
"""

import logging
import select
import socket
import struct
import threading

log = logging.getLogger(__name__)

_server_socket: socket.socket | None = None
_thread: threading.Thread | None = None
_stop_event = threading.Event()

BUFFER = 65536


def _socks5_connect(dst_host: str, dst_port: int,
                    proxy_host: str, proxy_port: int,
                    proxy_user: str, proxy_pass: str,
                    timeout: float = 15) -> socket.socket:
    """Open a TCP connection to dst via SOCKS5 proxy with user/pass auth."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((proxy_host, proxy_port))

    # Greeting: offer user/pass auth (method 0x02)
    sock.sendall(b"\x05\x01\x02")
    resp = sock.recv(2)
    if resp[0:1] != b"\x05" or resp[1:2] != b"\x02":
        sock.close()
        raise ConnectionError("SOCKS5 server did not accept user/pass auth")

    # Sub-negotiation: user/pass
    ulen = len(proxy_user)
    plen = len(proxy_pass)
    sock.sendall(struct.pack("!BB", 1, ulen) + proxy_user.encode()
                 + struct.pack("!B", plen) + proxy_pass.encode())
    resp = sock.recv(2)
    if resp[1:2] != b"\x00":
        sock.close()
        raise ConnectionError("SOCKS5 authentication failed")

    # Connect request – resolve DNS locally (PIA doesn't support ATYP 0x03)
    try:
        dst_ip = socket.gethostbyname(dst_host)
    except socket.gaierror as e:
        sock.close()
        raise ConnectionError(f"DNS resolution failed for {dst_host}: {e}")
    ip_bytes = socket.inet_aton(dst_ip)
    sock.sendall(b"\x05\x01\x00\x01" + ip_bytes + struct.pack("!H", dst_port))
    resp = sock.recv(10)
    if resp[1:2] != b"\x00":
        sock.close()
        raise ConnectionError(f"SOCKS5 connect failed: reply={resp[1]}")

    sock.settimeout(None)
    return sock


def _relay(a: socket.socket, b: socket.socket):
    """Bidirectional relay until one side closes."""
    try:
        while not _stop_event.is_set():
            readable, _, _ = select.select([a, b], [], [], 2.0)
            for s in readable:
                data = s.recv(BUFFER)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except (OSError, ConnectionError):
        pass
    finally:
        a.close()
        b.close()


def _handle_client(client: socket.socket,
                   proxy_host: str, proxy_port: int,
                   proxy_user: str, proxy_pass: str):
    """Handle one HTTP CONNECT request."""
    try:
        data = client.recv(BUFFER)
        if not data:
            client.close()
            return

        first_line = data.split(b"\r\n")[0].decode(errors="replace")
        parts = first_line.split()

        if len(parts) < 3:
            client.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            client.close()
            return

        method = parts[0].upper()
        target = parts[1]

        if method == "CONNECT":
            # CONNECT host:port HTTP/1.1
            host, port_str = target.rsplit(":", 1)
            port = int(port_str)
        else:
            # Plain HTTP: GET http://host:port/path HTTP/1.1
            # Extract host/port from URL
            from urllib.parse import urlparse
            parsed = urlparse(target)
            host = parsed.hostname or ""
            port = parsed.port or 80

        remote = _socks5_connect(host, port,
                                 proxy_host, proxy_port,
                                 proxy_user, proxy_pass)

        if method == "CONNECT":
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        else:
            # Forward the original request
            remote.sendall(data)

        _relay(client, remote)

    except Exception as exc:
        log.debug("Proxy client error: %s", exc)
        try:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except OSError:
            pass
        client.close()


def _serve(local_port: int,
           proxy_host: str, proxy_port: int,
           proxy_user: str, proxy_pass: str):
    global _server_socket
    _server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _server_socket.settimeout(2.0)
    _server_socket.bind(("127.0.0.1", local_port))
    _server_socket.listen(32)
    log.info("Proxy forwarder listening on 127.0.0.1:%d → socks5://%s:%d",
             local_port, proxy_host, proxy_port)

    while not _stop_event.is_set():
        try:
            client, _ = _server_socket.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        t = threading.Thread(target=_handle_client,
                             args=(client, proxy_host, proxy_port,
                                   proxy_user, proxy_pass),
                             daemon=True)
        t.start()

    _server_socket.close()
    log.info("Proxy forwarder stopped")


def start_forwarder(socks_host: str, socks_port: int,
                    socks_user: str, socks_pass: str,
                    local_port: int = 18123) -> int:
    """Start the local HTTP proxy forwarder in a background thread.
    Returns the local port."""
    global _thread
    _stop_event.clear()
    _thread = threading.Thread(target=_serve,
                               args=(local_port, socks_host, socks_port,
                                     socks_user, socks_pass),
                               daemon=True, name="proxy-forwarder")
    _thread.start()
    log.info("Proxy forwarder thread started (port %d)", local_port)
    return local_port


def stop_forwarder():
    """Stop the forwarder."""
    global _thread, _server_socket
    _stop_event.set()
    if _server_socket:
        try:
            _server_socket.close()
        except OSError:
            pass
    if _thread:
        _thread.join(timeout=5)
    _thread = None
    _server_socket = None
