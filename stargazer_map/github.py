"""GitHub GraphQL access through the `gh` CLI."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

REPOS_QUERY = """
query($org: String!, $endCursor: String) {
  repositoryOwner(login: $org) {
    repositories(first: 100, after: $endCursor, privacy: PUBLIC,
                 ownerAffiliations: [OWNER],
                 orderBy: {field: STARGAZERS, direction: DESC}) {
      nodes {
        name description url stargazerCount isFork isArchived
        primaryLanguage { name }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

STARGAZERS_QUERY = """
query($owner: String!, $name: String!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    stargazers(first: 100, after: $endCursor) {
      edges { starredAt node { login location } }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def gh_graphql_paginate(query: str, jq: str, **variables: str) -> list[dict]:
    cmd = ["gh", "api", "graphql", "--paginate", "-f", f"query={query}", "--jq", jq]
    for key, value in variables.items():
        cmd += ["-f", f"{key}={value}"]
    for attempt in range(3):
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        err = proc.stderr.strip()
        # Permission problems won't fix themselves; transient ones might.
        if re.search(r"NOT_FOUND|FORBIDDEN|Could not resolve|Resource not accessible|403", err):
            raise PermissionError(err)
        print(f"  gh failed (attempt {attempt + 1}/3): {err[:300]}", file=sys.stderr)
        time.sleep(10 * (attempt + 1))
    raise RuntimeError(err)


def list_repos(org: str, include_forks: bool, include_archived: bool) -> list[dict]:
    repos = gh_graphql_paginate(REPOS_QUERY, ".data.repositoryOwner.repositories.nodes[]", org=org)
    return [
        r
        for r in repos
        if (include_forks or not r["isFork"]) and (include_archived or not r["isArchived"])
    ]


def list_stargazers(owner: str, repo: str) -> list[dict]:
    """[{login, location, starredAt}] for each current stargazer of owner/repo."""
    return gh_graphql_paginate(
        STARGAZERS_QUERY,
        ".data.repository.stargazers.edges[] | .node + {starredAt}",
        owner=owner,
        name=repo,
    )


def parse_github_url(url: str) -> str | None:
    """'owner/name' from an https or ssh GitHub remote URL."""
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url.strip())
    return match.group(1) if match else None


def current_repository() -> str | None:
    """owner/name of the checkout we run in: set by GitHub Actions, else the git remote."""
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    proc = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True)
    return parse_github_url(proc.stdout) if proc.returncode == 0 else None
