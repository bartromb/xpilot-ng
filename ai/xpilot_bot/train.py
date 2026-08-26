"""PPO training with a curriculum, via Stable-Baselines3.

    pip install "xpilot-bot[rl]" stable-baselines3
    python -m xpilot_bot.train --steps 200000

The curriculum runs navigate, then dodge, then combat, carrying the policy
forward between stages. The roadmap's reason for staging is the usual one and
worth restating: firing is only rewarded when it connects, and it cannot
connect until the agent can already fly and aim, so an agent dropped straight
into combat has no gradient to climb and tends to settle for sitting still.

Everything here talks to real servers over the real protocol. Training is
therefore bounded by wall-clock game time, which is why the servers run
faster than realtime and in parallel; see --fps and --envs.

Run from the repository root, or pass --binary.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _lazy_imports():
    """Imported late so --help works without the RL extras installed."""
    try:
        from stable_baselines3 import PPO
        from stable_baselines3.common.monitor import Monitor
        from stable_baselines3.common.vec_env import DummyVecEnv
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Training needs stable-baselines3:\n"
            '    pip install "xpilot-bot[rl]" stable-baselines3'
        ) from exc
    return PPO, Monitor, DummyVecEnv


def build_vec_env(stage, n_envs, base_port, fps, max_steps, binary, map_file,
                  include_shots=False):
    from xpilot_bot.env import make_parallel
    _PPO, Monitor, DummyVecEnv = _lazy_imports()

    envs, servers = make_parallel(
        n_envs, base_port=base_port, fps=fps, stage=stage,
        max_steps=max_steps, binary=binary, map_file=map_file,
        include_shots=include_shots,
    )
    vec = DummyVecEnv([(lambda e=e: Monitor(e)) for e in envs])
    return vec, envs, servers


def train(args) -> int:
    PPO, _Monitor, _DummyVecEnv = _lazy_imports()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    stages = args.stages.split(",")
    per_stage = max(args.steps // len(stages), 1)
    model = None
    port = args.base_port

    for i, stage in enumerate(stages):
        print(f"\n=== stage {i + 1}/{len(stages)}: {stage} "
              f"({per_stage} steps) ===", flush=True)

        vec, envs, servers = build_vec_env(
            stage, args.envs, port, args.fps, args.max_steps,
            args.binary, args.map, include_shots=args.shots,
        )
        # Fresh ports per stage: a server from the previous stage may still be
        # shutting down, and binding over it fails intermittently.
        port += args.envs

        try:
            if model is None:
                model = PPO(
                    "MlpPolicy", vec,
                    verbose=1 if args.verbose else 0,
                    n_steps=args.rollout,
                    batch_size=args.batch,
                    learning_rate=args.lr,
                    ent_coef=args.ent_coef,
                    seed=args.seed,
                )
            else:
                # Carry the policy forward; that is what makes it a
                # curriculum rather than three unrelated training runs.
                model.set_env(vec)

            started = time.time()
            model.learn(total_timesteps=per_stage,
                        reset_num_timesteps=False,
                        progress_bar=False)
            took = time.time() - started

            path = out / f"ppo_{stage}"
            model.save(str(path))
            print(f"    {per_stage} steps in {took:.0f}s "
                  f"({per_stage / max(took, 1e-9):.0f} steps/s) -> {path}.zip",
                  flush=True)
        finally:
            vec.close()
            for s in servers:
                s.close()

    if model is not None:
        model.save(str(out / "ppo_final"))
        print(f"\nsaved {out / 'ppo_final'}.zip")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--steps", type=int, default=60_000,
                    help="total timesteps across all stages")
    ap.add_argument("--stages", default="navigate,dodge,combat",
                    help="comma-separated curriculum stages")
    ap.add_argument("--envs", type=int, default=4,
                    help="parallel environments, each with its own server")
    ap.add_argument("--fps", type=int, default=200,
                    help="server and client frame rate; 255 is the protocol "
                         "ceiling because the request is one byte")
    ap.add_argument("--max-steps", type=int, default=1500,
                    help="steps before an episode is truncated")
    ap.add_argument("--base-port", type=int, default=15500)
    ap.add_argument("--out", default="ai/checkpoints")
    ap.add_argument("--shots", action="store_true",
                    help="show the agent nearby shots. This widens the "
                         "observation, so a checkpoint trained with it can "
                         "only be evaluated with it.")
    ap.add_argument("--binary", default="./build/bin/xpilot-ng-server")
    ap.add_argument("--map", default="lib/maps/dodgers-robots.xp2")
    ap.add_argument("--rollout", type=int, default=512)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--ent-coef", type=float, default=0.01,
                    help="entropy bonus. Stable-Baselines3 defaults this to "
                         "0, which lets the policy converge on one action "
                         "and stop exploring; a previous run collapsed to "
                         "'turn right and fire' on 91%% of steps.")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    if not Path(args.binary).exists():
        print(f"server binary not found: {args.binary}\n"
              f"Build it first, or pass --binary. Run from the repo root.",
              file=sys.stderr)
        return 1

    return train(args)


if __name__ == "__main__":
    raise SystemExit(main())
