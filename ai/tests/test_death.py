"""Death detection.

There is no "you died" packet. There is a comment in `Receive_self` saying a
frame without PKT_SELF means the player "isn't actively playing, which means
he's either damaged, dead, paused or has game over", and it is tempting to
build death detection on that. It does not work. Measured against a live
server, an idle bot died ten times in ninety seconds and **not one frame was
missing its PKT_SELF** -- the server reports the ship straight through death
and respawn. An episode built on that signal never ends and the agent is
never told it died.

What the server does state, unambiguously, is a death notice on the reliable
sub-stream: "Probe was killed by a shot from Boson." That is what is used,
and it is what these tests exercise.

The frames here are fabricated; provoking a death on demand against a live
server is not something a test should depend on. What a live server *is*
needed for is confirming the signal exists at all, which is
`ai/tools/check_reliable.py`'s job.
"""

import struct

import numpy as np

from xpilot_bot import protocol as p
from xpilot_bot.env import XPilotEnv
from xpilot_bot.frames import Frame, Self
from xpilot_bot.reliable import ReliableStream


def _player_packet(pid, nick, myself):
    return (struct.pack(">Bh", p.PKT_PLAYER, pid) + b"\x00" + b" "
            + nick.encode() + b"\0" + b"u\0" + b"h\0" + b"shape\0" + b"ext\0"
            + bytes([myself]))


def _message_packet(text):
    return bytes([p.PKT_MESSAGE]) + text.encode() + b"\0"


class FakeClient:
    """Replays a scripted sequence of frames, with a real reliable stream."""

    def __init__(self, frames):
        self._frames = list(frames)
        self.sent = 0
        self.reliable = ReliableStream()
        # Two players, we are "bot". Fed as one segment at offset 0, the way
        # the server sends the player list on joining.
        self._feed(_player_packet(1, "bot", 1) + _player_packet(2, "robo", 0))

    def _feed(self, blob):
        self.reliable.feed(self.reliable.offset, blob)

    def kill_me(self, by="robo"):
        """Make the server announce our death, as it really would."""
        self._feed(_message_packet(f"bot was killed by a shot from {by}."))

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
    env._deaths_at_step = 0
    return env


def test_the_fixture_agrees_with_the_decoder():
    """If the synthetic packets stop matching what the decoder expects, these
    tests would pass while testing nothing."""
    env = _env_with([_alive()])
    board = env._client.reliable.board
    assert not env._client.reliable.desynced
    assert board.own_id == 1 and board.me.nick == "bot"


def test_a_death_notice_ends_the_episode():
    env = _env_with([_alive()])
    env._client.kill_me()
    _obs, reward, terminated, truncated, info = env.step(0)
    assert terminated and not truncated
    assert info.get("died") is True
    assert reward < 0, "dying should cost something"


def test_someone_elses_death_is_not_ours():
    env = _env_with([_alive()])
    env._client._feed(_message_packet("robo was killed by a shot from bot."))
    _obs, _reward, terminated, _truncated, info = env.step(0)
    assert not terminated
    assert "died" not in info
    assert info["scoreboard"]["own_kills"] == 1


def test_frames_without_own_ship_are_a_stall_not_a_death():
    """The old heuristic. It ends the episode -- something has gone wrong --
    but calling it a death would be a guess, and a wrong one."""
    env = _env_with([_not_playing()] * 5, death_frames=5)
    _obs, _reward, terminated, truncated, info = env.step(0)
    assert info.get("died") is None
    assert not terminated or truncated is False


def test_a_short_gap_is_harmless():
    env = _env_with([_not_playing()] * 2 + [_alive()], death_frames=5)
    _obs, _reward, terminated, truncated, info = env.step(0)
    assert not terminated and not truncated
    assert "died" not in info


def test_observation_is_held_over_death():
    """There is no fresh own-ship state to report at the moment of death, so
    the last one is repeated rather than a zero vector being invented."""
    env = _env_with([_alive()])
    obs_alive, _, _, _, _ = env.step(0)
    env._client.kill_me()
    obs_dead, _, terminated, _, _ = env.step(0)
    assert terminated
    assert np.allclose(obs_alive, obs_dead)


def test_two_deaths_in_one_episode_are_not_one():
    """The count only ever rises, so the episode must compare against where
    it started rather than against zero."""
    env = _env_with([_alive()])
    env._client.kill_me()
    _o, _r, terminated, _t, _i = env.step(0)
    assert terminated
    env._deaths_at_step = env._death_count()
    _o, _r, terminated, _t, _i = env.step(0)
    assert not terminated, "the same death must not end the next episode too"
    env._client.kill_me("someone else")
    _o, _r, terminated, _t, info = env.step(0)
    assert terminated and info.get("died") is True


def test_a_kill_is_rewarded_once():
    """The count only rises, so a kill must be rewarded on the step it
    happens and not on every step afterwards."""
    env = _env_with([_alive()] * 6)
    env.stage = "combat"
    env._kills_seen = 0
    base, _, _, _, _ = env.step(0)
    r_before = env._reward(_alive())
    env._client._feed(_message_packet("robo was killed by a shot from bot."))
    r_kill = env._reward(_alive())
    r_after = env._reward(_alive())
    assert r_kill > r_before + 4.0, "the kill step should be worth ~5"
    assert abs(r_after - r_before) < 1e-6, "and only that step"
