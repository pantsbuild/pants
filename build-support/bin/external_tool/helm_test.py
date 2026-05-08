# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from external_tool.helm import HelmReleases


def test_helm_releases_only_latest(monkeypatch) -> None:
    mock_releases = [
        {"tag_name": "v3.14.3"},
        {"tag_name": "v3.14.2"},
        {"tag_name": "v3.13.0"},
    ]

    def mock_fetch(url: str):
        assert "helm/helm" in url
        return mock_releases

    monkeypatch.setattr("external_tool.github.fetch_releases", mock_fetch)

    helm = HelmReleases(only_latest=True)
    versions = list(helm.get_releases("https://get.helm.sh/helm-v{version}-{platform}.tar.gz"))

    assert versions == ["3.14.3"]


def test_helm_releases_all_versions(monkeypatch) -> None:
    mock_releases = [
        {"tag_name": "v3.14.3"},
        {"tag_name": "v3.14.2"},
        {"tag_name": "v3.13.0"},
    ]

    def mock_fetch(url: str):
        assert "helm/helm" in url
        return mock_releases

    monkeypatch.setattr("external_tool.github.fetch_releases", mock_fetch)

    helm = HelmReleases(only_latest=False)
    versions = list(helm.get_releases("https://get.helm.sh/helm-v{version}-{platform}.tar.gz"))

    assert versions == ["3.14.3", "3.14.2", "3.13.0"]


def test_helm_releases_uses_github_api(monkeypatch) -> None:
    captured_url = None

    def mock_fetch(url: str):
        nonlocal captured_url
        captured_url = url
        return [{"tag_name": "v3.14.3"}]

    monkeypatch.setattr("external_tool.github.fetch_releases", mock_fetch)

    helm = HelmReleases(only_latest=True)
    list(helm.get_releases("https://get.helm.sh/helm-v{version}-{platform}.tar.gz"))

    assert captured_url == "https://api.github.com/repos/helm/helm/releases"
