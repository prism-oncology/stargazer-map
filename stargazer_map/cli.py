"""Command line: `stargazer-map fetch` then `stargazer-map build`.

Options default to environment variables (ORG, INCLUDE_FORKS, INCLUDE_ARCHIVED,
INCLUDE_LOGINS, MAX_GEOCODE, MAP_LAYERS, MIN_STARS, LOGO) so the GitHub workflow can
configure them in `env:`.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__, github
from .site import LAYERS, build
from .stats import fetch


def env_flag(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes"}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="stargazer-map", description="Map where your GitHub stargazers are."
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="fetch stargazers, geocode them and write the data dir")
    f.add_argument(
        "--org",
        default=os.environ.get("ORG"),
        help="GitHub user or organisation (default: $ORG, else the owner of this git repo)",
    )
    f.add_argument("--data", default="data", help="data directory (default: data)")
    f.add_argument(
        "--include-forks",
        action=argparse.BooleanOptionalAction,
        default=env_flag("INCLUDE_FORKS", False),
    )
    f.add_argument(
        "--include-archived",
        action=argparse.BooleanOptionalAction,
        default=env_flag("INCLUDE_ARCHIVED", True),
    )
    f.add_argument(
        "--include-logins",
        action=argparse.BooleanOptionalAction,
        default=env_flag("INCLUDE_LOGINS", False),
        help="publish stargazer logins in the JSON and map popups",
    )
    f.add_argument(
        "--max-geocode",
        type=int,
        default=int(os.environ.get("MAX_GEOCODE", "800")),
        help="new locations to geocode per run (default: 800)",
    )

    b = sub.add_parser("build", help="render the static site from the data dir")
    b.add_argument("--data", default="data", help="data directory (default: data)")
    b.add_argument("--site", default="site", help="output directory (default: site)")
    b.add_argument(
        "--layers",
        default=os.environ.get("MAP_LAYERS", ",".join(LAYERS)),
        help=(
            "comma-separated map layers shown by default, from: "
            f"{', '.join(LAYERS)} (default: all; viewers can toggle each)"
        ),
    )
    b.add_argument(
        "--min-stars",
        type=int,
        default=int(os.environ.get("MIN_STARS") or 0),
        help="only list repos with at least this many stars (default: 0, all repos)",
    )
    b.add_argument(
        "--logo",
        default=os.environ.get("LOGO") or None,
        help=(
            "image (svg/png/jpg/webp) shown at the top of every page "
            "(default: the owner's GitHub avatar)"
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "build":
        layers = [x.strip() for x in args.layers.split(",") if x.strip()]
        try:
            build(args.data, args.site, layers, args.min_stars, args.logo)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        return 0

    repository = github.current_repository()
    # Defaults to the owner of this repo, so a fork maps its own stars.
    org = args.org or (repository.split("/")[0] if repository else None)
    if not org:
        print("Pass --org (or set ORG) to the user or organisation to map.", file=sys.stderr)
        return 2
    try:
        fetch(
            org,
            args.data,
            repository=repository,
            include_forks=args.include_forks,
            include_archived=args.include_archived,
            include_logins=args.include_logins,
            max_geocode=args.max_geocode,
        )
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0
