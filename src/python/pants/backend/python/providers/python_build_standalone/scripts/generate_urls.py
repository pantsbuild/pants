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
from pathlib import Path

import github
import requests
from github.GitReleaseAsset import GitReleaseAsset

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
    return github.Github(auth=github.Auth.Token(token) if token else None)


def _compute_sha256(url):
    response = requests.get(url, stream=True)
    sha256_hash = hashlib.sha256()

    for chunk in response.iter_content(chunk_size=4096):
        if chunk:
            sha256_hash.update(chunk)

    return sha256_hash.hexdigest()


def scrape_release(release, scraped_releases, asset_map, sha256_map):
    scraped_releases.add(release.tag_name)
    assets = release.get_assets()
    for asset in assets:
        # NB: From https://python-build-standalone.readthedocs.io/en/latest/running.html#obtaining-distributions
        # > Casual users will likely want to use the install_only archive,
        # > as most users do not need the build artifacts present in the full archive.
        is_applicable = any(
            f"{machine}-{osname}-install_only" in asset.name
            for machine, osname in itertools.product(
                ["aarch64", "x86_64"], ["apple-darwin", "unknown-linux-gnu"]
            )
        )
        if not is_applicable:
            continue

        is_checksum = asset.name.endswith(".sha256")
        if is_checksum:
            shasum = requests.get(asset.browser_download_url).text.strip()
            sha256_map[asset.name.removesuffix(".sha256")] = shasum
        else:
            asset_map[asset.name] = asset


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

    github = _github()
    pbs_repo = github.get_repo("indygreg/python-build-standalone")
    print("Downloading PBS release metadata.")
    releases = pbs_repo.get_releases()
    print("Downloaded PBS release metadata.")

    asset_map: dict[str, GitReleaseAsset] = {}
    sha256_map: dict[str, str] = {}
    for release in releases.reversed:
        tag_name = release.tag_name

        if (
            options.scrape_all_releases
            or (options.scrape_releases and tag_name in options.scrape_releases)
            or (not options.scrape_releases and tag_name not in scraped_releases)
        ):
            print(f"Scraping release tag `{tag_name}`.")
            scrape_release(
                release=release,
                scraped_releases=scraped_releases,
                asset_map=asset_map,
                sha256_map=sha256_map,
            )
        else:
            if options.verbose:
                print(f"Skipped release tag `{tag_name}.")

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
            sha256sum = _compute_sha256(asset.browser_download_url)

        pythons_dict[python_version][pbs_release_tag][pants_platform_tag] = {
            "url": asset.browser_download_url,
            "sha256": sha256sum,
            "size": asset.size,
        }

    VERSIONS_PATH.write_text(json.dumps(versions_info, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
