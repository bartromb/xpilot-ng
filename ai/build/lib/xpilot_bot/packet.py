"""Wire encoding for the XPilot NG protocol.

This mirrors Packet_printf/Packet_scanf in src/common/net.c. Integers are
big-endian and strings are NUL-terminated; there is no length prefix
anywhere, which is why a reader has to know the expected shape in advance.

Sizes, taken from the C:

    %c        1 byte
    %hd %hu   2 bytes
    %d  %u    4 bytes
    %ld %lu   4 bytes   (four, not eight -- see net.c around line 660)
    %s        NUL-terminated, capped at MAX_CHARS (80) by the server
    %S        NUL-terminated, capped at MSG_LEN (256)
"""

from __future__ import annotations

import struct

MAX_CHARS = 80
MSG_LEN = 256


class Writer:
    """Builds a packet body."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def c(self, v: int) -> "Writer":
        self.buf.append(v & 0xFF)
        return self

    def hu(self, v: int) -> "Writer":
        self.buf += struct.pack(">H", v & 0xFFFF)
        return self

    def hd(self, v: int) -> "Writer":
        self.buf += struct.pack(">h", v)
        return self

    def u(self, v: int) -> "Writer":
        self.buf += struct.pack(">I", v & 0xFFFFFFFF)
        return self

    def d(self, v: int) -> "Writer":
        self.buf += struct.pack(">i", v)
        return self

    # %ld is four bytes on the wire, matching the C.
    ld = d
    lu = u

    def s(self, v: str) -> "Writer":
        self.buf += v.encode("latin-1", "replace")[: MAX_CHARS - 1]
        self.buf.append(0)
        return self

    def raw(self, b: bytes) -> "Writer":
        self.buf += b
        return self

    def bytes(self) -> bytes:
        return bytes(self.buf)


class Reader:
    """Reads a packet body.

    Raises Truncated rather than returning junk when the packet is shorter
    than the caller expects, because a bot silently acting on a half-parsed
    packet is worse than one that stops.
    """

    class Truncated(Exception):
        pass

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def _take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise Reader.Truncated(
                f"want {n} bytes at {self.pos}, have {self.remaining()}"
            )
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out

    def c(self) -> int:
        return self._take(1)[0]

    def hu(self) -> int:
        return struct.unpack(">H", self._take(2))[0]

    def hd(self) -> int:
        return struct.unpack(">h", self._take(2))[0]

    def u(self) -> int:
        return struct.unpack(">I", self._take(4))[0]

    def d(self) -> int:
        return struct.unpack(">i", self._take(4))[0]

    ld = d
    lu = u

    def s(self) -> str:
        end = self.data.find(b"\0", self.pos)
        if end < 0:
            raise Reader.Truncated("unterminated string")
        out = self.data[self.pos : end]
        self.pos = end + 1
        return out.decode("latin-1")

    def rest(self) -> bytes:
        out = self.data[self.pos :]
        self.pos = len(self.data)
        return out
