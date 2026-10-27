"""Render <data_dir>/summary.json + stats/*.json into a static site:

index.html          overview: org-wide map + one card per repo
<repo>.html         one map page per repository
data/*.json         the aggregated stats (handy for other tools)
assets/             style.css, theme.js, logo.js, map.js, countries.geojson
                    (copied from stargazer_map/assets/)
"""

from __future__ import annotations

import html
import json
import shutil
import urllib.parse
from collections.abc import Iterable
from importlib import resources
from pathlib import Path

LEAFLET = "https://unpkg.com/leaflet@1.9.4/dist"
ASSETS = ("style.css", "theme.js", "logo.js", "map.js", "countries.geojson")
LOGO_TYPES = (".svg", ".png", ".jpg", ".jpeg", ".webp")
# Map layers a viewer can toggle: countries coloured by stargazer count, and one
# bubble per place sized by count.
LAYERS = ("countries", "bubbles")
# Applies the visitor's saved light/dark choice before first paint (see theme.js).
THEME_INIT = (
    "<script>try{var t=localStorage.getItem('stargazer-map:theme');"
    "if(t==='light'||t==='dark')document.documentElement.dataset.theme=t}catch(e){}</script>"
)


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else "–"


def page(
    title: str,
    crumb: str,
    heading: str,
    sub: str,
    body: str,
    map_data: dict | None,
    repository: str,
    generated: str,
    logo: str = "",
) -> str:
    crumb = f'<div class="crumb">{crumb}</div>' if crumb else ""
    map_block = ""
    if map_data is not None:
        data = json.dumps(map_data, ensure_ascii=False).replace("</", "<\\/")
        map_block = (
            f'<script id="map-data" type="application/json">{data}</script>'
            f'<script src="{LEAFLET}/leaflet.js"></script>'
            '<script src="assets/map.js"></script>'
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<link rel="stylesheet" href="{LEAFLET}/leaflet.css">
<link rel="stylesheet" href="assets/style.css">
{THEME_INIT}</head>
<body>
<header><button id="theme-toggle" class="theme-toggle" type="button"></button>{logo}
{crumb}<h1>{heading}</h1><p class="sub">{sub}</p></header>
<main>{body}</main>
<footer>Updated {esc(generated[:16].replace("T", " "))} UTC ·
Locations are self-reported on GitHub profiles, geocoded with
<a href="https://nominatim.openstreetmap.org/">OpenStreetMap Nominatim</a> ·
<a href="https://github.com/{esc(repository)}">source</a></footer>
<script src="assets/theme.js"></script>
<script src="assets/logo.js"></script>
{map_block}
</body></html>
"""


def kpis(stats: dict, star_count=None) -> str:
    stargazers = stats.get("stargazers")
    located = stats.get("located")
    # Share of stargazers whose profile location could be placed on the map.
    pct = f" ({round(100 * located / stargazers)}%)" if stargazers and located is not None else ""
    items = []
    if star_count is not None:
        items.append((fmt(star_count), "stars"))
    items += [
        (fmt(stargazers), "stargazers read" if star_count is not None else "unique stargazers"),
        (fmt(located), f"stargazers located{pct}"),
        (fmt(len(stats.get("countries") or [])), "countries"),
    ]
    return (
        '<div class="kpis">'
        + "".join(f'<div class="kpi"><b>{v}</b><span>{k}</span></div>' for v, k in items)
        + "</div>"
    )


def ranking_table(rows: list[dict], label_key: str, scale: str, limit: int = 15) -> str:
    """Top-N table with bars. map.js colours each bar from `data-n` on the `scale`
    ramp ("countries": the map's blue, "places": the bubbles' orange)."""
    if not rows:
        return '<p class="sub">No located stargazers yet.</p>'
    top = rows[:limit]
    peak = max(r["count"] for r in top)
    trs = "".join(
        f'<tr><td>{esc(r[label_key])}</td><td class="n">{r["count"]}</td>'
        f'<td class="bar"><i data-n="{r["count"]}" '
        f'style="width:{max(4, 100 * r["count"] / peak):.0f}%"></i></td></tr>'
        for r in top
    )
    return f'<table data-scale="{scale}">{trs}</table>'


def map_and_rankings(stats: dict) -> str:
    countries = ranking_table(stats.get("countries") or [], "name", "countries")
    # A whole-country bubble ("France") is no place to rank.
    places = [p for p in stats.get("places") or [] if not p.get("country_only")]
    places = ranking_table(places, "label", "places")
    return (
        '<div id="map"></div><div class="cols">'
        f"<section><h2>Top countries</h2>{countries}</section>"
        f"<section><h2>Top places</h2>{places}</section></div>"
    )


def detail_body(stats: dict, star_count=None) -> str:
    warn = ""
    if stats.get("error"):
        warn = f'<p class="warn">⚠ {esc(stats["error"])}'
        if stats.get("stale_since"):
            warn += f" Showing data from {esc(stats['stale_since'][:10])}."
        warn += "</p>"
    return warn + kpis(stats, star_count) + map_and_rankings(stats)


def map_data(stats: dict, layers: list[str]) -> dict:
    """What map.js draws: bubbles, country counts, and the layers shown by default."""
    return {
        "places": stats.get("places") or [],
        "countries": {c["code"]: c["count"] for c in stats.get("countries") or []},
        "layers": layers,
    }


def build(
    data_dir: Path | str = "data",
    site_dir: Path | str = "site",
    layers: Iterable[str] = LAYERS,
    min_stars: int = 0,
    logo: Path | str | None = None,
) -> Path:
    """Regenerate `site_dir` from scratch and return its path.

    `layers` are the map layers shown when a page opens (any of LAYERS); viewers can
    toggle each one on the map. Repos with fewer than `min_stars` stars get no page
    or card; their stargazers still count on the overview map. The top of every page
    shows the owner's GitHub avatar, or `logo` (an image file) instead.
    """
    data_dir, site_dir = Path(data_dir), Path(site_dir)
    layers = list(dict.fromkeys(layers))
    if not layers or not set(layers) <= set(LAYERS):
        raise ValueError(f"layers must be one or more of {', '.join(LAYERS)}, got {layers}")
    summary = json.loads((data_dir / "summary.json").read_text(encoding="utf-8"))
    org, generated = summary["org"], summary["generated_at"]
    repos = [r for r in summary["repos"] if (r.get("star_count") or 0) >= min_stars]
    repository = summary.get("repository") or org
    if logo:
        logo = Path(logo)
        if logo.suffix.lower() not in LOGO_TYPES or not logo.is_file():
            raise ValueError(f"logo must be an existing {'/'.join(LOGO_TYPES)} file, got {logo}")

    if site_dir.exists():
        shutil.rmtree(site_dir)
    (site_dir / "data").mkdir(parents=True)
    (site_dir / "assets").mkdir()
    assets = resources.files("stargazer_map") / "assets"
    for name in ASSETS:
        (site_dir / "assets" / name).write_bytes((assets / name).read_bytes())
    for f in (data_dir / "stats").glob("*.json"):
        shutil.copy(f, site_dir / "data" / f.name)
    shutil.copy(data_dir / "summary.json", site_dir / "data" / "summary.json")
    if logo:
        name = f"logo{logo.suffix.lower()}"
        shutil.copy(logo, site_dir / "assets" / name)
        logo_html = f'<img class="logo" src="assets/{name}" alt="{esc(org)}">'
    else:
        # Loaded by the browser, like the map tiles, so the build stays offline. This
        # host (unlike github.com/<org>.png, a redirect) sends CORS headers, which
        # logo.js needs to crop the avatar's blank margins.
        avatar = f"https://avatars.githubusercontent.com/{urllib.parse.quote(org)}?s=400"
        logo_html = (
            f'<img class="logo avatar" src="{esc(avatar)}" alt="{esc(org)}"'
            ' crossorigin="anonymous">'
        )
    # The logo links to the owner on GitHub, so the index needs no crumb for it.
    logo_html = f'<a class="logo-link" href="https://github.com/{esc(org)}">{logo_html}</a>'

    # Per-repo pages
    for r in repos:
        stats_file = data_dir / "stats" / f"{r['repo']}.json"
        stats = json.loads(stats_file.read_text(encoding="utf-8"))
        crumb = f'<a href="index.html">{esc(org)}</a> / {esc(r["repo"])}'
        heading = f'<a href="{esc(r["url"])}" style="color:inherit">{esc(r["repo"])}</a>'
        if r.get("archived"):
            heading += '<span class="badge">archived</span>'
        (site_dir / f"{r['repo']}.html").write_text(
            page(
                f"{r['repo']} stargazers",
                crumb,
                heading,
                esc(r.get("description") or "Where this repository's stargazers are."),
                detail_body(stats, r.get("star_count")),
                map_data(stats, layers),
                repository,
                generated,
                logo_html,
            ),
            encoding="utf-8",
        )

    # Index page
    overall = json.loads((data_dir / "stats" / "_all.json").read_text(encoding="utf-8"))
    cards = []
    for r in sorted(repos, key=lambda r: -(r.get("star_count") or 0)):
        meta = f"★ {fmt(r.get('star_count'))}"
        if r.get("located") is not None:
            meta += f" · {fmt(r['located'])} mapped · {fmt(r.get('countries'))} countries"
        lang = f'<span class="badge">{esc(r["language"])}</span>' if r.get("language") else ""
        err = '<div class="warn">⚠ data unavailable</div>' if r.get("error") else ""
        cards.append(
            f'<a class="card" href="{esc(r["repo"])}.html"><h3>{esc(r["repo"])}{lang}</h3>'
            f'<p>{esc(r.get("description") or "")}</p><div class="meta">{meta}</div>{err}</a>'
        )
    body = (
        kpis(overall)
        + map_and_rankings(overall)
        + '<h2 style="margin-top:32px">Repositories</h2>'
        + f'<div class="grid">{"".join(cards)}</div>'
    )
    (site_dir / "index.html").write_text(
        page(
            f"{org} star maps",
            "",
            f"Where {esc('PRISM Institute' if org == 'prism-oncology' else org)} stargazers are",
            "One map per repository, rebuilt weekly from public GitHub profile locations.",
            body,
            map_data(overall, layers),
            repository,
            generated,
            logo_html,
        ),
        encoding="utf-8",
    )
    (site_dir / ".nojekyll").write_text("")
    print(f"Built {len(repos) + 1} pages in {site_dir}")
    return site_dir
