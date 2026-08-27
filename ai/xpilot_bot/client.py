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
from .reliable import ReliableStream
from .frames import Frame, decode_frame, iter_reliable
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
    truncated_frames: int = 0
    #: How often the key state had to be sent again because the server had
    #: not acknowledged it. A few is normal; a lot means packet loss.
    key_resends: int = 0
    #: Seconds between joining and the ship first reacting to a control.
    ready_after: float | None = None
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
        view_width: int = 1024,
        view_height: int = 768,
        fps: int = 50,
        team: int = 0xFFFF,
        timeout: float = 3.0,
        power: float = 55.0,
        turn_speed: float = 16.0,
        turn_resistance: float = 0.0,
    ) -> None:
        self.host = host
        self.port = port
        self.nick = nick[: p.MAX_CHARS - 1]
        self.user = user[: p.MAX_CHARS - 1]
        self.team = team
        self.timeout = timeout
        # How much of the world the server should send us.
        self.view_width = view_width
        self.view_height = view_height
        self.fps = fps
        # Ship handling. See send_ship_controls -- the turn speed in
        # particular is load-bearing: leave it unsent and the ship is welded
        # to one heading.
        self.power = power
        self.turn_speed = turn_speed
        self.turn_resistance = turn_resistance
        #: Minimum frames between key-state retransmissions. See poll().
        self.key_resend_frames = 25
        self._last_key_resend_frame = 0

        self.status = Status()
        self._contact: socket.socket | None = None
        self._game: socket.socket | None = None
        self._keys = bytearray(p.KEYBOARD_SIZE)
        self._key_change = 0
        # Reliable-stream bookkeeping. The server resends unacknowledged data
        # and will eventually drop a client that never acknowledges, so this
        # is not optional even for a bot that ignores the content.
        self._reliable_offset = 0
        #: Decoded scores, players and messages from that stream. It handles
        #: the map blob at the head of the stream itself, so segments can be
        #: fed to it from the first datagram onwards.
        self.reliable = ReliableStream()
        self._last_loops = 0
        #: The most recently decoded frame, and the bytes it came from.
        self.frame: Frame | None = None
        self.last_raw: bytes | None = None

    # ---------------------------------------------------------------- join

    def connect(self, wait_ready: bool = True) -> None:
        """Run the whole handshake, leaving the bot in the game."""
        self._contact_server()
        self._enter_game()
        self._open_game_socket()
        self._verify()
        self._start_play()
        self.request_fps(self.fps)
        # Once playing, tell the server how much of the world to send. It is
        # in the server's playing-state table; sending it any earlier, during
        # setup or login, is a disconnect.
        self._send_display()
        # Without this the ship cannot turn. See send_ship_controls.
        self.send_ship_controls()
        self.status.connected = True
        if wait_ready:
            # A freshly-joined ship ignores the controls for about five
            # seconds. Returning from connect() before then hands back a
            # client that looks connected and quietly does nothing.
            self.wait_until_responsive()

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

    def send_ship_controls(self) -> None:
        """Tell the server how the ship handles.

        This is not optional and it is not tuning. `MIN_PLAYER_TURNSPEED` is
        0.0, and a player starts at the minimum (`Player_init` in
        src/server/player.c), so a client that never sends PKT_TURNSPEED has
        a ship that **cannot turn at all**. Nothing reports this: the keys
        are accepted, the frames keep coming, and the heading simply never
        changes. Measured before this existed, a bot holding turn-right for
        five seconds stayed at heading 32 the whole time.

        The consequence for a learning agent is worse than a stuck ship. It
        was being rewarded for pointing at its nearest opponent while having
        no action available that could change where it pointed, so the aim
        term was pure noise -- and the benchmark's aim column with it.

        Engine power has the same shape: the default here is what the real
        client sends (`power` 55.0, `turnSpeed` 16.0, `turnResistance` 0.0
        in src/client/default.c). The `_s` variants are what the ship does
        while the shift-modifier is held; the client sends both.
        """
        assert self._game is not None
        for pkt, value in (
            (p.PKT_POWER, self.power),
            (p.PKT_POWER_S, self.power),
            (p.PKT_TURNSPEED, self.turn_speed),
            (p.PKT_TURNSPEED_S, self.turn_speed),
            (p.PKT_TURNRESISTANCE, self.turn_resistance),
            (p.PKT_TURNRESISTANCE_S, self.turn_resistance),
        ):
            # The wire format is a short of value * 256.
            self._game.send(
                Writer().c(pkt).hd(int(value * 256.0)).bytes())

    def wait_until_responsive(self, timeout: float = 8.0) -> bool:
        """Block until the ship actually reacts to the controls.

        A freshly-joined ship ignores input for several seconds. Measured:
        pressing turn-right about a second after joining does nothing at all,
        while the identical press ten seconds in works. Nothing announces the
        transition -- the keyboard packet is accepted and acknowledged
        throughout, the heading simply does not move.

        This matters most for short episodes. At 255 fps with ten frames to a
        step, a 130-step episode is about five seconds, so an agent that
        starts the moment it joins can spend most of its first episode
        issuing commands into a void and learning from the result.

        Re-sending the same key state does not help, because the server skips
        any update whose change counter it has already seen
        (`Receive_keyboard`). Only a real transition produces key events, so
        this toggles a turn key rather than repeating it.

        Returns True once the ship moves, False if it never did.
        """
        assert self._game is not None
        deadline = time.time() + timeout
        turning = False

        while time.time() < deadline:
            # Toggle, so the server sees an actual press event.
            if turning:
                self.release(p.KEY_TURN_LEFT)
            else:
                self.press(p.KEY_TURN_LEFT)
            turning = not turning
            self.send_keys()

            seen = set()
            until = time.time() + 0.5
            while time.time() < until:
                frame = self.poll()
                if frame is not None and frame.self_ is not None:
                    seen.add(frame.self_.heading)
                if len(seen) > 1:
                    self.release_all()
                    self.send_keys()
                    self.status.ready_after = time.time() - (deadline - timeout)
                    return True

        self.release_all()
        self.send_keys()
        return False

    def request_fps(self, fps: int) -> None:
        """Ask the server for a frame rate.

        Without this the server sends at its own default regardless of how
        fast it is actually running, so raising -framesPerSecond alone does
        not speed a bot up. Raising both is what makes faster-than-realtime
        training possible.

        The value is one byte, so 255 is the ceiling.
        """
        assert self._game is not None
        self.fps = max(1, min(255, int(fps)))
        self._game.send(Writer().c(p.PKT_ASYNC_FPS).c(self.fps).bytes())

    def _send_display(self) -> None:
        """Tell the server how much of the world we want to see.

        This is not cosmetic. The server culls objects to the client's
        declared view, so a client that never sends PKT_DISPLAY is shown
        nothing but its own ship -- which looks exactly like an empty map and
        is a thoroughly confusing way to discover the packet exists.
        """
        assert self._game is not None
        self._game.send(
            Writer()
            .c(p.PKT_DISPLAY)
            .hd(self.view_width)
            .hd(self.view_height)
            .c(0)      # sparks: a bot does not need them
            .c(0)      # spark colours
            .bytes()
        )

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
        """Acknowledge and decode every reliable segment in a datagram.

        Not just one, and not only at offset zero. Before frames start, a
        segment arrives as a datagram of its own; once play begins the server
        piggybacks it onto the end of a frame update instead, so the datagram
        starts with PKT_START and the segment is somewhere inside it. Reading
        only `data[0]` therefore works perfectly through setup and then stops
        working the instant the game starts -- the stream appears to freeze,
        nothing is ever acknowledged, and the server eventually drops the
        connection with a retransmit timeout. That is a slow and confusing
        way to discover the packet is not where you assumed.
        """
        if not data:
            return

        acked = False
        for rel, rel_loops, payload in iter_reliable(data):
            self._last_loops = rel_loops
            self.reliable.feed(rel, payload)
            # Only advance on the segment we are actually waiting for;
            # anything else is a retransmission or arrived out of order.
            if rel == self._reliable_offset:
                self._reliable_offset += len(payload)
            acked = True

        if not acked:
            return

        try:
            self._game.send(
                Writer()
                .c(p.PKT_ACK)
                .ld(self._reliable_offset)
                .ld(self._last_loops)
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

    def poll(self) -> Frame | None:
        """Read and decode one frame from the server, if one is waiting.

        Returns a decoded Frame, or None if nothing arrived. Also
        acknowledges the reliable stream, so this must be called regularly
        even by a bot that ignores the contents.

        The raw bytes remain available as `last_raw` for anything this
        decoder does not yet cover.
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
        self.last_raw = data

        frame = decode_frame(data)

        # No key-state retransmission here. Resending on every frame is a
        # feedback loop -- a lagging acknowledgement causes resends, which
        # queue, which widen the lag -- and it is unnecessary anyway: the
        # environment sends the whole key state every step, so a lost
        # datagram costs one step, and wait_until_responsive toggles keys
        # explicitly while waiting for the ship to wake up.
        #
        # Removing it did NOT fix the reconnect storm that appears with many
        # environments on one machine, which is a separate and still-open
        # problem. See the note in env.reset(). Four environments run clean;
        # sixteen do not.

        return frame

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
