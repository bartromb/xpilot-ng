"""Choosing a tactic, slowly, while the controller keeps flying.

The roadmap asks for an LLM as a high-level strategy layer on a classical
controller, and is emphatic that it is never for frame-level control because
the latency is unsuitable. It is right, and the number is worth stating: at
255 frames per second a frame is 4 ms, while a small model's round trip is
somewhere between several hundred milliseconds and several seconds. That is
two to three orders of magnitude apart.

So the split here is strict:

  tactics.py    every frame, pure arithmetic, decides which keys to hold
  strategy.py   every few seconds, may block, decides which *word* to hold

The strategist runs on its own thread and publishes a decision when it has
one. The control loop never waits for it; it keeps executing the last tactic,
which is a perfectly good thing to be doing. If the model is slow, the bot
plays slightly out of date. If the model is unreachable, the bot falls back
to a rule-based strategist and carries on. Neither is a failure state, and
that is the point of putting the model here rather than in the loop.

Nothing in this module is required to run a bot: `ScriptedStrategist` is the
default and has no dependencies. `LLMStrategist` uses `urllib` from the
standard library, so enabling it adds nothing to install either.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .tactics import (CAUTIOUS_FUEL, EVADE_RANGE, LOW_FUEL, TACTICS,
                      Situation)

LOG = logging.getLogger("xpilot_bot.strategy")


@dataclass
class Decision:
    """What to do, and optionally what to say about it."""

    tactic: str
    say: str | None = None
    #: Where it came from, so a log can distinguish a model's judgement from
    #: a fallback that merely looks like one.
    source: str = "scripted"

    def validated(self) -> "Decision":
        """Force the tactic into the allowed set.

        A language model will eventually answer "attack" or "Hunt." or a
        sentence. Guessing at intent invites a bot that does something
        different from what it said; refusing outright would drop a decision
        that is nearly right. So: exact match, then a forgiving match, then
        give up and patrol.
        """
        raw = (self.tactic or "").strip().strip('".').lower()
        if raw in TACTICS:
            # Return the cleaned name, not self: the caller compares this
            # against TACTICS, and "evade." would fail that comparison
            # everywhere downstream.
            return Decision(raw, self.say, self.source)
        for name in TACTICS:
            if raw.startswith(name) or name in raw.split():
                return Decision(name, self.say, self.source)
        LOG.warning("unusable tactic %r; patrolling", self.tactic)
        return Decision("patrol", self.say, self.source + "+rejected")


class Strategist:
    """Decides a tactic from a situation. Called off the control loop."""

    #: Seconds between decisions. Tactics are not frame-level things.
    interval = 3.0

    def decide(self, situation: Situation) -> Decision:
        raise NotImplementedError


class ScriptedStrategist(Strategist):
    """Rules. The default, the fallback, and the thing to beat.

    Worth keeping honest about: this is not a weak baseline chosen to make a
    language model look good. Most of what matters in this game is close
    range and reflexive, and rules are good at that.
    """

    def decide(self, situation: Situation) -> Decision:
        s = situation
        shot = s.nearest_shot
        enemy = s.nearest_enemy

        # 90 pixels, not the 220 this started with. In a firefight there is
        # almost always *a* shot within 220 pixels, so the bot broke off
        # permanently and never attacked. Measured over two rounds: at 220 it
        # scored 0 kills against 18 deaths, at 90 it scored 7 against 19.
        #
        # Note what that second number says. All the extra evading bought no
        # survival whatsoever -- deaths were 18 either way. The defensive
        # tactic was not defending, it was only failing to attack.
        if shot is not None and shot.dist < EVADE_RANGE:
            return Decision("evade", source="scripted")
        if s.fuel < LOW_FUEL:
            return Decision("regroup", source="scripted")
        if enemy is None:
            return Decision("patrol", source="scripted")
        if s.fuel < CAUTIOUS_FUEL or enemy.dist > 500:
            return Decision("snipe", source="scripted")
        return Decision("hunt", source="scripted")


SYSTEM_PROMPT = """\
You are the tactical commander of a ship in XPilot, a 2D space combat game.

You do not fly the ship. A controller does that, every frame. Your job is to
pick which of these it should be doing, and you are asked again every few
seconds:

  hunt     close on the nearest enemy and shoot it
  snipe    hold range, fire only on a good line, spend less fuel
  evade    turn away from the nearest threat and run, shields if it is close
  regroup  break off entirely, no firing, buy time
  patrol   nothing in view, keep moving and look around

Reply with JSON only: {"tactic": "<one of the five>", "say": "<optional>"}

"say" is a short taunt or remark broadcast to the other players, at most 60
characters. Use it rarely -- at most one message in five decisions -- and
never repeat yourself. Omit it or use null most of the time.
"""


class LLMStrategist(Strategist):
    """Asks a language model, and is prepared for it not to answer.

    Every failure mode ends in the scripted strategist rather than in an
    exception: no key configured, no network, a timeout, a malformed body, a
    tactic that is not a tactic. A bot that stops flying because an API
    call failed would be a worse bot than one that never called an API.
    """

    #: The model is asked less often than the rules, because each call costs
    #: money and latency, and tactics do not change that fast.
    interval = 5.0

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        api_key: str | None = None,
        timeout: float = 6.0,
        fallback: Strategist | None = None,
        endpoint: str = "https://api.anthropic.com/v1/messages",
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.timeout = timeout
        self.endpoint = endpoint
        self.fallback = fallback or ScriptedStrategist()
        #: Counted so a run can be judged on how often the model actually
        #: decided anything, rather than on the assumption that it did.
        self.calls = 0
        self.failures = 0

    def available(self) -> bool:
        return bool(self.api_key)

    def decide(self, situation: Situation) -> Decision:
        if not self.available():
            return self.fallback.decide(situation)
        try:
            body = self._ask(self._describe(situation))
            self.calls += 1
            return Decision(
                tactic=body.get("tactic", ""),
                say=body.get("say") or None,
                source="llm",
            ).validated()
        except Exception as exc:                  # noqa: BLE001 - see docstring
            self.failures += 1
            LOG.warning("strategist falling back to rules: %s", exc)
            return self.fallback.decide(situation)

    # -- prompt ---------------------------------------------------------

    @staticmethod
    def _describe(s: Situation) -> str:
        """A compact, factual situation report.

        Distances in pixels and bearings in clock positions, because "enemy
        at 2 o'clock, 180 away" is a thing a model reasons about well, and
        "bearing -1.0472 rad" is not.
        """
        def clock(bearing: float) -> str:
            # Bearing is signed radians from the nose, positive to port.
            hours = (-bearing / (2 * 3.141592653589793) * 12) % 12
            return f"{int(round(hours)) or 12} o'clock"

        lines = [
            f"fuel {s.fuel:.0f} (tank holds {s.fuel_max:.0f}; "
            f"under {LOW_FUEL:.0f} is trouble), speed {s.speed:.0f}",
            f"score {s.score:.0f}, {s.kills} kills, {s.deaths} deaths",
            f"currently: {s.tactic}",
        ]
        if s.enemies:
            lines.append("enemies: " + "; ".join(
                f"{c.dist:.0f} away at {clock(c.bearing)}"
                for c in s.enemies[:3]))
        else:
            lines.append("enemies: none in view")
        if s.shots:
            near = s.shots[0]
            lines.append(f"nearest incoming fire: {near.dist:.0f} away "
                         f"at {clock(near.bearing)}")
        return "\n".join(lines)

    def _ask(self, description: str) -> dict:
        payload = json.dumps({
            "model": self.model,
            "max_tokens": 100,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": description}],
        }).encode("utf-8")

        req = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            reply = json.loads(resp.read().decode("utf-8"))

        text = "".join(part.get("text", "")
                       for part in reply.get("content", []))
        return _first_json_object(text)


def _first_json_object(text: str) -> dict:
    """Pull the first JSON object out of a reply.

    Models wrap JSON in prose and code fences however they are asked not to,
    and a strategist that fails on a stray ```json is a strategist that falls
    back to rules for the whole game.
    """
    start = text.find("{")
    if start < 0:
        raise ValueError(f"no JSON object in reply: {text[:120]!r}")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError(f"unterminated JSON in reply: {text[:120]!r}")


class BackgroundStrategist:
    """Runs a strategist on its own thread and publishes its latest decision.

    This is the piece that makes a slow strategist usable. `current` returns
    immediately, always, with the most recent answer; the control loop never
    blocks on a decision and never skips a frame waiting for one. A stale
    tactic is a perfectly good thing to be executing.
    """

    def __init__(self, strategist: Strategist, initial: str = "patrol") -> None:
        self.strategist = strategist
        self._decision = Decision(initial, source="initial")
        self._situation: Situation | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        #: Decisions actually taken up by the control loop.
        self.updates = 0

    def start(self) -> "BackgroundStrategist":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def observe(self, situation: Situation) -> None:
        """Hand the thread the latest view of the world. Never blocks."""
        with self._lock:
            self._situation = situation

    @property
    def current(self) -> Decision:
        with self._lock:
            return self._decision

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                situation = self._situation
            if situation is not None:
                try:
                    decision = self.strategist.decide(situation)
                except Exception as exc:          # noqa: BLE001
                    LOG.warning("strategist raised, keeping last: %s", exc)
                else:
                    with self._lock:
                        if decision.tactic != self._decision.tactic:
                            self.updates += 1
                        self._decision = decision
            self._stop.wait(self.strategist.interval)
