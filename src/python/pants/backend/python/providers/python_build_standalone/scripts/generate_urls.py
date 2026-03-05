# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import sys
from collections.abc import Generator, Iterable
from pathlib import Path

import github
import requests
from github.GitRelease import GitRelease
from github.GitReleaseAsset import GitReleaseAsset
from github.Repository import Repository

VERSIONS_PATH = Path(
    "src/python/pants/backend/python/providers/python_build_standalone/versions_info.json"
)


def _github():
    # generate with `gh auth token`
    token = os.environ.get("GH_TOKEN")
    if token is None:
        print(
            "WARNING: No GitHub token configured in GH_TOKEN. Lower rate limits will apply!",
            file=sys.stderr,
        )
    return github.Github(auth=github.Auth.Token(token) if token else None, per_page=10)


def _compute_sha256(url):
    response = requests.get(url, stream=True)
    sha256_hash = hashlib.sha256()

    for chunk in response.iter_content(chunk_size=4096):
        if chunk:
            sha256_hash.update(chunk)

    return sha256_hash.hexdigest()


def scrape_release(
    release: GitRelease,
    scraped_releases: set[str],
    asset_map: dict[str, GitReleaseAsset],
    sha256_map: dict[str, str],
):
    scraped_releases.add(release.tag_name)

    applicable_sha256_assets: list[GitReleaseAsset] = []
    sha256sums_asset: GitReleaseAsset | None = None
    applicable_release_assets_count = 0
    for asset in release.get_assets():
        if asset.name == "SHA256SUMS":
            if sha256sums_asset is not None:
                raise ValueError("Found multiple release assets claiming to be SHA256SUMS file.")
            sha256sums_asset = asset
            continue

        # NB: From https://python-build-standalone.readthedocs.io/en/latest/running.html#obtaining-distributions
        # > Casual users will likely want to use the install_only archive,
        # > as most users do not need the build artifacts present in the full archive.
        is_applicable = any(
            f"{machine}-{osname}-install_only" in asset.name
            for machine, osname in itertools.product(
                ["aarch64", "x86_64"], ["apple-darwin", "unknown-linux-gnu"]
            )
        )
        if is_applicable:
            if asset.name.endswith(".sha256"):
                applicable_sha256_assets.append(asset)
            else:
                asset_map[asset.name] = asset
                applicable_release_assets_count += 1

    print(f"-- Found {applicable_release_assets_count} applicable asset(s).")

    # Obtain the published SHA256 hashes for the release aasets.
    if sha256sums_asset is not None:
        print("-- Scraping reported SHA256 hashes from the release's SHA256SUMS file.")
        sha256sums_content = requests.get(sha256sums_asset.browser_download_url).text
        for sha256sum_line in sha256sums_content.splitlines():
            sha256_hash, asset_name = re.split(r"\s+", sha256sum_line.strip())
            if asset_name in asset_map:
                if asset_name in sha256_map:
                    raise ValueError(f"A SHA256 hash for {asset_name} was already discovered!")
                sha256_map[asset_name] = sha256_hash
    else:
        if release.tag_name >= "20250708":
            raise ValueError(
                "PBS releases from 20250708 onwward only publish a SHA256SUMS file, but it was not found in the release."
            )
        print("-- Scraping reported SHA256 hashes from .sha256 files.")
        for asset in applicable_sha256_assets:
            shasum = requests.get(asset.browser_download_url).text.strip()
            sha256_map[asset.name.removesuffix(".sha256")] = shasum


def get_releases_after_given_release(
    gh: github.Github, pbs_repo: Repository, scraped_releases: set[str]
) -> list[GitRelease]:
    recent_releases: list[GitRelease] = []
    for release in pbs_repo.get_releases():
        if release.prerelease or release.draft:
            continue
        if release.tag_name in scraped_releases:
            break
        recent_releases.append(release)

    return sorted(recent_releases, key=lambda r: r.created_at)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scrape-all-releases", dest="scrape_all_releases", action="store_true")
    parser.add_argument(
        "--scrape-release", metavar="RELEASE", dest="scrape_releases", action="append"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    options = parser.parse_args()

    print("Starting to scrape GitHub PBS releases.")
    if not VERSIONS_PATH.parent.exists():
        raise Exception("This helper script must be run from the root of the Pants repository.")

    versions_info = json.loads(VERSIONS_PATH.read_text())
    scraped_releases = set(versions_info["scraped_releases"])

    gh = _github()
    pbs_repo = gh.get_repo("astral-sh/python-build-standalone")

    print("Downloading PBS release metadata.")
    releases: Iterable[GitRelease]
    if options.scrape_all_releases:

        def get_all_releases_filtered() -> Generator[GitRelease]:
            for release in pbs_repo.get_releases():
                if release.prerelease or release.draft:
                    continue
                yield release

        releases = get_all_releases_filtered()
    elif options.scrape_releases:
        print(f"Only scraping releases: {', '.join(options.scrape_releases)}")
        releases = [pbs_repo.get_release(tag_name) for tag_name in options.scrape_releases]
    else:
        latest_scraped_release_name = max(scraped_releases)
        print(f"Latest scraped release: {latest_scraped_release_name}")
        releases = get_releases_after_given_release(
            gh, pbs_repo=pbs_repo, scraped_releases=scraped_releases
        )
        recent_release_tags = [r.tag_name for r in releases]
        print(f"Found recent release tags: {','.join(recent_release_tags)}")

    print("Downloaded PBS release metadata.")

    asset_map: dict[str, GitReleaseAsset] = {}
    sha256_map: dict[str, str] = {}
    for release in releases:
        print(f"Scraping release tag `{release.tag_name}`.")
        scrape_release(
            release=release,
            scraped_releases=scraped_releases,
            asset_map=asset_map,
            sha256_map=sha256_map,
        )

    print("Finished scraping releases.")

    versions_info["scraped_releases"] = sorted(scraped_releases)
    pythons_dict = versions_info["pythons"]
    asset_matcher = re.compile(r"^([a-zA-Z0-9]+)-([0-9.]+)\+([0-9.]+)-")

    for asset in asset_map.values():
        matched_versions = asset_matcher.match(asset.name)
        if not matched_versions:
            continue

        python_version, pbs_release_tag = matched_versions.groups()[1:3]
        if python_version not in pythons_dict:
            pythons_dict[python_version] = {}
        if pbs_release_tag not in pythons_dict[python_version]:
            pythons_dict[python_version][pbs_release_tag] = {}

        name_parts = asset.name.replace("darwin", "macos").replace("aarch64", "arm64").split("-")
        pants_platform_tag = f"{name_parts[4]}_{name_parts[2]}"
        sha256sum = sha256_map.get(asset.name)
        if sha256sum is None:
            print(
                f"WARNING: No precomputed SHA256 hash was reported for {asset.name}. Downloading the artifact to compute."
            )
            sha256sum = _compute_sha256(asset.browser_download_url)

        pythons_dict[python_version][pbs_release_tag][pants_platform_tag] = {
            "url": asset.browser_download_url,
            "sha256": sha256sum,
            "size": asset.size,
        }

    VERSIONS_PATH.write_text(json.dumps(versions_info, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
