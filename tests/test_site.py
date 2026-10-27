import json
import re

import pytest

from stargazer_map.site import build


def write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def make_data(tmp_path):
    data = tmp_path / "data"
    (data / "stats").mkdir(parents=True)
    write(
        data / "summary.json",
        {
            "org": "me",
            "repository": "me/stargazer-map",
            "generated_at": "2026-10-09T00:00:00+00:00",
            "repos": [
                {
                    "repo": "tool",
                    "url": "https://github.com/me/tool",
                    "description": "A tool",
                    "language": "Python",
                    "archived": False,
                    "star_count": 2,
                    "stargazers": 2,
                    "located": 1,
                    "error": None,
                    "countries": 1,
                },
            ],
        },
    )
    stats = {
        "stargazers": 2,
        "located": 1,
        "places": [{"lat": 1, "lon": 2, "label": "Evil </script>", "count": 1}],
        "countries": [{"code": "FR", "name": "France", "count": 1}],
    }
    write(data / "stats" / "_all.json", stats)
    stats["history"] = [["2026-09", 1], ["2026-10", 2]]
    write(data / "stats" / "tool.json", stats)
    return data


def embedded_map_data(page):
    match = re.search(r'<script id="map-data" type="application/json">(.*?)</script>', page)
    return json.loads(match.group(1))


def test_build(tmp_path):
    site = build(make_data(tmp_path), tmp_path / "site")

    files = {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}
    assert {"index.html", "tool.html", ".nojekyll", "assets/style.css", "assets/map.js",
            "assets/theme.js",
            "assets/countries.geojson",
            "data/summary.json", "data/tool.json", "data/_all.json"} <= files  # fmt: skip
    index = (site / "index.html").read_text(encoding="utf-8")
    assert 'href="https://github.com/me/stargazer-map">source' in index
    assert 'href="tool.html"' in index
    # 1 of 2 stargazers has a location on the map.
    assert "<b>1</b><span>stargazers located (50%)</span>" in index
    assert 'id="theme-toggle"' in index and "stargazer-map:theme" in index
    # Bars carry their value for map.js to colour (countries: map blue, places: orange).
    assert '<table data-scale="countries">' in index and '<table data-scale="places">' in index
    assert '<i data-n="1" style="width:100%">' in index
    # A place label must not be able to close the embedded JSON script.
    tool = (site / "tool.html").read_text(encoding="utf-8")
    assert "Evil <\\/script>" in tool
    assert embedded_map_data(tool) == {
        "places": [{"lat": 1, "lon": 2, "label": "Evil </script>", "count": 1}],
        "countries": {"FR": 1},
        "layers": ["countries", "bubbles"],
    }
    countries = json.loads((site / "assets" / "countries.geojson").read_text(encoding="utf-8"))
    assert {"FR", "SG", "BH"} <= {f["id"] for f in countries["features"]}
    # Repo pages chart their stars over time; the overview doesn't.
    assert "<h2>Stars over time</h2>" in tool and "<title>Oct 2026: 2 stars</title>" in tool
    assert "Stars over time" not in index
    # Every page has the sidebar, with this page marked.
    assert '<a href="tool.html" class="active" aria-current="page">tool' in tool
    assert '<a href="docs/how-it-works.html">How it works</a>' in index


def test_build_docs(tmp_path):
    site = build(make_data(tmp_path), tmp_path / "site", min_stars=1)
    doc = (site / "docs" / "how-it-works.html").read_text(encoding="utf-8")
    # One level down: site links climb back to the root.
    assert 'href="../assets/style.css"' in doc and 'href="../tool.html"' in doc
    assert 'id="map-data"' not in doc
    # Template values are filled in, and the page's sections are listed under its entry.
    assert 'href="https://github.com/me">me</a>' in doc and "fewer than 1 stars" in doc
    assert "$" not in doc.split("<main>")[1]
    assert '<li><a href="#privacy">Privacy</a></li>' in doc


def test_build_layers(tmp_path):
    data = make_data(tmp_path)
    site = build(data, tmp_path / "site", layers=["bubbles"])
    index = (site / "index.html").read_text(encoding="utf-8")
    assert embedded_map_data(index)["layers"] == ["bubbles"]
    for bad in ([], ["heat"]):
        with pytest.raises(ValueError):
            build(data, tmp_path / "site", layers=bad)


def test_build_min_stars(tmp_path):
    data = make_data(tmp_path)  # one repo, "tool", with 2 stars
    site = build(data, tmp_path / "site", min_stars=3)
    assert not (site / "tool.html").exists()
    index = (site / "index.html").read_text(encoding="utf-8")
    assert 'href="tool.html"' not in index
    # The overview map still counts the hidden repo's stargazers.
    assert embedded_map_data(index)["countries"] == {"FR": 1}
    assert (build(data, tmp_path / "site", min_stars=2) / "tool.html").exists()


def test_build_logo(tmp_path):
    data = make_data(tmp_path)
    logo = tmp_path / "Brand.PNG"
    logo.write_bytes(b"\x89PNG fake")
    site = build(data, tmp_path / "site", logo=logo)
    assert (site / "assets" / "logo.png").read_bytes() == b"\x89PNG fake"
    for page in ("index.html", "tool.html"):
        html = (site / page).read_text(encoding="utf-8")
        assert '<img class="logo" src="assets/logo.png" alt="me">' in html
    # Without one, every page shows the owner's GitHub avatar.
    avatar = (
        '<img class="logo avatar" src="https://avatars.githubusercontent.com/me?s=400" alt="me"'
        ' crossorigin="anonymous">'
    )
    for page in ("index.html", "tool.html"):
        html = (build(data, tmp_path / "site") / page).read_text(encoding="utf-8")
        # ...linking to the owner on GitHub.
        assert f'<a class="logo-link" href="https://github.com/me">{avatar}</a>' in html
    for bad in (tmp_path / "missing.png", data / "summary.json"):
        with pytest.raises(ValueError):
            build(data, tmp_path / "site", logo=bad)


def test_country_only_bubble_is_not_a_top_place(tmp_path):
    data = make_data(tmp_path)
    france = {"lat": 46.603, "lon": 1.888, "label": "France", "country": "FR", "count": 3,
              "country_only": True}  # fmt: skip
    stats = json.loads((data / "stats" / "tool.json").read_text(encoding="utf-8"))
    stats["places"].insert(0, france)
    write(data / "stats" / "tool.json", stats)
    tool = (build(data, tmp_path / "site") / "tool.html").read_text(encoding="utf-8")
    assert france in embedded_map_data(tool)["places"]  # drawn on the map...
    places = tool.split('<table data-scale="places">')[1].split("</table>")[0]
    assert "<td>France</td>" not in places  # ...but not ranked
