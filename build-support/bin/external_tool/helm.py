# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from collections.abc import Iterator

from external_tool.github import GithubReleases


class HelmReleases:
    """Fetches Helm releases from GitHub.

    Helm binaries are hosted on get.helm.sh, but releases are published on
    GitHub (helm/helm). This class uses the GitHub Releases API to discover
    available versions.

    See https://github.com/helm/helm/issues/5663 for historical hosting discussion.
    """

    _GITHUB_URL_TEMPLATE = "https://github.com/helm/helm/releases/download/v{version}/helm-v{version}-{platform}.tar.gz"

    def __init__(self, only_latest: bool) -> None:
        self.only_latest = only_latest
        self._github_releases = GithubReleases(only_latest=only_latest)

    def get_releases(self, url_template: str) -> Iterator[str]:
        # Ignore the url_template (which points to get.helm.sh) and use GitHub instead
        return self._github_releases.get_releases(self._GITHUB_URL_TEMPLATE)
