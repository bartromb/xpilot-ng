"""Minimal headless XPilot NG client.

Implements enough of the protocol for a bot to join a server and act: the
two-phase handshake, the verify exchange on the game socket, and the keyboard
vector that carries every action a player can take.

The handshake is documented in docs/protocol.md; the short version is that the
server does not serve the game from 15345. It replies there with a *different*
port, and everything after that happens on the second port.

What this deliberately does not do is decode the full frame stream. There are
93 packet types and most describe things a bot does not need in order to fly.
Frames are read and acknowledged so the connection stays healthy, and the
interesting ones are surfaced; the rest are skipped. See README.md.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field

from . import protocol as p
from .packet import Reader, Writer


class ProtocolError(Exception):
    pass


@dataclass
class Status:
    """What the bot knows about itself and the world.

    Deliberately small. Everything here is decoded from packets this client
    actually understands, so nothing in it is a guess.
    """

    connected: bool = False
    frame: int = 0
    login_port: int = 0
    server_version: int = 0
    keys_held: set = field(default_factory=set)


class Client:
    def __init__(
        self,
        host: str = "localhost",
        port: int = p.SERVER_PORT,
        nick: str = "bot",
        user: str = "bot",
        team: int = 0xFFFF,
        timeout: float = 3.0,
    ) -> None:
        self.host = host
        self.port = port
        self.nick = nick[: p.MAX_CHARS - 1]
        self.user = user[: p.MAX_CHARS - 1]
        self.team = team
        self.timeout = timeout

        self.status = Status()
        self._contact: socket.socket | None = None
        self._game: socket.socket | None = None
        self._keys = bytearray(p.KEYBOARD_SIZE)
        self._key_change = 0
        # Reliable-stream bookkeeping. The server resends unacknowledged data
        # and will eventually drop a client that never acknowledges, so this
        # is not optional even for a bot that ignores the content.
        self._reliable_offset = 0
        self._last_loops = 0

    # ---------------------------------------------------------------- join

    def connect(self) -> None:
        """Run the whole handshake, leaving the bot in the game."""
        self._contact_server()
        self._enter_game()
        self._open_game_socket()
        self._verify()
        self._start_play()
        self.status.connected = True

    def _contact_server(self) -> None:
        self._contact = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._contact.settimeout(self.timeout)
        self._contact.bind(("", 0))
        my_port = self._contact.getsockname()[1]

        pkt = (
            Writer()
            .u(p.version_to_magic(0x4F15))
            .s(self.user)
            .hu(my_port)
            .c(p.CONTACT_pack)
            .bytes()
        )
        self._contact.sendto(pkt, (self.host, self.port))

        data, _ = self._contact.recvfrom(4096)
        r = Reader(data)
        magic = r.u()
        if (magic & 0xFFFF) != p.MAGIC_WORD:
            raise ProtocolError(f"bad magic 0x{magic:08x} in contact reply")
        self.status.server_version = p.magic_to_version(magic)

    def _enter_game(self) -> None:
        """Ask to join, and read back the port the game is actually on."""
        assert self._contact is not None
        my_port = self._contact.getsockname()[1]

        pkt = (
            Writer()
            .u(p.version_to_magic(self.status.server_version))
            .s(self.user)
            .hu(my_port)
            .c(p.ENTER_QUEUE_pack)
            .s(self.nick)
            .s("bot")          # display name
            .s(self.host)      # host name
            .d(self.team)
            .bytes()
        )

        deadline = time.time() + 10.0
        while time.time() < deadline:
            self._contact.sendto(pkt, (self.host, self.port))
            try:
                data, _ = self._contact.recvfrom(4096)
            except socket.timeout:
                continue

            r = Reader(data)
            r.u()                    # magic
            reply_to = r.c()
            status = r.c()

            if reply_to == p.ENTER_GAME_pack and status == p.SUCCESS:
                self.status.login_port = r.hu()
                return
            if reply_to == p.ENTER_QUEUE_pack and status == p.SUCCESS:
                # Queued behind other players; keep asking.
                time.sleep(0.5)
                continue
            raise ProtocolError(
                f"join refused: reply_to=0x{reply_to:02x} status=0x{status:02x}"
            )

        raise ProtocolError("timed out waiting to be let into the game")

    def _open_game_socket(self) -> None:
        self._game = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._game.settimeout(self.timeout)
        self._game.bind(("", 0))
        # connect() so the kernel filters anything not from the server
        self._game.connect((self.host, self.status.login_port))

    def _verify(self) -> None:
        assert self._game is not None
        pkt = (
            Writer()
            .c(p.PKT_VERIFY)
            .s(self.user)
            .s(self.nick)
            .s("bot")
            .bytes()
        )

        for _ in range(5):
            self._game.send(pkt)
            try:
                data = self._game.recv(8192)
            except socket.timeout:
                continue
            if not data:
                continue
            if data[0] == p.PKT_QUIT:
                raise ProtocolError("server closed the connection during verify")
            # A reliable-stream reply means the server accepted us.
            if data[0] == p.PKT_RELIABLE:
                return
        raise ProtocolError("no verify response from server")

    def _drain_setup(self, quiet_for: float = 0.4, limit: float = 15.0) -> int:
        """Receive and acknowledge setup data until the server goes quiet.

        After verifying, the connection sits in CONN_SETUP while the server
        pushes the map down the reliable stream. It only advances to
        CONN_LOGIN once the client has acknowledged all of it. Sending
        anything else in the meantime -- a keyboard packet, say -- is treated
        as an "undefined packet" and the connection is destroyed, which is a
        confusing way to discover you skipped a step.

        Returns the number of datagrams consumed.
        """
        assert self._game is not None
        got = 0
        deadline = time.time() + limit
        last_data = time.time()

        while time.time() < deadline:
            try:
                data = self._game.recv(8192)
            except socket.timeout:
                if time.time() - last_data > quiet_for:
                    break
                continue
            except ConnectionRefusedError:
                raise ProtocolError("server dropped the connection during setup")

            if not data:
                continue
            if data[0] == p.PKT_QUIT:
                raise ProtocolError("server closed the connection during setup")

            got += 1
            last_data = time.time()
            self._handle_datagram(data)

        return got

    def _start_play(self) -> None:
        """Ask to be put into play, once setup has been drained.

        Readiness is detected passively, by waiting for the server to start
        sending frames (PKT_START). Probing by sending a keyboard packet does
        not work: while the connection is still in setup that packet is
        exactly what the server rejects, so the probe destroys the thing it
        is trying to measure.
        """
        assert self._game is not None
        self._game.settimeout(0.1)
        self._drain_setup()

        pkt = Writer().c(p.PKT_PLAY).bytes()
        deadline = time.time() + 15.0

        while time.time() < deadline:
            self._game.send(pkt)

            inner = time.time() + 1.0
            while time.time() < inner:
                try:
                    data = self._game.recv(8192)
                except socket.timeout:
                    continue
                except ConnectionRefusedError:
                    raise ProtocolError("server dropped us while starting play")

                if not data:
                    continue
                if data[0] == p.PKT_QUIT:
                    raise ProtocolError("server closed the connection")

                self._handle_datagram(data)

                # Frames mean we are in the game.
                if data[0] in (p.PKT_START, p.PKT_SELF):
                    self._game.settimeout(self.timeout)
                    return

        self._game.settimeout(self.timeout)
        raise ProtocolError("server never started sending frames")

    def _handle_datagram(self, data: bytes) -> None:
        """Acknowledge the reliable stream. Frame content is not decoded."""
        if not data or data[0] != p.PKT_RELIABLE:
            return
        try:
            r = Reader(data)
            r.c()                       # PKT_RELIABLE
            length = r.hd()
            rel = r.ld()
            rel_loops = r.ld()
        except Reader.Truncated:
            return

        self._last_loops = rel_loops

        # Only advance on the segment we are actually waiting for; anything
        # else is a retransmission or arrived out of order.
        if rel == self._reliable_offset:
            self._reliable_offset += length

        try:
            self._game.send(
                Writer()
                .c(p.PKT_ACK)
                .ld(self._reliable_offset)
                .ld(rel_loops)
                .bytes()
            )
        except OSError:
            pass

    # -------------------------------------------------------------- acting

    def press(self, key: int) -> None:
        """Hold a key down. Actions persist until released."""
        if self._keys[key // 8] & (1 << (key % 8)):
            return
        self._keys[key // 8] |= 1 << (key % 8)
        self._key_change += 1
        self.status.keys_held.add(key)

    def release(self, key: int) -> None:
        if not self._keys[key // 8] & (1 << (key % 8)):
            return
        self._keys[key // 8] &= ~(1 << (key % 8))
        self._key_change += 1
        self.status.keys_held.discard(key)

    def release_all(self) -> None:
        for k in list(self.status.keys_held):
            self.release(k)

    def send_keys(self) -> None:
        """Push the current key state to the server."""
        assert self._game is not None
        pkt = (
            Writer()
            .c(p.PKT_KEYBOARD)
            .ld(self._key_change)
            .raw(bytes(self._keys))
            .bytes()
        )
        self._game.send(pkt)

    # --------------------------------------------------------------- frames

    def poll(self) -> bytes | None:
        """Read one datagram from the server, if one is waiting.

        The frame stream is not decoded; see the module docstring. Returning
        the raw bytes lets a caller experiment without this library pretending
        to understand more than it does.
        """
        assert self._game is not None
        try:
            data = self._game.recv(8192)
        except socket.timeout:
            return None
        except ConnectionRefusedError:
            # ICMP port unreachable: the server has dropped us.
            self.status.connected = False
            raise ProtocolError("server closed the connection")
        self.status.frame += 1
        self._handle_datagram(data)
        return data

    def close(self) -> None:
        try:
            if self._game is not None:
                self._game.send(Writer().c(p.PKT_QUIT).bytes())
        except OSError:
            pass
        for s in (self._game, self._contact):
            if s is not None:
                s.close()
        self._game = self._contact = None
        self.status.connected = False

    def __enter__(self) -> "Client":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
