#!/usr/bin/env python3
"""A self-hostable XPilot NG metaserver.

The original metaservers (meta.xpilot.org, meta2.xpilot.org) are dead, which
is why the client's server browser is empty. This is a drop-in replacement
that speaks the same protocol, so unmodified clients and servers can use it.

It is deliberately compatible rather than modern. The roadmap suggested "a
tiny HTTP JSON service", but an HTTP service cannot be talked to by an
unmodified client, and protocol compatibility is the point of this fork. So
the wire protocol is the original one, and the JSON is offered alongside it
for humans and dashboards.

Three listeners:

  UDP 5500   servers announce themselves here ("add server ...", "... remove")
  TCP 4401   clients connect and are sent the server list, then disconnected
  TCP 4402   optional; GET returns the same list as JSON  (--http-port 0 to disable)

No dependencies. Python 3.9+.

This program is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation; either version 2 of the License, or (at your option) any later
version.  See the COPYING file for details.
"""

from __future__ import annotations

import argparse
import json
import logging
import selectors
import socket
import sys
import time
from dataclasses import dataclass, field

LOG = logging.getLogger("metaserver")

DEFAULT_UDP_PORT = 5500      # META_PORT: servers announce here
DEFAULT_TCP_PORT = 4401      # META_PROG_PORT: clients ask here
DEFAULT_HTTP_PORT = 4402     # not part of the original protocol

# A server re-announces roughly every 180s (GIVE_META_SERVER_A_HINT in
# src/server/metaserver.c), so anything unheard-from for well over that is
# gone rather than merely quiet.
DEFAULT_TTL = 600.0

# The client splits each line on ':' and requires exactly this many fields,
# discarding the line otherwise (NUM_META_DATA_FIELDS in src/client/meta.h).
NUM_FIELDS = 18

# Field order, from Parse_meta_line in src/client/meta.c. The names are the
# keys the server announces; where they differ the mapping is noted.
FIELD_ORDER = [
    "version",      # 0
    "server",       # 1  hostname
    "port",         # 2  numeric
    "users",        # 3  numeric
    "map",          # 4
    "sizeMap",      # 5
    "author",       # 6
    "status",       # 7  the server calls this "mode"
    "bases",        # 8  numeric
    "fps",          # 9  numeric
    "players",      # 10 playlist
    "sound",        # 11
    "stime",        # 12 uptime, numeric
    "teams",        # 13 teambases, numeric
    "timing",       # 14
    "ip",           # 15 dotted quad; filled in from the sender's address
    "free",         # 16 freebases
    "queue",        # 17 numeric
]

# Numeric fields the client parses with sscanf("%u"). A non-numeric value here
# makes the client reject the whole line, so they get a safe default.
NUMERIC = {"port", "users", "bases", "fps", "stime", "teams", "queue"}


@dataclass
class Server:
    """One announced game server."""

    ip: str
    attrs: dict = field(default_factory=dict)
    last_seen: float = field(default_factory=time.time)

    def key(self) -> tuple:
        """Servers are identified by host and port, not host alone.

        Several servers on one machine is normal, so keying on hostname would
        make them overwrite each other.
        """
        return (self.attrs.get("server", self.ip), self.attrs.get("port", "0"))

    def to_line(self) -> str:
        """Render as the colon-separated line the client expects."""
        out = []
        for name in FIELD_ORDER:
            if name == "ip":
                value = self.ip
            else:
                value = self.attrs.get(name, "")
            value = value.replace(":", " ").replace("\n", " ")
            if name in NUMERIC and not value.isdigit():
                value = "0"
            out.append(value)
        return ":".join(out)

    def to_dict(self) -> dict:
        d = dict(self.attrs)
        d["ip"] = self.ip
        d["age"] = round(time.time() - self.last_seen, 1)
        return d


class MetaServer:
    def __init__(self, ttl: float = DEFAULT_TTL) -> None:
        self.servers: dict[tuple, Server] = {}
        self.ttl = ttl

    # ------------------------------------------------------------ announces

    def handle_announce(self, data: bytes, addr: tuple) -> None:
        """Process one UDP announcement.

        Two shapes, both from src/server/metaserver.c:

            add server <host>\\nadd users <n>\\n...     a full status report
            server <host>\\nremove                      a clean shutdown
        """
        ip = addr[0]
        try:
            text = data.decode("latin-1")
        except Exception:
            return

        text = text.rstrip("\0")
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if not lines:
            return

        if any(ln == "remove" for ln in lines):
            self._handle_remove(lines, ip)
            return

        attrs: dict[str, str] = {}
        for ln in lines:
            if not ln.startswith("add "):
                continue
            rest = ln[4:]
            key, _, value = rest.partition(" ")
            if key:
                attrs[key] = value

        if "server" not in attrs:
            # Without a hostname there is nothing to key on.
            return

        # The server announces its game port as "port"; keep the announced
        # value but fall back to the well-known one if it is missing.
        attrs.setdefault("port", "15345")
        # The client's field 7 is the game status, which the server calls mode.
        if "status" not in attrs and "mode" in attrs:
            attrs["status"] = attrs["mode"]

        srv = Server(ip=ip, attrs=attrs)
        key = srv.key()
        existed = key in self.servers
        self.servers[key] = srv
        LOG.info(
            "%s %s:%s (%s users, map %r) from %s",
            "update" if existed else "ADD   ",
            attrs.get("server"),
            attrs.get("port"),
            attrs.get("users", "?"),
            attrs.get("map", "?"),
            ip,
        )

    def _handle_remove(self, lines: list[str], ip: str) -> None:
        host = None
        for ln in lines:
            if ln.startswith("server "):
                host = ln[7:].strip()
                break
        if host is None:
            return
        gone = [k for k in self.servers if k[0] == host]
        for k in gone:
            del self.servers[k]
            LOG.info("REMOVE %s:%s (announced shutdown from %s)", k[0], k[1], ip)

    # -------------------------------------------------------------- listing

    def expire(self) -> None:
        now = time.time()
        dead = [k for k, s in self.servers.items() if now - s.last_seen > self.ttl]
        for k in dead:
            del self.servers[k]
            LOG.info("EXPIRE %s:%s (silent for over %.0fs)", k[0], k[1], self.ttl)

    def active(self) -> list[Server]:
        self.expire()
        return sorted(
            self.servers.values(),
            key=lambda s: (s.attrs.get("server", ""), s.attrs.get("port", "")),
        )

    def list_text(self) -> bytes:
        """The payload sent to a connecting client."""
        lines = [s.to_line() for s in self.active()]
        return ("\n".join(lines) + "\n").encode("latin-1", "replace")

    def list_json(self) -> bytes:
        return json.dumps(
            {"servers": [s.to_dict() for s in self.active()]}, indent=2
        ).encode("utf-8")


def http_response(body: bytes, content_type: str = "application/json") -> bytes:
    head = (
        "HTTP/1.1 200 OK\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "\r\n"
    )
    return head.encode("ascii") + body


def serve(
    udp_port: int,
    tcp_port: int,
    http_port: int,
    bind: str,
    ttl: float,
) -> int:
    meta = MetaServer(ttl=ttl)
    sel = selectors.DefaultSelector()

    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp.bind((bind, udp_port))
    sel.register(udp, selectors.EVENT_READ, "udp")

    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp.bind((bind, tcp_port))
    tcp.listen(16)
    sel.register(tcp, selectors.EVENT_READ, "tcp")

    http = None
    if http_port:
        http = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        http.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        http.bind((bind, http_port))
        http.listen(16)
        sel.register(http, selectors.EVENT_READ, "http")

    LOG.info("announcements on udp/%d", udp_port)
    LOG.info("client list on tcp/%d", tcp_port)
    if http:
        LOG.info("json on http://%s:%d/", bind or "0.0.0.0", http_port)

    try:
        while True:
            # Wake periodically even when idle, so expiry happens on time.
            for key, _ in sel.select(timeout=30.0):
                kind = key.data
                if kind == "udp":
                    data, addr = key.fileobj.recvfrom(65535)
                    meta.handle_announce(data, addr)
                elif kind == "tcp":
                    conn, addr = key.fileobj.accept()
                    try:
                        conn.settimeout(5.0)
                        conn.sendall(meta.list_text())
                    except OSError as exc:
                        LOG.debug("client %s: %s", addr[0], exc)
                    finally:
                        conn.close()
                elif kind == "http":
                    conn, addr = key.fileobj.accept()
                    try:
                        conn.settimeout(5.0)
                        conn.recv(4096)          # request line; ignored
                        conn.sendall(http_response(meta.list_json()))
                    except OSError as exc:
                        LOG.debug("http client %s: %s", addr[0], exc)
                    finally:
                        conn.close()
            meta.expire()
    except KeyboardInterrupt:
        LOG.info("shutting down")
        return 0
    finally:
        sel.close()
        udp.close()
        tcp.close()
        if http:
            http.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bind", default="", help="address to bind (default: all)")
    ap.add_argument("--udp-port", type=int, default=DEFAULT_UDP_PORT,
                    help=f"server announcements (default {DEFAULT_UDP_PORT})")
    ap.add_argument("--tcp-port", type=int, default=DEFAULT_TCP_PORT,
                    help=f"client queries (default {DEFAULT_TCP_PORT})")
    ap.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT,
                    help="JSON endpoint; 0 disables it")
    ap.add_argument("--ttl", type=float, default=DEFAULT_TTL,
                    help=f"drop servers unheard-from for this long "
                         f"(default {DEFAULT_TTL:.0f}s)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )
    return serve(args.udp_port, args.tcp_port, args.http_port, args.bind, args.ttl)


if __name__ == "__main__":
    sys.exit(main())
