# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import hashlib
import itertools
import json
import os
import subprocess
from pathlib import Path

# @TODO:
import github  # pants: no-infer-dep
import requests

VERSIONS_PATH = Path(__file__).parent.parent / "versions_info.json"


def _github():
    token = os.environ.get("GH_TOKEN")
    if not token:
        token = subprocess.run(
            ["gh", "auth", "token"], check=True, text=True, capture_output=True
        ).stdout.strip()

    return github.Github(auth=github.Auth.Token(token))


def _compute_sha256(url):
    response = requests.get(url, stream=True)
    sha256_hash = hashlib.sha256()

    for chunk in response.iter_content(chunk_size=4096):
        if chunk:
            sha256_hash.update(chunk)

    return sha256_hash.hexdigest()


def main() -> None:
    versions_info = json.loads(VERSIONS_PATH.read_text())
    scraped_releases = set(versions_info["scraped_releases"])

    github = _github()
    pbs_repo = github.get_repo("indygreg/python-build-standalone")
    releases = pbs_repo.get_releases()

    asset_map: dict[str, github.GitReleaseAsset.GitReleaseAsset] = {}
    sha256_map: dict[str, str] = {}
    for release in releases.reversed:
        tag_name = release.tag_name

        if tag_name not in scraped_releases:
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

    versions_info["scraped_releases"] = sorted(scraped_releases)
    pythons_dict = versions_info["pythons"]
    for asset in asset_map.values():
        python_version = asset.name.split("+")[0].split("-")[1]
        if python_version not in pythons_dict:
            pythons_dict[python_version] = {}

        name_parts = asset.name.replace("darwin", "macos").replace("aarch64", "arm64").split("-")
        pants_platform_tag = f"{name_parts[4]}_{name_parts[2]}"
        sha256sum = sha256_map.get(asset.name)
        if sha256sum is None:
            sha256sum = _compute_sha256(asset.browser_download_url)

        pythons_dict[python_version][pants_platform_tag] = {
            "url": asset.browser_download_url,
            "sha256": sha256sum,
            "size": asset.size,
        }

    VERSIONS_PATH.write_text(json.dumps(versions_info, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
