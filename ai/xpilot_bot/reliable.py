"""Decoding the reliable sub-stream: scores, players, messages.

The frame stream (see frames.py) carries where everything *is*. It does not
carry what any of it *means* -- who is playing, who killed whom, what the
score is. All of that travels on a second, ordered channel multiplexed into
the same UDP socket as PKT_RELIABLE segments, and until this module existed
the bot acknowledged those segments without ever looking inside them. That is
why win rates were unmeasurable: the information was arriving all along.

Two things make this more than a switch statement.

**It is a byte stream, not a packet stream.** Segments carry an offset into a
continuous stream, they arrive out of order, they are retransmitted, and a
single packet may straddle a segment boundary. So bytes are buffered by
offset and parsed only once contiguous.

**Packets are variable-length and undelimited.** Several carry NUL-terminated
strings, so a packet's size is not known until it has been parsed. A partial
packet at the end of the buffer is therefore normal and must be left alone
until the rest arrives -- not skipped, because skipping desynchronises
everything after it.

**It does not begin with packets at all.** The stream opens with the verify
reply and a magic number, and then the entire map arrives as an opaque blob
whose length is announced in a header. Only after that blob does the packet
stream start. An earlier attempt here tried to sidestep that by switching
decoding on once setup "looked finished", which worked or desynchronised
depending on packet timing -- the layout is deterministic, so it is parsed
rather than guessed at:

    [PKT_REPLY][PKT_MAGIC][setup header + map_data_len bytes][packets...]

Formats come from the Receive_* functions in src/client/netclient.c. Several
are version-dependent; the ones here are for 4.7.x (version >= 0x4F11), which
is what this fork's server speaks.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

from . import protocol as p


class _Incomplete(Exception):
    """Not enough bytes yet. Not an error -- wait for the next segment."""


@dataclass
class Player:
    """A participant, from PKT_PLAYER."""

    id: int
    team: int
    mychar: str          # ' ' alive, 'W' waiting, 'P' paused, 'D' game over
    nick: str
    user: str
    host: str
    shape: str = ""
    myself: bool = False

    #: Filled in from PKT_SCORE as the game runs.
    score: float = 0.0
    life: int = 0
    #: Deaths, counted by watching `life` fall. An *increase* is a new round
    #: rather than a resurrection, so it is counted separately.
    deaths: int = 0
    #: Kills credited by the server's death notices.
    kills: int = 0
    rounds: int = 0
    #: False until the first PKT_SCORE, because the initial `life` is not a
    #: transition and must not be read as one.
    _seen_life: bool = False


@dataclass
class Setup:
    """Map and game parameters, from the setup blob at the head of the stream."""

    map_data_len: int = 0
    mode: int = 0
    lives: int = 0
    width: int = 0
    height: int = 0
    fps: int = 0
    name: str = ""
    author: str = ""
    data_url: str = ""


@dataclass
class Message:
    """A line of text, from PKT_MESSAGE."""

    text: str


#: Death notices, from the sprintf formats in src/server/*.c. Order matters:
#: the general "killed by X" case must be tried after the specific ones, or it
#: swallows "a ball owned by X" and reports the killer as "a ball owned by X".
_DEATHS = [
    # "%s was killed by %s from %s.%s"  -- e.g. "a shot from Pilt"
    (re.compile(r"^(?P<v>.+?) was killed by .+? from (?P<k>.+?)\.\s*$"), True),
    # "%s was killed by a ball owned by %s.%s"
    (re.compile(r"^(?P<v>.+?) was killed by a ball owned by (?P<k>.+?)\.\s*$"), True),
    # "%s was killed by a ball."   -- nobody is credited
    (re.compile(r"^(?P<v>.+?) was killed by a ball\.\s*$"), False),
    # "%s was killed by %s."
    (re.compile(r"^(?P<v>.+?) was killed by (?P<k>.+?)\.\s*$"), True),
    # "%s smashed into an asteroid." / "%s crashed%s against a wall" / etc.
    (re.compile(r"^(?P<v>.+?) (?:crashed|smashed)\b.*$"), False),
]

#: "%s and %s crashed." kills both of them and credits neither.
_MUTUAL = re.compile(r"^(?P<a>.+?) and (?P<b>.+?) crashed\.\s*$")


@dataclass
class ScoreEvent:
    """A score change at a position, from PKT_SCORE_OBJECT.

    This is what the client draws floating over the map ("+10"), and it is
    the closest thing the protocol has to a kill notification.
    """

    score: float
    x: int
    y: int
    text: str


class ScoreBoard:
    """Accumulated state from the reliable stream."""

    def __init__(self) -> None:
        self.players: dict[int, Player] = {}
        self.messages: list[Message] = []
        self.score_events: list[ScoreEvent] = []
        self.team_scores: dict[int, float] = {}
        self.own_id: int | None = None
        self.setup: Setup | None = None
        #: Highest chat sequence the server has acknowledged. The client
        #: resends an unacknowledged message, so it needs to be told.
        self.talk_ack: int = 0
        #: Types seen that this module does not decode, for diagnosing gaps.
        self.unknown: dict[int, int] = {}
        #: Every type decoded, and how often. Cheap, and the fastest way to
        #: answer "did that packet actually arrive?" when a count looks wrong.
        self.counts: dict[int, int] = {}

    # -- convenience -------------------------------------------------------

    @property
    def me(self) -> Player | None:
        return self.players.get(self.own_id) if self.own_id is not None else None

    def opponents(self) -> list[Player]:
        return [pl for pid, pl in self.players.items() if pid != self.own_id]

    def _by_nick(self, nick: str):
        for pl in self.players.values():
            if pl.nick == nick:
                return pl
        return None

    def note_message(self, text: str) -> None:
        """Count kills and deaths from the game's own death notices.

        This is the authoritative record, and on most maps it is the *only*
        one: PKT_SCORE carries a life count, but where lives are unlimited it
        never changes, so watching it detects nothing. The messages are what
        a human player reads, and they are generated by the server rather
        than by any client.

        Player chat is excluded by the one reliable discriminator available:
        the server appends " [nick]" to everything a player says, and to
        nothing it says itself. Without that check a player could type a
        death notice and have it counted.
        """
        text = text.strip()
        if text.endswith("]"):
            return                       # chat, or a server notice

        m = _MUTUAL.match(text)
        if m:
            hits = [self._by_nick(m.group("a")), self._by_nick(m.group("b"))]
            if all(hits):
                for pl in hits:
                    pl.deaths += 1
                return

        for pattern, has_killer in _DEATHS:
            m = pattern.match(text)
            if not m:
                continue
            victim = self._by_nick(m.group("v"))
            if victim is None:
                # Not a name we know: some other message that happens to
                # read like one. Counting it would invent a death.
                continue
            victim.deaths += 1
            if has_killer:
                killer = self._by_nick(m.group("k"))
                if killer is not None and killer is not victim:
                    killer.kills += 1
            return

    def deaths_for(self, pid: int) -> int:
        pl = self.players.get(pid)
        return pl.deaths if pl else 0

    def summary(self) -> dict:
        """A flat dict, for logging and for the benchmark's win rate."""
        me = self.me
        opp = self.opponents()
        return {
            "own_score": me.score if me else None,
            "own_deaths": me.deaths if me else None,
            "own_lives": me.life if me else None,
            "own_kills": me.kills if me else None,
            "opponents": len(opp),
            "opponent_score_total": sum(o.score for o in opp),
            "opponent_deaths_total": sum(o.deaths for o in opp),
            "messages": len(self.messages),
        }


# --------------------------------------------------------------- parsing


class _Cursor:
    """A bounds-checked reader that raises _Incomplete rather than truncating."""

    __slots__ = ("buf", "i")

    def __init__(self, buf: bytes, i: int = 0) -> None:
        self.buf, self.i = buf, i

    def _take(self, n: int) -> bytes:
        if self.i + n > len(self.buf):
            raise _Incomplete
        out = self.buf[self.i : self.i + n]
        self.i += n
        return out

    def u8(self) -> int:
        return self._take(1)[0]

    def i16(self) -> int:
        return struct.unpack(">h", self._take(2))[0]

    def u16(self) -> int:
        return struct.unpack(">H", self._take(2))[0]

    def i32(self) -> int:
        return struct.unpack(">i", self._take(4))[0]

    def u32(self) -> int:
        return struct.unpack(">I", self._take(4))[0]

    def string(self) -> str:
        end = self.buf.find(b"\0", self.i)
        if end < 0:
            raise _Incomplete
        out = self.buf[self.i : end]
        self.i = end + 1
        return out.decode("latin-1")


class ReliableStream:
    """Reassembles and decodes the reliable sub-stream.

    Feed it segments with `feed`; read the result off `board`.
    """

    #: Refuse to buffer more than this while waiting for a gap to fill. The
    #: stream is ordered and the server retransmits, so a gap that never
    #: closes means something is wrong; growing without bound would be worse.
    MAX_PENDING = 1 << 20

    def __init__(self) -> None:
        self.board = ScoreBoard()
        #: Next offset the parser expects, i.e. how much of the stream is done.
        self.offset = 0
        self._buf = bytearray()          # contiguous, unparsed, starts at self.offset
        self._pending: dict[int, bytes] = {}   # out-of-order segments
        #: Set once a packet cannot be decoded at all. The stream is a byte
        #: stream, so this is unrecoverable and further decoding stops.
        self.desynced = False
        self.desynced_at: int | None = None
        #: The stream opens with the map as an opaque blob. Until it has been
        #: stepped over, the bytes here are not packets.
        self._phase = "prologue"     # prologue -> setup -> packets
        self._skip = 0               # map bytes still to step over

    # -- input -------------------------------------------------------------

    def feed(self, offset: int, payload: bytes) -> None:
        """Add one reliable segment at its stream offset."""
        if self.desynced or not payload:
            return

        end = offset + len(payload)
        if end <= self.offset + len(self._buf):
            return                        # wholly retransmitted; already have it

        head = self.offset + len(self._buf)
        if offset > head:
            # A gap: hold it until the missing bytes arrive.
            if sum(map(len, self._pending.values())) < self.MAX_PENDING:
                self._pending[offset] = payload
            return

        # Overlapping or contiguous: append only the part we do not have.
        self._buf += payload[head - offset :]

        # A held segment may now be contiguous; keep draining while so.
        while True:
            head = self.offset + len(self._buf)
            # Anything entirely behind head is data we already have. Dropping
            # it matters: retransmissions are routine, so without this the
            # held set grows until it hits MAX_PENDING and starts refusing
            # segments that are genuinely needed.
            for off in [o for o, d in self._pending.items() if o + len(d) <= head]:
                del self._pending[off]

            seg = self._pending.pop(head, None)
            if seg is None:
                # Also accept a held segment that starts before head.
                for off in sorted(self._pending):
                    if off <= head < off + len(self._pending[off]):
                        seg = self._pending.pop(off)[head - off :]
                        break
                    if off > head:
                        break
            if seg is None:
                break
            self._buf += seg

        self._parse()

    # -- decoding ----------------------------------------------------------

    def _parse(self) -> None:
        """Consume as many whole packets as the buffer holds."""
        while self._buf and not self.desynced:
            if self._skip:
                n = min(self._skip, len(self._buf))
                del self._buf[:n]
                self.offset += n
                self._skip -= n
                continue
            if self._phase == "setup":
                if not self._parse_setup():
                    return               # wait for the rest of the header
                continue

            c = _Cursor(bytes(self._buf))
            try:
                if not self._packet(c):
                    self.desynced = True
                    self.desynced_at = self._buf[0]
                    return
            except _Incomplete:
                return                    # wait for more bytes
            consumed = c.i
            if consumed <= 0:             # would loop forever
                self.desynced = True
                self.desynced_at = self._buf[0]
                return
            del self._buf[:consumed]
            self.offset += consumed

    def _parse_setup(self) -> bool:
        """Read the setup header and arrange to step over the map data.

        Format from Net_setup in src/client/netclient.c (the modern branch;
        `oldServer` is a pre-4.5 wire format this fork's server never speaks).
        """
        c = _Cursor(bytes(self._buf))
        try:
            st = Setup(
                map_data_len=c.i32(), mode=c.i32(), lives=c.i16(),
                width=c.i16(), height=c.i16(), fps=c.i16(),
                name=c.string(), author=c.string(), data_url=c.string(),
            )
        except _Incomplete:
            return False

        if st.map_data_len <= 0 or st.width <= 0 or st.height <= 0:
            # The same sanity check the C client makes. Failing it means the
            # stream is not where we think it is, and guessing on would be
            # worse than stopping.
            self.desynced = True
            self.desynced_at = None
            return False

        self.board.setup = st
        del self._buf[: c.i]
        self.offset += c.i
        self._skip = st.map_data_len
        self._phase = "packets"
        return True

    def _packet(self, c: _Cursor) -> bool:
        """Decode one packet. False means the type is unknown (fatal here)."""
        b = self.board
        t = c.u8()
        b.counts[t] = b.counts.get(t, 0) + 1

        if t == p.PKT_SCORE:
            pid, score, life = c.i16(), c.i32(), c.i16()
            mychar, alliance = c.u8(), c.u8()
            pl = b.players.get(pid)
            if pl is not None:
                if pl._seen_life:
                    if life < pl.life:
                        pl.deaths += pl.life - life
                    elif life > pl.life:
                        pl.rounds += 1
                pl._seen_life = True
                pl.life = life
                # The server scales scores by 100 in this protocol version.
                pl.score = score / 100.0
                pl.mychar = chr(mychar)
            return True

        if t == p.PKT_PLAYER:
            pid, team, mychar = c.i16(), c.u8(), c.u8()
            nick, user, host = c.string(), c.string(), c.string()
            # The ship shape arrives as *two* strings, not one: Send_player
            # writes the base shape and then an "ext" continuation, which the
            # C client appends to the first. Reading only one leaves a whole
            # string on the stream and desynchronises everything after it.
            shape = c.string() + c.string()
            myself = bool(c.u8())
            b.players[pid] = Player(
                id=pid, team=team, mychar=chr(mychar), nick=nick,
                user=user, host=host, shape=shape, myself=myself,
            )
            if myself:
                b.own_id = pid
            return True

        if t == p.PKT_LEAVE:
            b.players.pop(c.i16(), None)
            return True

        if t == p.PKT_MESSAGE:
            text = c.string()
            b.messages.append(Message(text=text))
            b.note_message(text)
            return True

        if t == p.PKT_SCORE_OBJECT:
            score, x, y = c.i32(), c.u16(), c.u16()
            b.score_events.append(
                ScoreEvent(score=score / 100.0, x=x, y=y, text=c.string()))
            return True

        if t == p.PKT_TALK_ACK:
            seq = c.i32()
            if seq > b.talk_ack:
                b.talk_ack = seq
            return True

        if t == p.PKT_TEAM_SCORE:
            team, score = c.i16(), c.i32()
            b.team_scores[team] = score / 100.0
            return True

        if t == p.PKT_MOTD:
            # "%c%ld%hd%ld": offset into the motd, the length of *this*
            # chunk, and the total motd size. The chunk's text follows
            # inline, and it is the short -- not the trailing long -- that
            # says how much of it to step over.
            _offset, chunk_len, _total_size = c.i32(), c.i16(), c.i32()
            c._take(max(chunk_len, 0))
            return True

        # Fixed-size packets with nothing this bot needs. They still have to
        # be sized exactly right, because getting one wrong desynchronises
        # every packet after it.
        if t == p.PKT_MAGIC:
            c.u32()
            # The map blob follows the magic number immediately.
            if self._phase == "prologue":
                self._phase = "setup"
            return True

        sizes = {
            p.PKT_REPLY: 2,         # %c%c   (replyto, status)
            p.PKT_TEAM: 3,          # %hd%c
            p.PKT_SEEK: 6,          # %hd%hd%hd
            p.PKT_BASE: 4,          # %hd%hu
            p.PKT_WAR: 4,           # %hd%hd
            p.PKT_TIMING: 4,        # %hd%hu
            p.PKT_STRING: 5,        # %c%hu%hu
        }
        if t in sizes:
            c._take(sizes[t])
            return True

        if t == p.PKT_QUIT:
            c.string()
            return True

        b.unknown[t] = b.unknown.get(t, 0) + 1
        return False
