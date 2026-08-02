"""Validate and preview an authored world without deployment or persistence."""

import argparse
import sys
from pathlib import Path

from rumor_mill.worlds.authoring import WorldLoadError, load_world
from rumor_mill.worlds.continuity import validate_continuity
from rumor_mill.worlds.seeding import smoke_transcript


def preview_world(world_path: str | Path, *, seed: int = 0, days: int = 14) -> str:
    """Return a deterministic author preview after all validations pass."""

    world = load_world(world_path)
    issues = validate_continuity(world)
    if issues:
        detail = "\n".join(f"{world_path}:{issue.field}: {issue.message}" for issue in issues)
        raise ValueError(f"continuity validation failed:\n{detail}")
    return smoke_transcript(world, seed, days=days)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("world", type=Path, help="path to a versioned world JSON file")
    parser.add_argument("--seed", type=int, default=0, help="deterministic beat-selection seed")
    parser.add_argument("--days", type=int, choices=range(1, 15), default=14)
    parser.add_argument("--output", type=Path, help="write Markdown preview to this path")
    args = parser.parse_args(argv)

    try:
        transcript = preview_world(args.world, seed=args.seed, days=args.days)
    except (WorldLoadError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.output is None:
        print(transcript, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(transcript, encoding="utf-8")
        print(f"Validated {args.world}; preview written to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
