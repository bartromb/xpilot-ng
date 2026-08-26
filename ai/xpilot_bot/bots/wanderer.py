"""Flies in lazy arcs: thrust constantly, sweep the turn back and forth.

No perception at all -- it never looks at the world. That is the point: it
shows that acting works before any decoding does.
"""

from __future__ import annotations

import math
import time

from ..client import Client
from .. import protocol as p


def run(host: str = "localhost", port: int = 15345, seconds: float = 60.0) -> None:
    with Client(host=host, port=port, nick="wanderer", user="wanderer") as c:
        start = time.time()
        while time.time() - start < seconds:
            t = time.time() - start
            c.release_all()
            c.press(p.KEY_THRUST)
            # A slow sine gives a wandering curve rather than a tight spin.
            c.press(p.KEY_TURN_LEFT if math.sin(t / 1.5) > 0 else p.KEY_TURN_RIGHT)
            c.send_keys()
            c.poll()
            time.sleep(0.05)


if __name__ == "__main__":
    run()
