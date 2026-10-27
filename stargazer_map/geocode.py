"""Geocoding with OpenStreetMap Nominatim (1 request/second, cached on disk)."""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def normalise_location(raw: str | None) -> str | None:
    if not raw:
        return None
    text = re.sub(r"[\U00010000-\U0010FFFF]", " ", raw)  # strip emoji
    text = re.sub(r"\s+", " ", text).strip(" ,.;|-/")
    if len(text) < 2:
        return None
    return text.lower()


def load_cache(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict, path: Path) -> None:
    path.write_text(
        json.dumps(dict(sorted(cache.items())), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


_last_call = 0.0


def nominatim(query: str, user_agent: str) -> dict | None:
    global _last_call
    wait = 1.1 - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
            "accept-language": "en",
        }
    )
    req = urllib.request.Request(f"{NOMINATIM_URL}?{params}", headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            results = json.load(resp)
    finally:
        _last_call = time.monotonic()
    return parse_hit(results[0], query) if results else None


# Nominatim `addresstype`s that cover an area rather than a place: a profile that
# only says "USA" or "California" counts for its country but gets no map bubble.
AREA_LEVELS = {"continent", "country", "state"}
# Countries that are one city, where a country-level answer is the place itself.
CITY_STATES = {"SG", "HK", "MO", "MC", "VA", "SM", "GI"}
# Cities that Nominatim returns as a "state" (city-level regions). Nothing in the
# response tells them apart from real states like California, hence a list.
STATE_CITIES = {
    "Beijing", "Shanghai", "Tianjin", "Chongqing", "Mexico City", "Berlin", "Hamburg",
    "Bremen", "Vienna", "Brussels", "Moscow", "Saint Petersburg", "Seoul", "Busan",
    "Tokyo", "Delhi", "Buenos Aires", "Bogotá", "Kuala Lumpur", "Islamabad", "Canberra",
}  # fmt: skip


def parse_hit(hit: dict, query: str) -> dict:
    """Reduce one Nominatim jsonv2 result to what the cache keeps."""
    addr = hit.get("address", {})
    level = hit.get("addresstype")
    city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("municipality")
        # e.g. Changsha comes back as a "region" with no city field: use its own name
        or (hit.get("name") if level not in AREA_LEVELS else None)
        or addr.get("county")
        or addr.get("state")
    )
    country = addr.get("country")
    if city == country:  # e.g. "kenya" can match an old "Kenya" boundary: still just a country
        city = None
    label = ", ".join(p for p in (city, country) if p) or hit.get("display_name", query)
    return {
        "lat": round(float(hit["lat"]), 3),
        "lon": round(float(hit["lon"]), 3),
        "label": label,
        "country": country,
        "country_code": (addr.get("country_code") or "").upper() or None,
        "level": level,
    }


def is_place(geo: dict) -> bool:
    """Whether a cached result is precise enough for a bubble and "Top places"."""
    if geo["label"] == geo.get("country"):  # just a country (also true of old entries)
        return geo.get("country_code") in CITY_STATES
    level = geo.get("level")
    if level == "state":
        return geo["label"].split(", ")[0] in STATE_CITIES
    return level not in AREA_LEVELS


def is_country_only(geo: dict) -> bool:
    """A result that names a country and nothing smaller ("USA", "France")."""
    return geo["label"] == geo.get("country") and not is_place(geo)


def geocode_all(
    locations: set[str], cache: dict, cache_path: Path, max_new: int, user_agent: str
) -> None:
    """Geocode locations missing from the cache. A None entry means "nothing found".

    Entries cached before `level` existed are looked up again, after the new ones and
    within the same `max_new` budget.
    """
    new = sorted(loc for loc in locations if loc not in cache)
    stale = sorted(loc for loc in locations if cache.get(loc) and "level" not in cache[loc])
    todo = (new + stale)[:max_new]
    print(f"Geocoding {len(new)} new and {len(stale)} outdated locations", end="")
    print(f" ({len(todo)} this run, rest next run)" if len(todo) < len(new + stale) else "")
    for i, loc in enumerate(todo, 1):
        try:
            cache[loc] = nominatim(loc, user_agent)
        except Exception as exc:  # network hiccup: retry on the next run
            print(f"  geocode failed for {loc!r}: {exc}", file=sys.stderr)
            continue
        if i % 50 == 0:
            save_cache(cache, cache_path)
            print(f"  {i}/{len(todo)}")
    save_cache(cache, cache_path)
