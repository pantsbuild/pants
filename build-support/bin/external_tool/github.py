# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from collections.abc import Generator, Iterator
from typing import TypedDict
from urllib.parse import urlparse

import requests


class Release(TypedDict):
    tag_name: str


def fetch_releases(url: str) -> list[Release]:
    response = requests.get(url, headers={"Accept": "application/vnd.github.v3+json"})
    response.raise_for_status()
    releases = response.json()
    assert isinstance(releases, list)
    return releases


def _parse_github_releases(json_data: list[Release]) -> Generator[str]:
    for release in json_data:
        if "tag_name" in release:
            yield release["tag_name"].strip().lstrip("v")


class GithubReleases:
    def __init__(self, only_latest: bool) -> None:
        self.only_latest = only_latest

    def get_releases(self, url_template: str) -> Iterator[str]:
        parsed = urlparse(url_template)
        index = parsed.path.find("/releases/")
        if index == -1:
            index = parsed.path.find("/archive/")
            if index == -1:
                raise ValueError(url_template)
        repo = parsed.path[:index]
        url = f"https://api.github.com/repos{repo}/releases"
        releases_json = fetch_releases(url)
        result = _parse_github_releases(releases_json)
        if self.only_latest:
            return iter([next(iter(result))])
        return result
