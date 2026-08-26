"""Death detection, tested against synthetic frames.

The protocol has no "you died" packet. What it has is the absence of
PKT_SELF: Receive_self in netclient.c notes that a frame missing it means the
player "isn't actively playing, which means he's either damaged, dead, paused
or has game over".

This uses fabricated frames rather than dying in a real game, because
provoking a death on demand turned out to be unreliable -- holding
self-destruct for thirty seconds against a live server did not produce one.
The mechanism is what is asserted here; whether a given server kills you is
not this code's business.
"""

import numpy as np

from xpilot_bot.env import XPilotEnv
from xpilot_bot.frames import Frame, Self
from xpilot_bot.reliable import ReliableStream


class FakeClient:
    """Replays a scripted sequence of frames."""

    def __init__(self, frames):
        self._frames = list(frames)
        self.sent = 0
        # The real client carries one, and env reports from it.
        self.reliable = ReliableStream()

    def poll(self):
        return self._frames.pop(0) if self._frames else _alive()

    def release_all(self): pass
    def press(self, key): pass
    def send_keys(self): self.sent += 1
    def close(self): pass


def _alive():
    f = Frame()
    f.self_ = Self(x=100, y=100, fuel=500, fuel_max=1000, heading=0)
    return f


def _not_playing():
    return Frame()          # no self_


def _env_with(frames, death_frames=5):
    env = XPilotEnv(port=1, death_frames=death_frames, max_steps=10_000)
    env._client = FakeClient(frames)
    env._last_obs = np.zeros(env.observation_space.shape, dtype=np.float32)
    return env


def test_run_of_missing_frames_ends_the_episode():
    env = _env_with([_not_playing()] * 5)
    _obs, reward, terminated, truncated, info = env.step(0)
    assert terminated and not truncated
    assert info.get("died") is True
    assert reward < 0, "dying should cost something"


def test_a_short_gap_is_not_death():
    # Gaps happen between lives and while paused; one is not a death.
    env = _env_with([_not_playing()] * 2 + [_alive()], death_frames=5)
    _obs, _reward, terminated, truncated, info = env.step(0)
    assert not terminated and not truncated
    assert "died" not in info


def test_observation_is_held_over_death():
    """There is no own-ship state while dead, so the last one is repeated
    rather than a fabricated zero vector being handed to the agent."""
    env = _env_with([_alive()])
    obs_alive, _, _, _, _ = env.step(0)
    env._client = FakeClient([_not_playing()] * 5)
    obs_dead, _, terminated, _, _ = env.step(0)
    assert terminated
    assert np.allclose(obs_alive, obs_dead)


if __name__ == "__main__":
    import sys
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print(f"  PASS  {name}")
            except AssertionError as exc:
                failures += 1; print(f"  FAIL  {name}: {exc}")
    print("all death-detection tests passed" if not failures
          else f"{failures} failed")
    sys.exit(1 if failures else 0)
