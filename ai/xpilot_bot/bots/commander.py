"""A bot with a strategy layer: rules fly it, something slower decides.

    python -m xpilot_bot.bots.commander --seconds 120
    ANTHROPIC_API_KEY=... python -m xpilot_bot.bots.commander --llm

The controller in `tactics.py` runs every frame and holds keys. The
strategist in `strategy.py` runs on another thread every few seconds and
changes which tactic the controller is executing. With `--llm` that
strategist asks a language model; without it, and whenever the model is
unreachable, it is a handful of rules.

This is the roadmap's stretch goal, and the reason it is shaped this way is
the roadmap's own caveat: an LLM is unsuitable for frame-level control. At
255 fps a frame is 4 ms and a model round trip is hundreds of milliseconds
at best, so the model is given the one job whose timescale actually matches
it -- choosing between five words every few seconds -- and is never in the
path of flying the ship.
"""

from __future__ import annotations

import argparse
import logging
import math
import time

from .. import protocol as p
from ..client import Client
from ..frames import world_shots, wrapped_delta
from ..strategy import (BackgroundStrategist, LLMStrategist,
                        ScriptedStrategist)
from ..tactics import Contact, Situation, plan_keys

LOG = logging.getLogger("xpilot_bot.commander")

#: Beyond this, something is not worth reporting as a contact.
SIGHT = 1400.0


def observe(client: Client, tactic: str) -> Situation:
    """Turn the decoded frame and scoreboard into a Situation.

    Bearings are signed radians from our nose, positive to port, which is
    what both the controller and the prompt expect.
    """
    frame = client.frame
    board = client.reliable.board
    me = frame.self_ if frame is not None else None
    if me is None:
        return Situation(alive=False, tactic=tactic)

    setup = board.setup
    w = setup.width if setup else 0
    h = setup.height if setup else 0
    heading = 2 * math.pi * me.heading / 128.0

    def contact(x, y) -> Contact:
        dx, dy = wrapped_delta(w, h, me.x, me.y, x, y)
        bearing = math.atan2(dy, dx) - heading
        bearing = (bearing + math.pi) % (2 * math.pi) - math.pi
        return Contact(dist=math.hypot(dx, dy), bearing=bearing)

    enemies = [contact(s.x, s.y) for s in frame.ships
               if (s.x, s.y) != (me.x, me.y)]
    enemies = sorted((c for c in enemies if c.dist < SIGHT),
                     key=lambda c: c.dist)

    shots = [contact(x, y) for x, y, _kind in world_shots(frame)]
    # Our own muzzle flash sits on top of us; reporting it as incoming fire
    # would have the bot permanently evading itself.
    shots = sorted((c for c in shots if 20 < c.dist < SIGHT),
                   key=lambda c: c.dist)

    mine = board.me
    return Situation(
        alive=True,
        fuel=float(me.fuel),
        fuel_max=float(me.fuel_max),
        speed=math.hypot(me.vx, me.vy),
        enemies=enemies,
        shots=shots,
        score=mine.score if mine else 0.0,
        kills=mine.kills if mine else 0,
        deaths=mine.deaths if mine else 0,
        tactic=tactic,
    )


def run(host: str = "localhost", port: int = 15345, seconds: float = 120.0,
        use_llm: bool = False, model: str = "claude-haiku-4-5-20251001",
        nick: str = "commander", fps: int = 60, quiet: bool = False) -> dict:
    """Play for `seconds`, and return what happened."""
    strategist = ScriptedStrategist()
    if use_llm:
        llm = LLMStrategist(model=model, fallback=strategist)
        if not llm.available():
            LOG.warning("no ANTHROPIC_API_KEY; using rules instead")
        strategist = llm

    background = BackgroundStrategist(strategist, initial="patrol")
    said = set()
    tactic_frames: dict[str, int] = {}

    with Client(host=host, port=port, nick=nick, user=nick, fps=fps) as client:
        background.start()
        try:
            tactic = "patrol"
            end = time.time() + seconds
            while time.time() < end:
                frame = client.poll()
                if frame is None:
                    continue

                situation = observe(client, tactic)
                background.observe(situation)

                decision = background.current
                if decision.tactic != tactic:
                    tactic = decision.tactic
                    if not quiet:
                        LOG.info("tactic -> %s (%s)", tactic, decision.source)
                # Say a thing at most once, so a model that repeats itself
                # does not spam the server.
                if decision.say and decision.say not in said:
                    said.add(decision.say)
                    client.say(decision.say)

                tactic_frames[tactic] = tactic_frames.get(tactic, 0) + 1

                client.release_all()
                for key in plan_keys(situation, tactic):
                    client.press(key)
                client.send_keys()
        finally:
            background.stop()

        board = client.reliable.board
        mine = board.me
        result = {
            "kills": mine.kills if mine else 0,
            "deaths": mine.deaths if mine else 0,
            "score": mine.score if mine else 0.0,
            "tactic_changes": background.updates,
            "frames_per_tactic": tactic_frames,
            "said": sorted(said),
        }

    if isinstance(strategist, LLMStrategist):
        result["llm_calls"] = strategist.calls
        result["llm_failures"] = strategist.failures
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=15345)
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--nick", default="commander")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--llm", action="store_true",
                    help="ask a language model to choose tactics. Needs "
                         "ANTHROPIC_API_KEY; falls back to rules without it, "
                         "and on any timeout or error.")
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    result = run(host=args.host, port=args.port, seconds=args.seconds,
                 use_llm=args.llm, model=args.model, nick=args.nick,
                 fps=args.fps)

    print(f"\nkills {result['kills']}  deaths {result['deaths']}  "
          f"score {result['score']:.0f}")
    print(f"tactic changes: {result['tactic_changes']}")
    for name, frames in sorted(result["frames_per_tactic"].items(),
                               key=lambda kv: -kv[1]):
        print(f"  {name:8s} {frames:6d} frames")
    if result["said"]:
        print("said:")
        for line in result["said"]:
            print(f"  {line}")
    if "llm_calls" in result:
        print(f"model: {result['llm_calls']} calls, "
              f"{result['llm_failures']} fell back to rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
