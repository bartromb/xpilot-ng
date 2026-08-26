"""A Gymnasium environment wrapping the XPilot NG client.

The agent plays against an unmodified server, seeing only what a human
player's client is sent and acting only through keys a human can press. That
constraint is the point: an agent trained here is playing the real game, not a
convenient approximation of it.

    pip install "xpilot-bot[rl]"

    import gymnasium as gym
    from xpilot_bot.env import XPilotEnv

    env = XPilotEnv(host="localhost", port=15345)
    obs, info = env.reset()
    obs, reward, terminated, truncated, info = env.step(env.action_space.sample())

The server must already be running. `ServerProcess` in this module can start
one for you, including at faster than realtime.

Requires gymnasium and numpy; the rest of xpilot_bot does not.
"""

from __future__ import annotations

import math
import subprocess
import time

import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        'XPilotEnv needs gymnasium. Install with: pip install "xpilot-bot[rl]"'
    ) from exc

from .client import Client, ProtocolError
from . import protocol as p

#: Actions, as combinations of held keys. XPilot input is continuous -- keys
#: are held rather than tapped -- so each action is "the set of keys held for
#: this step" rather than an event.
ACTIONS: list[tuple[int, ...]] = [
    (),                                        # coast
    (p.KEY_THRUST,),
    (p.KEY_TURN_LEFT,),
    (p.KEY_TURN_RIGHT,),
    (p.KEY_THRUST, p.KEY_TURN_LEFT),
    (p.KEY_THRUST, p.KEY_TURN_RIGHT),
    (p.KEY_FIRE_SHOT,),
    (p.KEY_THRUST, p.KEY_FIRE_SHOT),
    (p.KEY_TURN_LEFT, p.KEY_FIRE_SHOT),
    (p.KEY_TURN_RIGHT, p.KEY_FIRE_SHOT),
    (p.KEY_SHIELD,),
]

#: How many other ships appear in the observation, nearest first.
MAX_TRACKED_SHIPS = 4

HEADING_STEPS = 128


class ServerProcess:
    """Runs a dedicated server for one environment.

    Each environment needs its own server on its own port: XPilot has no
    notion of parallel independent matches inside one process, so N parallel
    environments means N servers. They are cheap -- a headless server with a
    couple of robots is a few MB.
    """

    def __init__(
        self,
        binary: str = "./build/bin/xpilot-ng-server",
        map_file: str = "lib/maps/dodgers-robots.xp2",
        port: int = 15345,
        robots: int = 2,
        fps: int = 50,
        quiet: bool = True,
    ) -> None:
        self.port = port
        self.fps = fps
        self._proc = subprocess.Popen(
            [
                binary,
                "-map", map_file,
                "-port", str(port),
                "-maxRobots", str(robots),
                "-minRobots", str(robots),
                "-framesPerSecond", str(fps),
                # Without these the server exits when the last human leaves,
                # which for a bot-only server means immediately.
                "-noQuit", "-idleRun",
                # Nothing should phone home during training.
                "-reportToMetaServer", "false",
            ],
            stdout=subprocess.DEVNULL if quiet else None,
            stderr=subprocess.DEVNULL if quiet else None,
        )
        # Give it time to bind before anyone connects.
        time.sleep(1.5)

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def __enter__(self) -> "ServerProcess":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class XPilotEnv(gym.Env):
    """One bot in one XPilot game.

    Observation (float32), all scaled to roughly [-1, 1]:

        0     fuel / fuel_max
        1,2   own velocity
        3,4   heading as (cos, sin) -- continuous across the 127->0 wrap,
              which a raw heading number is not
        5     1 if damaged
        then, per tracked ship, nearest first:
        +0,1  relative position
        +2    distance
        +3    bearing error: where it is, relative to where we point
        +4    1 if this slot holds a real ship, 0 if padding

    The presence flag matters. Without it a padded slot of zeros is
    indistinguishable from a ship at exactly our position.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        host: str = "localhost",
        port: int = 15345,
        nick: str = "rl",
        fps: int = 50,
        max_steps: int = 2000,
        frames_per_step: int = 1,
        world_scale: float = 3000.0,
        server: ServerProcess | None = None,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.nick = nick
        self.fps = fps
        self.max_steps = max_steps
        self.frames_per_step = frames_per_step
        self.world_scale = world_scale
        self._server = server

        self.action_space = spaces.Discrete(len(ACTIONS))
        obs_len = 6 + 5 * MAX_TRACKED_SHIPS
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_len,), dtype=np.float32
        )

        self._client: Client | None = None
        self._steps = 0
        self._prev_fuel: float | None = None
        self._prev_damaged = False

    # ------------------------------------------------------------ gym API

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._close_client()

        self._client = Client(
            host=self.host, port=self.port,
            nick=self.nick, user=self.nick, fps=self.fps,
        )
        self._client.connect()
        self._steps = 0
        self._prev_fuel = None
        self._prev_damaged = False

        frame = self._await_frame()
        return self._observe(frame), {}

    def step(self, action: int):
        if self._client is None:
            raise RuntimeError("step() before reset()")

        keys = ACTIONS[int(action)]
        self._client.release_all()
        for k in keys:
            self._client.press(k)

        try:
            self._client.send_keys()
            frame = None
            for _ in range(self.frames_per_step):
                frame = self._await_frame()
        except ProtocolError:
            # Dropped mid-episode. Ending it is honest; pretending otherwise
            # would feed the agent an observation that never happened.
            obs = np.zeros(self.observation_space.shape, dtype=np.float32)
            return obs, 0.0, True, False, {"disconnected": True}

        self._steps += 1
        obs = self._observe(frame)
        reward = self._reward(frame)
        truncated = self._steps >= self.max_steps
        return obs, reward, False, truncated, {"frame": frame.loops}

    def close(self):
        self._close_client()
        if self._server is not None:
            self._server.close()
            self._server = None

    # -------------------------------------------------------------- innards

    def _close_client(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except OSError:
                pass
            self._client = None

    def _await_frame(self, timeout: float = 5.0):
        """Block until a frame with own-ship state arrives.

        Frames without a PKT_SELF happen while dead, paused or between
        lives, and carry no position to act on.
        """
        assert self._client is not None
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self._client.poll()
            if frame is not None and frame.self_ is not None:
                return frame
        raise ProtocolError("no frame from the server within the timeout")

    def _observe(self, frame) -> np.ndarray:
        me = frame.self_
        s = self.world_scale
        heading = 2 * math.pi * me.heading / HEADING_STEPS

        obs = [
            me.fuel / max(me.fuel_max, 1),
            me.vx / 50.0,
            me.vy / 50.0,
            math.cos(heading),
            math.sin(heading),
            1.0 if frame.damaged else 0.0,
        ]

        others = [sh for sh in frame.ships if (sh.x, sh.y) != (me.x, me.y)]
        others.sort(key=lambda sh: (sh.x - me.x) ** 2 + (sh.y - me.y) ** 2)

        for i in range(MAX_TRACKED_SHIPS):
            if i < len(others):
                sh = others[i]
                dx, dy = sh.x - me.x, sh.y - me.y
                dist = math.hypot(dx, dy)
                bearing = math.atan2(dy, dx)
                err = (bearing - heading + math.pi) % (2 * math.pi) - math.pi
                obs += [dx / s, dy / s, dist / s, err / math.pi, 1.0]
            else:
                obs += [0.0, 0.0, 0.0, 0.0, 0.0]

        return np.asarray(obs, dtype=np.float32)

    def _reward(self, frame) -> float:
        """A deliberately plain reward: stay alive, keep fuel, face the enemy.

        It is not a good fighting reward and is not meant to be. Phase 6c's
        curriculum is where shaping belongs; putting it here would bake one
        set of choices into the environment, where every experiment would
        inherit them.
        """
        me = frame.self_
        reward = 0.01  # being alive at all

        fuel = me.fuel / max(me.fuel_max, 1)
        if self._prev_fuel is not None:
            reward += (fuel - self._prev_fuel) * 0.5
        self._prev_fuel = fuel

        if frame.damaged and not self._prev_damaged:
            reward -= 1.0
        self._prev_damaged = frame.damaged

        others = [sh for sh in frame.ships if (sh.x, sh.y) != (me.x, me.y)]
        if others:
            nearest = min(others,
                          key=lambda sh: (sh.x - me.x) ** 2 + (sh.y - me.y) ** 2)
            heading = 2 * math.pi * me.heading / HEADING_STEPS
            bearing = math.atan2(nearest.y - me.y, nearest.x - me.x)
            err = abs((bearing - heading + math.pi) % (2 * math.pi) - math.pi)
            reward += 0.02 * (1.0 - err / math.pi)

        return float(reward)


def make_parallel(
    n: int,
    base_port: int = 15400,
    fps: int = 200,
    robots: int = 2,
    map_file: str = "lib/maps/dodgers-robots.xp2",
    binary: str = "./build/bin/xpilot-ng-server",
    **env_kwargs,
):
    """Start n independent environments, each with its own server.

    XPilot has no concept of separate matches inside one server process, so
    parallelism means one server per environment, each on its own port. They
    are cheap: a headless server with a couple of robots is a few MB and
    little CPU when nothing is happening.

    Returns (envs, servers). Close the envs; each closes its own server.

        envs, _ = make_parallel(4, fps=200)
        vec = gymnasium.vector.SyncVectorEnv([lambda e=e: e for e in envs])
    """
    envs, servers = [], []
    try:
        for i in range(n):
            port = base_port + i
            srv = ServerProcess(binary=binary, map_file=map_file, port=port,
                                robots=robots, fps=fps)
            servers.append(srv)
            envs.append(XPilotEnv(port=port, nick=f"rl{i}", fps=fps,
                                  server=srv, **env_kwargs))
        return envs, servers
    except Exception:
        for e in envs:
            e.close()
        for s in servers:
            s.close()
        raise
