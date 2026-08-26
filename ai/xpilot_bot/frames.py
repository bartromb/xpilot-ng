"""Frame decoding: turning the server's packet stream into world state.

Every datagram the server sends during play is one frame, beginning with
PKT_START and ending with PKT_END, with a run of packets in between.

The awkward part is that packets are concatenated with no length prefix and no
delimiter, so reading packet N+1 requires knowing the exact size of packet N.
An unrecognised type is therefore not something that can be skipped: it
desynchronises everything after it. That is why this module carries a size for
every type it may encounter, and why `Frame.truncated` exists to say when it
gave up rather than quietly returning half a world.

Sizes come from the Packet_scanf format strings in src/client/netclient.c. A
mistake in any one of them silently corrupts everything downstream, which is
easy to miss because the result still looks like plausible packets -- an
off-by-one on PKT_BALL showed up as a frame containing two PKT_SELF packets,
which cannot happen.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import protocol as p

# PKT_DEBRIS is a base: the type byte encodes the colour, so it occupies a
# whole range (DEBRIS_TYPES in src/common/const.h).
DEBRIS_TYPES = 8 * 4 * 4


def _fmtlen(fmt: str) -> int:
    """Byte length of a fixed-width Packet_printf format string."""
    n, i = 0, 0
    while i < len(fmt):
        assert fmt[i] == "%"
        i += 1
        if fmt[i] == "h":
            n, i = n + 2, i + 2
        elif fmt[i] == "l":
            n, i = n + 4, i + 2
        elif fmt[i] == "c":
            n, i = n + 1, i + 1
        elif fmt[i] in "du":
            n, i = n + 4, i + 1
        else:
            raise ValueError(f"unhandled conversion %{fmt[i]}")
    return n


# Fixed-size packets, with the format they come from so the number can be
# checked against the C rather than trusted.
FIXED_SIZES = {
    p.PKT_START:     _fmtlen("%c%ld%ld"),
    p.PKT_END:       _fmtlen("%c%ld"),
    p.PKT_SELF:      _fmtlen("%c%hd%hd%hd%hd%c%c%c%c%hd%hd%c%c")
                     + _fmtlen("%c%hd%hd%hd%hd%c%c%c"),
    p.PKT_SHIP:      _fmtlen("%c%hd%hd%hd%c%c"),
    p.PKT_MINE:      _fmtlen("%c%hd%hd%c%hd"),
    p.PKT_CONNECTOR: _fmtlen("%c%hd%hd%hd%hd%c"),
    p.PKT_BALL:      _fmtlen("%c%hd%hd%hd%c"),
    p.PKT_DAMAGED:   _fmtlen("%c%c"),
    p.PKT_ITEM:      _fmtlen("%c%hd%hd%c"),
    p.PKT_CANNON:    _fmtlen("%c%hu%hu%c%ld%hu"),
    p.PKT_FUEL:      _fmtlen("%c%hu%hu%c%ld%hu"),
    p.PKT_TARGET:    _fmtlen("%c%hu%hu%hu%c%ld%hu"),
    p.PKT_APPEARING: _fmtlen("%c%hd%hd%hd%hd"),
    p.PKT_WRECKAGE:  _fmtlen("%c%hd%hd%c%c%c"),
    p.PKT_ECM:       _fmtlen("%c%hd%hd%hd"),
    p.PKT_REFUEL:    _fmtlen("%c%hd%hd%hd%hd"),
    p.PKT_LASER:     _fmtlen("%c%c%hd%hd%hd%c"),
    p.PKT_MISSILE:   _fmtlen("%c%hd%hd%c%c"),
    p.PKT_PAUSED:    _fmtlen("%c%hd%hd%hd"),
    p.PKT_RADAR:     _fmtlen("%c%hd%hd%c"),
}


@dataclass
class Self:
    """Own ship. Everything a bot needs to fly is here."""

    x: int = 0
    y: int = 0
    vx: int = 0
    vy: int = 0
    heading: int = 0          # 0..127, not degrees
    power: int = 0
    turnspeed: int = 0
    turnresistance: int = 0
    lock_id: int = 0
    lock_dist: int = 0
    lock_dir: int = 0
    next_checkpoint: int = 0
    current_tank: int = 0
    fuel: int = 0
    fuel_max: int = 0
    view_width: int = 0
    view_height: int = 0
    status: int = 0
    autopilot: int = 0


@dataclass
class Ship:
    """Another player's ship, in world coordinates."""

    x: int
    y: int
    id: int
    heading: int
    shield: bool = False
    cloak: bool = False
    eshield: bool = False
    phased: bool = False
    deflector: bool = False


@dataclass
class Shot:
    x: int
    y: int
    kind: int          # colour/type byte the server used


@dataclass
class Item:
    x: int
    y: int
    kind: int


@dataclass
class Frame:
    """One decoded frame."""

    loops: int = 0
    key_ack: int = 0
    self_: Self | None = None
    ships: list = field(default_factory=list)
    shots: list = field(default_factory=list)
    items: list = field(default_factory=list)
    balls: list = field(default_factory=list)
    mines: list = field(default_factory=list)
    damaged: bool = False

    #: Set when decoding stopped early. The fields above are then partial,
    #: which matters: an empty `ships` on a truncated frame means "unknown",
    #: not "no ships".
    truncated: bool = False
    #: The packet type that stopped it, for diagnosing a gap.
    truncated_at: int | None = None


def packet_length(buf: bytes, i: int) -> int | None:
    """Size in bytes of the packet at offset i, or None if unrecognised."""
    t = buf[i]

    if p.PKT_DEBRIS <= t < p.PKT_DEBRIS + DEBRIS_TYPES:
        # type, count, then count coordinate pairs
        return 2 + 2 * buf[i + 1]
    if t == p.PKT_FASTSHOT:
        # id, type, count, then count coordinate pairs
        return 3 + 2 * buf[i + 2]
    if t == p.PKT_FASTRADAR:
        # count, then count 3-byte entries
        return 2 + 3 * buf[i + 1]
    if t in FIXED_SIZES:
        return FIXED_SIZES[t]
    if t == p.PKT_SELF_ITEMS:
        # a bitmask, then one count byte per set bit
        mask = struct.unpack(">I", buf[i + 1 : i + 5])[0]
        return 5 + bin(mask).count("1")
    if t == p.PKT_MODIFIERS:
        end = buf.find(b"\0", i + 1)
        return None if end < 0 else end - i + 1
    if t == p.PKT_RELIABLE:
        # %c%hd%ld%ld header, then the payload the short announces
        return 11 + struct.unpack(">h", buf[i + 1 : i + 3])[0]
    return None


def decode_frame(buf: bytes) -> Frame:
    """Decode one datagram into a Frame.

    Never raises on malformed input: a bot that dies on a strange packet is
    worse than one that flies with a partial view and says so.
    """
    f = Frame()
    i = 0
    n = len(buf)

    while i < n:
        t = buf[i]
        length = packet_length(buf, i)
        if length is None or length <= 0 or i + length > n:
            f.truncated = True
            f.truncated_at = t
            return f

        body = buf[i : i + length]

        if t == p.PKT_START:
            _, f.loops, f.key_ack = struct.unpack(">Bii", body[:9])

        elif t == p.PKT_SELF:
            s = Self()
            (_, s.x, s.y, s.vx, s.vy, s.heading, s.power, s.turnspeed,
             s.turnresistance, s.lock_id, s.lock_dist, s.lock_dir,
             s.next_checkpoint) = struct.unpack(">Bhhhh4BhhBB", body[:19])
            (s.current_tank, s.fuel, s.fuel_max, s.view_width, s.view_height,
             _spark, s.status, s.autopilot) = struct.unpack(">Bhhhh3B", body[19:31])
            f.self_ = s

        elif t == p.PKT_SHIP:
            _, x, y, sid, heading, flags = struct.unpack(">BhhhBB", body[:9])
            f.ships.append(Ship(
                x=x, y=y, id=sid, heading=heading,
                shield=bool(flags & 1), cloak=bool(flags & 2),
                eshield=bool(flags & 4), phased=bool(flags & 8),
                deflector=bool(flags & 0x10),
            ))

        elif t == p.PKT_FASTSHOT:
            kind = body[1]
            count = body[2]
            for k in range(count):
                # Coordinates are one byte each, relative to the view.
                f.shots.append(Shot(x=body[3 + 2 * k], y=body[4 + 2 * k],
                                    kind=kind))

        elif t == p.PKT_ITEM:
            _, x, y, kind = struct.unpack(">BhhB", body[:6])
            f.items.append(Item(x=x, y=y, kind=kind))

        elif t == p.PKT_BALL:
            _, x, y, bid, _style = struct.unpack(">BhhhB", body[:8])
            f.balls.append((x, y, bid))

        elif t == p.PKT_MINE:
            _, x, y, teammine, mid = struct.unpack(">BhhBh", body[:8])
            f.mines.append((x, y, mid, bool(teammine)))

        elif t == p.PKT_DAMAGED:
            f.damaged = True

        i += length

    return f
