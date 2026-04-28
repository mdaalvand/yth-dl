#!/usr/bin/env python3
"""Delete GitHub releases, tags, workflow runs, and artifacts for one or more repos.

The script reads the GitHub token from the authenticated `origin` remote URL,
so it can operate on any local clone that already has push/delete access.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError


@dataclass(frozen=True)
class RepoInfo:
    path: Path
    remote_url: str
    token: str
    slug: str


def run_git(repo: Path, *args: str, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        capture_output=capture_output,
    )


def parse_repo_info(repo_path: Path) -> RepoInfo:
    remote_url = run_git(repo_path, "remote", "get-url", "origin", capture_output=True).stdout.strip()
    match = re.match(r"https://([^@]+)@github\.com/(.+?)(?:\.git)?$", remote_url)
    if not match:
        raise SystemExit(f"unexpected origin url for {repo_path}: {remote_url}")
    return RepoInfo(path=repo_path, remote_url=remote_url, token=match.group(1), slug=match.group(2))


def api_client(repo: RepoInfo) -> tuple[dict[str, str], str]:
    headers = {
        "Authorization": f"Bearer {repo.token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "codex-github-history-cleanup",
    }
    base = f"https://api.github.com/repos/{repo.slug}"
    return headers, base


def api_json(headers: dict[str, str], url: str) -> object:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def api_delete(headers: dict[str, str], url: str) -> None:
    req = urllib.request.Request(url, headers=headers, method="DELETE")
    try:
        with urllib.request.urlopen(req) as resp:
            resp.read()
    except HTTPError as exc:
        if exc.code != 404:
            raise


def paginate_items(headers: dict[str, str], base_url: str, key: str | None = None) -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        data = api_json(headers, f"{base_url}?per_page=100&page={page}")
        if not data:
            break
        if key is None:
            if not isinstance(data, list):
                raise SystemExit(f"unexpected response for {base_url}: {type(data)!r}")
            items.extend(data)
        else:
            if not isinstance(data, dict) or key not in data:
                raise SystemExit(f"unexpected response for {base_url}: {type(data)!r}")
            batch = data[key]
            if not isinstance(batch, list):
                raise SystemExit(f"unexpected collection for {base_url}: {type(batch)!r}")
            items.extend(batch)
        page += 1
    return items


def delete_local_tags(repo: Path, dry_run: bool) -> list[str]:
    output = run_git(repo, "tag", "--list", capture_output=True).stdout.splitlines()
    tags = [tag.strip() for tag in output if tag.strip()]
    for tag in tags:
        if dry_run:
            print(f"[dry-run] local tag: {tag}")
            continue
        run_git(repo, "tag", "-d", tag)
    return tags


def delete_remote_tags(repo: Path, dry_run: bool) -> list[str]:
    output = run_git(repo, "ls-remote", "--tags", "origin", capture_output=True).stdout.splitlines()
    tags: list[str] = []
    seen: set[str] = set()
    for line in output:
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        ref = parts[1]
        if not ref.startswith("refs/tags/"):
            continue
        tag = ref[len("refs/tags/") :]
        if tag.endswith("^{}"):
            tag = tag[:-3]
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)

    for start in range(0, len(tags), 20):
        batch = tags[start : start + 20]
        if dry_run:
            print(f"[dry-run] remote tags batch: {', '.join(batch)}")
            continue
        run_git(repo, "push", "origin", "--delete", *batch)
    return tags


def delete_releases(headers: dict[str, str], base_url: str, dry_run: bool) -> list[dict]:
    releases = paginate_items(headers, f"{base_url}/releases")
    for release in releases:
        rid = release["id"]
        name = release.get("name", "")
        tag = release.get("tag_name", "")
        if dry_run:
            print(f"[dry-run] release: id={rid} tag={tag} name={name}")
            continue
        api_delete(headers, f"{base_url}/releases/{rid}")
    return releases


def delete_workflow_runs(headers: dict[str, str], base_url: str, dry_run: bool) -> list[dict]:
    runs = paginate_items(headers, f"{base_url}/actions/runs", key="workflow_runs")
    for run in runs:
        run_id = run["id"]
        name = run.get("name", "")
        status = run.get("status", "")
        if dry_run:
            print(f"[dry-run] run: id={run_id} status={status} name={name}")
            continue
        api_delete(headers, f"{base_url}/actions/runs/{run_id}")
    return runs


def delete_workflow_artifacts(headers: dict[str, str], base_url: str, dry_run: bool) -> list[dict]:
    artifacts = paginate_items(headers, f"{base_url}/actions/artifacts", key="artifacts")
    for artifact in artifacts:
        artifact_id = artifact["id"]
        name = artifact.get("name", "")
        if dry_run:
            print(f"[dry-run] artifact: id={artifact_id} name={name}")
            continue
        api_delete(headers, f"{base_url}/actions/artifacts/{artifact_id}")
    return artifacts


def repo_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise argparse.ArgumentTypeError(f"repo path does not exist: {path}")
    return path


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repos", nargs="+", type=repo_path, help="Local git repository paths")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    parser.add_argument("--no-tags", action="store_true", help="Skip tag deletion")
    parser.add_argument("--no-releases", action="store_true", help="Skip release deletion")
    parser.add_argument("--no-runs", action="store_true", help="Skip workflow run deletion")
    parser.add_argument("--no-artifacts", action="store_true", help="Skip artifact deletion")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    overall = 0

    for repo_path_value in args.repos:
        repo = parse_repo_info(repo_path_value)
        headers, base_url = api_client(repo)
        print(f"== {repo.slug} ==")

        if not args.no_tags:
            local_tags = delete_local_tags(repo.path, args.dry_run)
            remote_tags = delete_remote_tags(repo.path, args.dry_run)
            print(f"tags: local={len(local_tags)} remote={len(remote_tags)}")

        if not args.no_releases:
            releases = delete_releases(headers, base_url, args.dry_run)
            print(f"releases: {len(releases)}")

        if not args.no_runs:
            runs = delete_workflow_runs(headers, base_url, args.dry_run)
            print(f"workflow runs: {len(runs)}")

        if not args.no_artifacts:
            artifacts = delete_workflow_artifacts(headers, base_url, args.dry_run)
            print(f"artifacts: {len(artifacts)}")

        print()

    return overall


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
