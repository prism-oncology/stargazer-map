import json

from stargazer_map.geocode import normalise_location
from stargazer_map.github import parse_github_url
from stargazer_map.stats import aggregate

PARIS = {"lat": 48.857, "lon": 2.352, "label": "Paris, France", "country": "France",
         "country_code": "FR", "level": "city"}  # fmt: skip
LYON = {"lat": 45.758, "lon": 4.835, "label": "Lyon, France", "country": "France",
        "country_code": "FR", "level": "city"}  # fmt: skip
USA = {"lat": 39.784, "lon": -100.446, "label": "United States", "country": "United States",
       "country_code": "US", "level": "country"}  # fmt: skip


def test_normalise_location():
    assert normalise_location("  Paris,  France 🇫🇷 ") == "paris, france"
    assert normalise_location("🌍") is None
    assert normalise_location("") is None
    assert normalise_location(None) is None


def test_parse_github_url():
    for url in (
        "https://github.com/me/repo.git",
        "https://github.com/me/repo",
        "git@github.com:me/repo.git\n",
    ):
        assert parse_github_url(url) == "me/repo"
    assert parse_github_url("https://gitlab.com/me/repo") is None


def test_aggregate():
    cache = {"paris": PARIS, "lyon": LYON, "nowhere": None}
    users = {"a": "paris", "b": "paris", "c": "lyon", "d": "nowhere", "e": None}
    stats = aggregate(users, cache)
    assert stats["stargazers"] == 5
    assert stats["with_location"] == 4
    assert stats["located"] == 3
    assert [(p["label"], p["count"]) for p in stats["places"]] == [
        ("Paris, France", 2),
        ("Lyon, France", 1),
    ]
    assert stats["countries"] == [{"code": "FR", "name": "France", "count": 3}]
    assert "logins" not in stats["places"][0]


def test_aggregate_logins():
    stats = aggregate({"a": "paris", "b": "paris"}, {"paris": PARIS}, include_logins=True)
    assert stats["places"][0]["logins"] == ["a", "b"]


def test_fetch(tmp_path, monkeypatch):
    from stargazer_map import geocode, github, stats

    repos = [
        {"name": "tool", "url": "u1", "description": "d", "stargazerCount": 3,
         "isFork": False, "isArchived": False, "primaryLanguage": {"name": "Python"}},
        {"name": "secret", "url": "u2", "description": None, "stargazerCount": 1,
         "isFork": False, "isArchived": True, "primaryLanguage": None},
        {"name": "empty", "url": "u3", "description": None, "stargazerCount": 0,
         "isFork": False, "isArchived": False, "primaryLanguage": None},
    ]  # fmt: skip
    stargazers = {
        "tool": [
            {"login": "a", "location": "Paris"},
            {"login": "b", "location": "Lyon 🦁"},
            {"login": "c", "location": None},
        ]
    }

    def list_stargazers(owner, repo):
        if repo not in stargazers:
            raise PermissionError("FORBIDDEN")
        return stargazers[repo]

    lookups = []

    def nominatim(query, user_agent):
        lookups.append(query)
        return {"paris": PARIS, "lyon": LYON}[query]

    monkeypatch.setattr(github, "list_repos", lambda *a: repos)
    monkeypatch.setattr(github, "list_stargazers", list_stargazers)
    monkeypatch.setattr(geocode, "nominatim", nominatim)

    data = tmp_path / "data"
    (data / "stats").mkdir(parents=True)
    # Previous stats for an unreadable repo are kept; stats for deleted repos are dropped.
    old = {"stargazers": 1, "located": 1, "places": [], "countries": [],
           "generated_at": "2026-01-01T00:00:00+00:00"}  # fmt: skip
    (data / "stats" / "secret.json").write_text(json.dumps(old))
    (data / "stats" / "gone.json").write_text("{}")

    summary = stats.fetch("me", data, repository="me/stargazer-map")

    assert sorted(lookups) == ["lyon", "paris"]
    assert summary["repository"] == "me/stargazer-map"
    assert summary["overall"] == {"stargazers": 3, "with_location": 2, "located": 2,
                                  "countries": 1}  # fmt: skip
    files = sorted(p.name for p in (data / "stats").iterdir())
    assert files == ["_all.json", "empty.json", "secret.json", "tool.json"]
    secret = json.loads((data / "stats" / "secret.json").read_text())
    assert secret["error"] and secret["stale_since"] == old["generated_at"]
    assert json.loads((data / "geocode-cache.json").read_text()) == {"lyon": LYON, "paris": PARIS}

    # Second run: everything is cached, nothing is geocoded again.
    lookups.clear()
    stats.fetch("me", data)
    assert lookups == []


def test_fetch_fails_when_token_cannot_read_any_repo(tmp_path, monkeypatch):
    import pytest

    from stargazer_map import github, stats

    repos = [
        {"name": n, "url": "u", "description": None, "stargazerCount": c,
         "isFork": False, "isArchived": False, "primaryLanguage": None}
        for n, c in (("starred", 2), ("empty", 0))
    ]  # fmt: skip

    def refuse(owner, repo):
        raise PermissionError("Resource not accessible by personal access token")

    monkeypatch.setattr(github, "list_repos", lambda *a: repos)
    monkeypatch.setattr(github, "list_stargazers", refuse)
    with pytest.raises(RuntimeError, match="Resource not accessible"):
        stats.fetch("me", tmp_path / "data")
    assert not (tmp_path / "data" / "summary.json").exists()


def test_aggregate_country_and_state_only_locations():
    california = {"lat": 36.7, "lon": -118.8, "label": "California, United States",
                  "country": "United States", "country_code": "US", "level": "state"}  # fmt: skip
    singapore = {"lat": 1.357, "lon": 103.819, "label": "Singapore", "country": "Singapore",
                 "country_code": "SG", "level": "country"}  # fmt: skip
    shanghai = {"lat": 31.23, "lon": 121.47, "label": "Shanghai, China", "country": "China",
                "country_code": "CN", "level": "state"}  # fmt: skip
    cache = {"usa": USA, "california": california, "singapore": singapore, "paris": PARIS,
             "shanghai": shanghai}  # fmt: skip
    users = {"a": "usa", "b": "california", "c": "singapore", "d": "paris", "e": "shanghai"}
    stats = aggregate(users, cache)
    # Everyone is located and counted for their country...
    assert stats["located"] == 5
    assert {c["code"]: c["count"] for c in stats["countries"]} == {
        "US": 2, "SG": 1, "FR": 1, "CN": 1}  # fmt: skip
    # ...a city-state and a city Nominatim calls a state are places, a bare country gets
    # a bubble at its centre, and a state gets none.
    assert {p["label"]: p.get("country_only", False) for p in stats["places"]} == {
        "Paris, France": False, "Shanghai, China": False, "Singapore": False,
        "United States": True}  # fmt: skip
    usa = next(p for p in stats["places"] if p["label"] == "United States")
    assert (usa["lat"], usa["lon"]) == (USA["lat"], USA["lon"])


def test_aggregate_legacy_cache_entries():
    legacy_usa = {k: v for k, v in USA.items() if k != "level"}
    legacy_paris = {k: v for k, v in PARIS.items() if k != "level"}
    stats = aggregate({"a": "usa", "b": "paris"}, {"usa": legacy_usa, "paris": legacy_paris})
    assert [(p["label"], p.get("country_only")) for p in stats["places"]] == [
        ("United States", True), ("Paris, France", None)]  # fmt: skip


def test_aggregate_merges_places_with_the_same_label():
    sf = {"lat": 37.788, "lon": -122.408, "label": "San Francisco, United States",
          "country": "United States", "country_code": "US", "level": "city"}  # fmt: skip
    bay_area = sf | {"lon": -122.356, "level": "region"}
    cache = {"san francisco": sf, "sf": sf, "bay area": bay_area}
    stats = aggregate({"a": "san francisco", "b": "sf", "c": "bay area"}, cache)
    assert stats["places"] == [
        {
            "lat": 37.788,
            "lon": -122.408,
            "label": "San Francisco, United States",
            "country": "US",
            "count": 3,
        }  # fmt: skip
    ]


def test_parse_hit():
    from stargazer_map.geocode import parse_hit

    changsha = {"lat": "28.1", "lon": "113.2", "addresstype": "region", "name": "Changsha",
                "address": {"state": "Hunan", "country": "China",
                            "country_code": "cn"}}  # fmt: skip
    assert parse_hit(changsha, "changsha")["label"] == "Changsha, China"
    usa = {"lat": "39.78", "lon": "-100.45", "addresstype": "country", "name": "United States",
           "address": {"country": "United States", "country_code": "us"}}  # fmt: skip
    kenya = {"lat": "0.1", "lon": "37.9", "addresstype": "historic:administrative",
             "name": "Kenya", "address": {"country": "Kenya", "country_code": "ke"}}  # fmt: skip
    assert parse_hit(kenya, "kenya")["label"] == "Kenya"
    assert parse_hit(usa, "usa") == {
        "lat": 39.78, "lon": -100.45, "label": "United States", "country": "United States",
        "country_code": "US", "level": "country",
    }  # fmt: skip


def test_geocode_all_refreshes_entries_without_level(tmp_path, monkeypatch):
    from stargazer_map import geocode

    legacy = {k: v for k, v in PARIS.items() if k != "level"}
    cache = {"paris": legacy, "nowhere": None}
    lookups = []

    def nominatim(query, user_agent):
        lookups.append(query)
        return {"paris": PARIS, "lyon": LYON}[query]

    monkeypatch.setattr(geocode, "nominatim", nominatim)
    geocode.geocode_all({"paris", "lyon", "nowhere"}, cache, tmp_path / "c.json", 10, "ua")
    assert lookups == ["lyon", "paris"]  # new first, then outdated; "nothing found" kept
    assert cache == {"paris": PARIS, "lyon": LYON, "nowhere": None}
