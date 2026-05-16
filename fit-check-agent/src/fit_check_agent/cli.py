from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Sequence

from fit_check_agent.config import Settings
from fit_check_agent.pipeline import run_fit_check
from fit_check_agent.profiles import discover_profiles


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fit-check agent utility commands.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-profiles", help="Print available profile names.")

    run_parser = subparsers.add_parser(
        "fit-check",
        help="Run a fit check from a captured product JSON payload.",
    )
    run_parser.add_argument("--profile", required=True)
    run_parser.add_argument("--payload-file", required=True)

    args = parser.parse_args(argv)
    settings = Settings()

    if args.command == "list-profiles":
        for profile in discover_profiles(settings.profiles_dir):
            print(profile)
        return 0

    if args.command == "fit-check":
        payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
        result = asyncio.run(
            run_fit_check(
                profile_name=args.profile,
                product_payload=payload,
                settings=settings,
            )
        )
        print(json.dumps(result.__dict__, indent=2, sort_keys=True))
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
