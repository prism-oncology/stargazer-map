"""Fetch stargazers of every public repo of a GitHub owner, geocode their profile
locations and write aggregated per-repo stats to <data_dir>/stats/."""

from __future__ import annotations

import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

from . import geocode, github

SUMMARY_REPO_KEYS = (
    "repo", "url", "description", "language", "archived",
    "star_count", "stargazers", "located", "error",
)  # fmt: skip
AGGREGATE_KEYS = ("stargazers", "with_location", "located", "places", "countries")


def aggregate(users: dict[str, str | None], cache: dict, include_logins: bool = False) -> dict:
    """users: login -> normalised location (or None).

    Places are grouped by label, so spellings that geocode to the same city a few
    hundred metres apart ("San Francisco", "Bay Area") make one bubble, drawn at the
    most common of their coordinates. Country- or state-only locations count toward
    `located` and `countries` but are not places.
    """
    places: dict[str, dict] = {}
    countries: Counter = Counter()
    country_names: dict[str, str] = {}
    with_location = located = 0
    for login, loc in sorted(users.items()):
        if loc:
            with_location += 1
        geo = cache.get(loc) if loc else None
        if not geo:
            continue
        located += 1
        if geo.get("country_code"):
            countries[geo["country_code"]] += 1
            country_names[geo["country_code"]] = geo.get("country") or geo["country_code"]
        if not geocode.is_place(geo):
            continue
        place = places.setdefault(
            geo["label"],
            {
                "label": geo["label"],
                "country": geo.get("country_code"),
                "count": 0,
                "at": Counter(),
            },
        )
        place["count"] += 1
        place["at"][(geo["lat"], geo["lon"])] += 1
        if include_logins:
            place.setdefault("logins", []).append(login)
    rows = []
    for place in sorted(places.values(), key=lambda p: -p["count"]):
        (lat, lon), _ = place.pop("at").most_common(1)[0]
        rows.append({"lat": lat, "lon": lon} | place)
    return {
        "stargazers": len(users),
        "with_location": with_location,
        "located": located,
        "places": rows,
        "countries": [
            {"code": c, "name": country_names[c], "count": n} for c, n in countries.most_common()
        ],
    }


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def fetch(
    org: str,
    data_dir: Path | str = "data",
    *,
    repository: str | None = None,
    include_forks: bool = False,
    include_archived: bool = True,
    include_logins: bool = False,
    max_geocode: int = 800,
) -> dict:
    """Refresh <data_dir> for `org` and return the summary.

    `repository` (owner/name of this tool's repo) is used for the Nominatim user agent
    and the site's "source" link.
    """
    data_dir = Path(data_dir)
    stats_dir = data_dir / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    cache_path = data_dir / "geocode-cache.json"
    user_agent = f"stargazer-map/1.0 (https://github.com/{repository or org})"
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

    repos = github.list_repos(org, include_forks, include_archived)
    print(f"{len(repos)} repos in {org}")

    per_repo_users: dict[str, dict[str, str | None]] = {}
    errors: dict[str, str] = {}
    for r in repos:
        if r["stargazerCount"] == 0:
            per_repo_users[r["name"]] = {}
            continue
        print(f"- {r['name']} ({r['stargazerCount']} stars)")
        try:
            nodes = github.list_stargazers(org, r["name"])
        except PermissionError as exc:
            errors[r["name"]] = f"GitHub refused to list stargazers: {str(exc)[:200]}"
            print(f"  skipped: {exc}", file=sys.stderr)
            continue
        per_repo_users[r["name"]] = {
            n["login"]: geocode.normalise_location(n.get("location")) for n in nodes
        }

    starred = [r["name"] for r in repos if r["stargazerCount"] > 0]
    if starred and all(name in errors for name in starred):
        # Every refusal is then a token problem, not a per-repo one.
        raise RuntimeError(
            "The token could not list stargazers for any repository. It must belong to an "
            f"admin or collaborator of {org}'s repositories (see README > Token).\n"
            f"GitHub said: {errors[starred[0]]}"
        )

    cache = geocode.load_cache(cache_path)
    all_locations = {loc for users in per_repo_users.values() for loc in users.values() if loc}
    geocode.geocode_all(all_locations, cache, cache_path, max_geocode, user_agent)

    summary = {"org": org, "repository": repository, "generated_at": now, "repos": []}
    union: dict[str, str | None] = {}
    for r in repos:
        name = r["name"]
        users = per_repo_users.get(name)
        stats = {
            "repo": name,
            "url": r["url"],
            "description": r.get("description"),
            "language": (r.get("primaryLanguage") or {}).get("name"),
            "archived": r["isArchived"],
            "star_count": r["stargazerCount"],
            "generated_at": now,
            "error": errors.get(name),
        }
        if users is not None:
            stats.update(aggregate(users, cache, include_logins))
            union.update(users)
        else:
            # Keep the previous map if this run could not read the repo.
            previous = stats_dir / f"{name}.json"
            if previous.exists():
                old = json.loads(previous.read_text(encoding="utf-8"))
                for key in AGGREGATE_KEYS:
                    stats[key] = old.get(key)
                stats["stale_since"] = old.get("stale_since") or old.get("generated_at")
        write_json(stats_dir / f"{name}.json", stats)
        summary["repos"].append(
            {k: stats.get(k) for k in SUMMARY_REPO_KEYS}
            | {"countries": len(stats.get("countries") or [])}
        )

    overall = {
        "repo": "_all",
        "url": f"https://github.com/{org}",
        "description": f"Unique stargazers across all {org} repositories",
        "generated_at": now,
    } | aggregate(union, cache, include_logins)
    write_json(stats_dir / "_all.json", overall)
    summary["overall"] = {k: overall[k] for k in ("stargazers", "with_location", "located")} | {
        "countries": len(overall["countries"])
    }
    write_json(data_dir / "summary.json", summary)

    # Drop stats for repos that disappeared.
    keep = {f"{r['name']}.json" for r in repos} | {"_all.json"}
    for f in stats_dir.glob("*.json"):
        if f.name not in keep:
            f.unlink()

    print(
        f"Done: {overall['stargazers']} unique stargazers, "
        f"{overall['located']} located in {len(overall['countries'])} countries"
    )
    return summary
