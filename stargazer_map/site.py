"""Render <data_dir>/summary.json + stats/*.json into a static site:

index.html          overview: org-wide map + one card per repo
<repo>.html         one map page per repository
docs/<slug>.html    documentation (from the stargazer_map/docs/ fragments)
data/*.json         the aggregated stats (handy for other tools)
assets/             style.css, theme.js, logo.js, map.js, countries.geojson
                    (copied from stargazer_map/assets/)

Every page has the same frame: a top bar (logo, site name, source link, theme
toggle) and a left sidebar listing the maps and the docs, a drawer on phones.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import string
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
# Documentation pages: stargazer_map/docs/<slug>.html fragments, in sidebar order.
# They are string.Template text: $org, $repository and $min_stars_note are filled in.
DOCS = (
    ("reading-the-maps", "Reading the maps"),
    ("how-it-works", "How it works"),
    ("make-your-own", "Make your own"),
    ("data", "Data files"),
)
MENU_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"'
    ' stroke-linecap="round" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18"/></svg>'
)
GITHUB_ICON = (
    '<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3'
    ".58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.5"
    "3-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.7"
    "2 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82"
    "-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .2"
    "7 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.7"
    "5-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 "
    '0016 8c0-4.42-3.58-8-8-8z"/></svg>'
)
# Applies the visitor's saved light/dark choice before first paint (see theme.js).
THEME_INIT = (
    "<script>try{var t=localStorage.getItem('stargazer-map:theme');"
    "if(t==='light'||t==='dark')document.documentElement.dataset.theme=t}catch(e){}</script>"
)


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else "–"


def sidebar(org: str, repos: list[dict], current: str, root: str, sections=()) -> str:
    """Left navigation. `current` is the href of this page (relative to the site root);
    `sections` are this page's (id, title) headings, listed under its entry."""

    def link(href, label, extra=""):
        active = href == current
        cls = ' class="active" aria-current="page"' if active else ""
        sub = ""
        if active and sections:
            sub = "<ul>" + "".join(f'<li><a href="#{esc(i)}">{t}</a></li>' for i, t in sections)
            sub += "</ul>"
        return f'<li><a href="{root}{esc(href)}"{cls}>{label}{extra}</a>{sub}</li>'

    maps = link("index.html", "All repositories")
    maps += "".join(
        link(
            f"{r['repo']}.html",
            esc(r["repo"]),
            f'<span class="count">{fmt(r.get("star_count"))}</span>',
        )
        for r in sorted(repos, key=lambda r: -(r.get("star_count") or 0))
    )
    docs = "".join(link(f"docs/{slug}.html", esc(title)) for slug, title in DOCS)
    return (
        '<nav class="sidebar" aria-label="Site">'
        f'<p class="nav-title">Maps</p><ul>{maps}</ul>'
        f'<p class="nav-title">Documentation</p><ul>{docs}</ul></nav>'
    )


def page(
    title: str,
    heading: str,
    sub: str,
    body: str,
    *,
    site_name: str,
    nav: str,
    repository: str,
    generated: str,
    logo: str = "",
    crumb: str = "",
    map_data: dict | None = None,
    root: str = "",
) -> str:
    """One page in the site frame. `root` is the path from this page to the site root
    ("" or "../"), prefixed to every site-relative link."""
    crumb = f'<div class="crumb">{crumb}</div>' if crumb else ""
    sub = f'<p class="sub">{sub}</p>' if sub else ""
    map_block = ""
    if map_data is not None:
        data = json.dumps(map_data, ensure_ascii=False).replace("</", "<\\/")
        map_block = (
            f'<script id="map-data" type="application/json">{data}</script>'
            f'<script src="{LEAFLET}/leaflet.js"></script>'
            f'<script src="{root}assets/map.js"></script>'
        )
    leaflet_css = f'<link rel="stylesheet" href="{LEAFLET}/leaflet.css">\n' if map_data else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
{leaflet_css}<link rel="stylesheet" href="{root}assets/style.css">
{THEME_INIT}</head>
<body>
<input type="checkbox" id="nav-toggle" class="nav-toggle">
<header class="topbar">
<label for="nav-toggle" class="icon-btn menu-btn" aria-label="Menu" title="Menu">{MENU_ICON}</label>
{logo}<a class="site-name" href="{root}index.html">{esc(site_name)}</a>
<a class="source" href="https://github.com/{esc(repository)}">{GITHUB_ICON}<span>{esc(repository)}</span></a>
<button id="theme-toggle" class="icon-btn theme-toggle" type="button"></button>
</header>
<div class="layout">
<label for="nav-toggle" class="scrim" aria-hidden="true"></label>
{nav}
<div class="content">
<div class="page-head">{crumb}<h1>{heading}</h1>{sub}</div>
<main>{body}</main>
<footer>Updated {esc(generated[:16].replace("T", " "))} UTC ·
Locations are self-reported on GitHub profiles, geocoded with
<a href="https://nominatim.openstreetmap.org/">OpenStreetMap Nominatim</a> ·
<a href="https://github.com/{esc(repository)}">source</a></footer>
</div>
</div>
<script src="{root}assets/theme.js"></script>
<script src="{root}assets/logo.js"></script>
{map_block}
</body></html>
"""


def doc_page(slug: str, values: dict) -> tuple[str, list[tuple[str, str]]]:
    """A docs fragment with `values` filled in, and its (id, title) h2 sections."""
    text = (resources.files("stargazer_map") / "docs" / f"{slug}.html").read_text(encoding="utf-8")
    body = string.Template(text).safe_substitute(values)
    return body, re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', body)


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
        logo_img = f'<img class="logo" src="{{root}}assets/{name}" alt="{esc(org)}">'
    else:
        # Loaded by the browser, like the map tiles, so the build stays offline. This
        # host (unlike github.com/<org>.png, a redirect) sends CORS headers, which
        # logo.js needs to crop the avatar's blank margins.
        avatar = f"https://avatars.githubusercontent.com/{urllib.parse.quote(org)}?s=400"
        logo_img = (
            f'<img class="logo avatar" src="{esc(avatar)}" alt="{esc(org)}"'
            ' crossorigin="anonymous">'
        )
    # The logo links to the owner on GitHub, so the index needs no crumb for it.
    logo_img = f'<a class="logo-link" href="https://github.com/{esc(org)}">{logo_img}</a>'
    site_name = f"{org} star maps"

    def write(href: str, title, heading, sub, body, sections=(), **kw):
        root = "../" * href.count("/")
        path = site_dir / href
        path.parent.mkdir(exist_ok=True)
        html_ = page(
            title,
            heading,
            sub,
            body,
            site_name=site_name,
            nav=sidebar(org, repos, href, root, sections),
            repository=repository,
            generated=generated,
            logo=logo_img.replace("{root}", root),
            root=root,
            **kw,
        )
        path.write_text(html_, encoding="utf-8")

    # Per-repo pages
    for r in repos:
        stats_file = data_dir / "stats" / f"{r['repo']}.json"
        stats = json.loads(stats_file.read_text(encoding="utf-8"))
        heading = f'<a href="{esc(r["url"])}" style="color:inherit">{esc(r["repo"])}</a>'
        if r.get("archived"):
            heading += '<span class="badge">archived</span>'
        write(
            f"{r['repo']}.html",
            f"{r['repo']} stargazers",
            heading,
            esc(r.get("description") or "Where this repository's stargazers are."),
            detail_body(stats, r.get("star_count")),
            crumb=f'<a href="index.html">{esc(org)}</a> / {esc(r["repo"])}',
            map_data=map_data(stats, layers),
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
    write(
        "index.html",
        site_name,
        f"Where {esc('PRISM Institute' if org == 'prism-oncology' else org)} stargazers are",
        "One map per repository, rebuilt weekly from public GitHub profile locations.",
        body,
        map_data=map_data(overall, layers),
    )

    # Documentation
    values = {
        "org": esc(org),
        "repository": esc(repository),
        "min_stars_note": (
            f" Repositories with fewer than {min_stars} stars get no page of their own, but"
            " their stargazers still count on the overview map."
            if min_stars > 0
            else ""
        ),
    }
    for slug, title in DOCS:
        body, sections = doc_page(slug, values)
        write(
            f"docs/{slug}.html",
            f"{title} · {site_name}",
            esc(title),
            "",
            f'<article class="prose">{body}</article>',
            sections,
            crumb=f'<a href="../index.html">{esc(org)}</a> / Documentation',
        )

    (site_dir / ".nojekyll").write_text("")
    print(f"Built {len(repos) + 1 + len(DOCS)} pages in {site_dir}")
    return site_dir
