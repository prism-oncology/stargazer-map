# stargazer-map

<div >

[![Live maps](https://img.shields.io/badge/live%20maps-GitHub%20Pages-c2410c?logo=github)](https://prism-oncology.github.io/stargazer-map/)
[![Update star maps](https://github.com/prism-oncology/stargazer-map/actions/workflows/update-maps.yml/badge.svg)](https://github.com/prism-oncology/stargazer-map/actions/workflows/update-maps.yml)
[![Tests](https://github.com/prism-oncology/stargazer-map/actions/workflows/tests.yml/badge.svg)](https://github.com/prism-oncology/stargazer-map/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Proudly Vibe Coded - Midnight Glow](https://vibecoded.fyi/badges/plastic/main/proudly-vibe-coded-midnight-glow.svg)](https://vibecoded.fyi/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

</div>

Weekly, automatically updated maps of where the stargazers of a GitHub user's or organisation's repositories are, published with GitHub Pages. Fork it to get maps for your own repositories.

Each public repository gets its own map, and an overview page combines all of them. Each map can show countries coloured by their number of stargazers, a bubble for each place, or both. Visitors switch each view on or off on the map. Locations come from the free-text "location" field on stargazers' GitHub profiles and are geocoded with [OpenStreetMap Nominatim](https://nominatim.openstreetmap.org/).

## Make your own

Fork this repository into the account or organisation whose stars you want to map. The maps cover every public repository the fork's owner has, except forks.

1. **Create a token.** Create a [classic personal access token](https://github.com/settings/tokens/new?scopes=public_repo&description=stargazer-map) with only the **`public_repo`** scope (the link preselects it). See [Token](#token) for why. Fine-grained tokens don't work for this.
2. **Add it as a secret.** In your fork, go to *Settings → Secrets and variables → Actions → New repository secret*. Name it `STARGAZERS_TOKEN` and paste the token.
3. **Enable GitHub Pages.** Go to *Settings → Pages* and set *Source* to **GitHub Actions**.
4. **Enable Actions.** Open the *Actions* tab and enable workflows. GitHub turns off scheduled workflows in forks until you do this.
5. **Run it once.** Go to *Actions → Update star maps → Run workflow*. After that, it runs every Monday at 04:17 UTC.

The site is published at `https://<owner>.github.io/<fork-name>/`.

The workflow keeps its data (stats and `geocode-cache.json`) on a separate `data` branch, so it never commits to `main`. A fork that didn't copy that branch starts with empty data. The geocode cache keeps locations that have already been geocoded, so they aren't looked up again. Nominatim allows about one request per second, so each run geocodes at most 800 new locations. If you have more stargazers than that, the maps fill in over several runs.

### Options

Set these in the `env:` blocks of `.github/workflows/update-maps.yml`. `MAP_LAYERS`, `MIN_STARS` and `LOGO` go on the *Build site* step, the others on the *Fetch* step:

| Variable | Default | Effect |
|---|---|---|
| `INCLUDE_FORKS` | `false` | Include repositories that are forks |
| `INCLUDE_ARCHIVED` | `true` | Include archived repositories |
| `INCLUDE_LOGINS` | `false` | Show stargazers' usernames in map popups and in the published JSON |
| `MAX_GEOCODE` | `800` | Maximum number of new locations geocoded per run |
| `MAP_LAYERS` | `countries,bubbles` | Map views shown when a page opens: `countries`, `bubbles`, or both. Visitors can still toggle each one |
| `MIN_STARS` | `0` (`10` for prism-oncology) | Only list repositories with at least this many stars. Smaller repositories get no page or card, but their stargazers still count on the overview map |
| `LOGO` | none (`branding/prism-oncology.jpeg` for prism-oncology) | Image file (svg, png, jpg or webp) shown at the top of every page. Put yours in `branding/` |

## Token

GitHub only lets admins and collaborators of a repository list its stargazers, so the workflow's built-in `GITHUB_TOKEN` is not enough. `STARGAZERS_TOKEN` must be a classic personal access token with the `public_repo` scope, created by someone with admin or collaborator access to the repositories you want to map. For an organisation that uses SAML single sign-on, also authorise the token for that organisation (*Configure SSO* next to the token).

When a token expires or loses access, the workflow fails and the log quotes GitHub's refusal. If only some repositories are refused, their pages show a warning and keep the data from the last successful run.

## Run locally

Requires Python 3.10+ and the [GitHub CLI](https://cli.github.com/), signed in with `gh auth login`.

```sh
pip install git+https://github.com/prism-oncology/stargazer-map
stargazer-map fetch               # writes ./data; --org <owner> to map someone else
stargazer-map build               # writes ./site
python -m http.server -d site
```

Run `stargazer-map fetch --help` to see every option. Each option can also be set with the environment variable from the table above. The same steps are available from Python:

```python
import stargazer_map

stargazer_map.fetch("prism-oncology", "data")
stargazer_map.build("data", "site")
```

## Development

```sh
git clone https://github.com/prism-oncology/stargazer-map && cd stargazer-map
pip install -e ".[dev]"
pytest
ruff check . && ruff format .
```
