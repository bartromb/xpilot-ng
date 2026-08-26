"""The smallest possible bot: joins, holds still, stays connected.

Useful as a connectivity check and as a punching bag for other bots.
"""

from __future__ import annotations

import time

from ..client import Client


def run(host: str = "localhost", port: int = 15345, seconds: float = 60.0) -> None:
    with Client(host=host, port=port, nick="idle", user="idle") as c:
        end = time.time() + seconds
        while time.time() < end:
            c.send_keys()      # an empty key state, but it keeps us alive
            c.poll()
            time.sleep(0.05)


if __name__ == "__main__":
    run()
