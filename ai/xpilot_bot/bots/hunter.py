"""Thrusts, turns, and fires in bursts.

Honest about its limits: this client does not decode the frame stream, so a
hunter cannot yet aim at anything. It sweeps and shoots, which is enough to
score by accident and enough to show how an action policy is structured. Real
aiming needs the frame decoding described in ai/README.md.
"""

from __future__ import annotations

import math
import time

from ..client import Client
from .. import protocol as p


def run(host: str = "localhost", port: int = 15345, seconds: float = 60.0) -> None:
    with Client(host=host, port=port, nick="hunter", user="hunter") as c:
        start = time.time()
        while time.time() - start < seconds:
            t = time.time() - start
            c.release_all()
            c.press(p.KEY_THRUST)
            c.press(p.KEY_TURN_LEFT if math.sin(t / 2.0) > 0 else p.KEY_TURN_RIGHT)
            # Fire in bursts rather than continuously, so the gun cools.
            if (t % 2.0) < 0.6:
                c.press(p.KEY_FIRE_SHOT)
            c.send_keys()
            c.poll()
            time.sleep(0.05)


if __name__ == "__main__":
    run()
