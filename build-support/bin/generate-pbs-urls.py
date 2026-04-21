# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
#
# From the Pants repo root, run: `python3 build-support/bin/generate-pbs-urls.py`
#

import itertools
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Final, TypedDict

VERSIONS_PATH: Final[Path] = Path(
    "src/python/pants/backend/python/providers/python_build_standalone/versions_info.json"
)

VALID_PBS_PATTERNS: Final[set[str]] = {
    f"{machine}-{osname}-install_only_stripped"
    for machine, osname in itertools.product(
        ["aarch64", "x86_64"], ["apple-darwin", "unknown-linux-gnu"]
    )
}

# Grab version, release tag, ignore alpha/beta releases
ASSET_MATCHER: Final[re.Pattern] = re.compile(r"^([a-zA-Z0-9]+)-([0-9.]+)\+([0-9.]+)-")


class GithubTaggedRelease(TypedDict):
    tagName: str


class GithubReleaseAsset(TypedDict):
    digest: str
    name: str
    size: int
    url: str


class FileInfo(TypedDict):
    sha256: str
    size: int
    url: str


class LocalReleaseInfo(TypedDict):
    pythons: dict[str, dict[str, dict[str, FileInfo]]]
    scraped_releases: list[str]


def list_all_remote_releases() -> set[str]:
    """Uses `gh` to call out to GitHub to grab all PBS releases"""
    result = subprocess.run(
        [
            "gh",
            "release",
            "list",
            "--repo",
            "astral-sh/python-build-standalone",
            "--json",
            "tagName",
            "--exclude-drafts",
            "--exclude-pre-releases",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    releases: list[GithubTaggedRelease] = json.loads(result.stdout)
    return {r["tagName"] for r in releases}


def list_filtered_release_assets(release_tag: str) -> list[GithubReleaseAsset]:
    """
    Uses `gh` to get all assets for this release.
    The results are then filtered for Pants-relevant releases (determined by VALID_PATTERNS).
    """
    result = subprocess.run(
        [
            "gh",
            "release",
            "view",
            release_tag,
            "--repo",
            "astral-sh/python-build-standalone",
            "--json",
            "assets",
            "--jq",
            "[.assets[] | {digest, name, size, url}]",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assets: list[GithubReleaseAsset] = json.loads(result.stdout)
    return [asset for asset in assets if any(p in asset["name"] for p in VALID_PBS_PATTERNS)]


def main():
    if not VERSIONS_PATH.exists():
        raise FileNotFoundError(
            "This helper script must be run from the root of the Pants repository."
        )

    print("Starting to scrape GitHub PBS releases")
    versions_info: LocalReleaseInfo = json.loads(VERSIONS_PATH.read_text())
    all_local_release_tags = set(versions_info["scraped_releases"])

    all_release_tags = list_all_remote_releases()
    missing_release_tags = sorted(all_release_tags.difference(all_local_release_tags))
    print(f"version_info is missing the following releases tags: {missing_release_tags}")
    if not missing_release_tags:
        print("Releases are up-to-date... Exiting...")
        sys.exit(0)

    for tag in missing_release_tags:
        print(f"\nFetching and parsing assets for release: {tag}")
        assets = list_filtered_release_assets(tag)
        all_local_release_tags.add(tag)

        for asset in assets:
            asset_name = asset["name"]
            matches = ASSET_MATCHER.match(asset_name)
            if not matches:
                print(f"    Skipping: {asset_name}")
                continue
            else:
                print(f"    Parsing: {asset_name}")

            python_version, pbs_release_tag = matches.groups()[1:3]
            assert tag == pbs_release_tag, (
                f"Fetched release info ({tag}) does not match parsed release info ({pbs_release_tag})"
            )

            name_parts = (
                asset_name.replace("darwin", "macos").replace("aarch64", "arm64").split("-")
            )
            platform = f"{name_parts[4]}_{name_parts[2]}"

            versions_info["pythons"].setdefault(python_version, {}).setdefault(tag, {})[
                platform
            ] = {
                "sha256": asset["digest"].removeprefix("sha256:"),
                "size": asset["size"],
                "url": asset["url"],
            }

    versions_info["scraped_releases"] = sorted(all_local_release_tags)
    print(f"Writing release information to {VERSIONS_PATH}")
    VERSIONS_PATH.write_text(json.dumps(versions_info, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
