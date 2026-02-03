# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Script to upgrade external tool versions.

Example:

pants run build-support/bin:external-tool-upgrade -- src/python/pants/backend/python/
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import multiprocessing
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from itertools import groupby
from multiprocessing.pool import ThreadPool
from pathlib import Path
from string import Formatter
from typing import Protocol, assert_never
from urllib.parse import urlparse

import requests
from external_tool.github import GithubReleases
from external_tool.helm import HelmReleases
from external_tool.kubectl import KubernetesReleases
from external_tool.python import (
    find_modules_with_subclasses,
    get_class_variables,
    replace_class_variables,
)
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version
from tqdm import tqdm

logger = logging.getLogger(__name__)


# The ExternalToolVersion class is copied here to avoid depending on pants.
# This makes it possible to run this as a standalone script with uv or use a
# separate resolve in pants.
@dataclass(frozen=True)
class ExternalToolVersion:
    version: str
    platform: str
    sha256: str
    filesize: int
    url_override: str | None = None

    def encode(self) -> str:
        parts = [self.version, self.platform, self.sha256, str(self.filesize)]
        if self.url_override:
            parts.append(self.url_override)
        return "|".join(parts)

    @classmethod
    def decode(cls, version_str: str) -> ExternalToolVersion:
        parts = [x.strip() for x in version_str.split("|")]
        version, platform, sha256, filesize = parts[:4]
        url_override = parts[4] if len(parts) > 4 else None
        return cls(version, platform, sha256, int(filesize), url_override=url_override)


def format_string_to_regex(format_string: str) -> re.Pattern:
    r"""Converts a format string to a regex.

    >>> format_string_to_regex("/release/v{version}/bin/{platform}/kubectl")
    re.compile('^\\/release\\/v(?P<version>.*)\\/bin\\/(?P<platform>.*)\\/kubectl$')
    """
    result_regex = ["^"]
    parts = Formatter().parse(format_string)
    for literal_text, field_name, format_spec, conversion in parts:
        escaped_text = literal_text.replace("/", r"\/")
        result_regex.append(escaped_text)
        if field_name is not None:
            result_regex.append(rf"(?P<{field_name}>.*)")
    result_regex.append("$")
    return re.compile("".join(result_regex))


class Releases(Protocol):
    def get_releases(self, url_template: str) -> Iterator[str]: ...


@dataclass(frozen=True)
class ToolVersion:
    path: Path
    class_name: str
    version: ExternalToolVersion


def fetch_version(
    *,
    path: Path,
    class_name: str,
    url_template: str,
    version: str,
    platform: str,
    platform_mapping: dict[str, str] | None,
    mode: Mode,
) -> ToolVersion | None:
    if platform_mapping is not None:
        url = url_template.format(version=version, platform=platform_mapping[platform])
    else:
        url = url_template.format(version=version)
    logger.debug("fetching %s version: %s", class_name, url)
    token = os.environ.get("GITHUB_TOKEN")
    headers = (
        {}
        if token is None
        else {
            "Authorization": "Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )

    if mode == Mode.only_fetch_versions:
        size = 0
        sha256 = "0000000000000000000000000000000000000000000000000000000000000000"

    elif mode == Mode.calculate_sha_and_size:
        response = requests.get(url, headers=headers, allow_redirects=True)
        if response.status_code != 200:
            logger.debug("failed to fetch %s version %s: %s", class_name, version, response.text)
            return None

        size = len(response.content)
        sha256 = hashlib.sha256(response.content).hexdigest()
    else:
        assert_never(mode)

    return ToolVersion(
        path=path,
        class_name=class_name,
        version=ExternalToolVersion(
            version=version,
            platform=platform,
            filesize=size,
            sha256=sha256,
        ),
    )


@dataclass(frozen=True)
class Tool:
    default_known_versions: list[str]
    default_url_template: str
    default_version: str
    default_url_platform_mapping: dict[str, str] | None = None


class Mode(StrEnum):
    only_fetch_versions = "only-fetch-versions"
    calculate_sha_and_size = "calculate-sha-and-size"


def filter_versions_by_constraint(
    versions: list[ExternalToolVersion],
    constraint: str | None,
) -> list[ExternalToolVersion]:
    """Filter versions using packaging.specifiers.

    >>> filter_versions_by_constraint([ExternalToolVersion("5.0", "cowsay", "", 0)], ">=4.0,<6.0")
    [ExternalToolVersion(version='5.0', platform='cowsay', sha256='', filesize=0, url_override=None)]
    """
    if constraint is None:
        return versions

    specifier = SpecifierSet(constraint)
    return [v for v in versions if specifier.contains(v.version.lstrip("v"))]


EXCLUDE_TOOLS = {
    "ExternalCCSubsystem",  # Doesn't define default_url_template.
    "ExternalHelmPlugin",  # Is a base class itself.
    "MakeselfSubsystem",  # Weird git tag format, skip for now.
    "PexCli",  # Custom code
    # google.protobuf.runtime_version.VersionError: Detected mismatched
    # Protobuf Gencode/Runtime major versions when loading codegen/hello.proto:
    # gencode 6.30.0 runtime 5.29.3. Same major version is required.
    "Protoc",
    "Shunit2",  # Can't fetch git commits yet.
    "TerraformTool",  # Handled by a different script.
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--platforms",
        default="macos_arm64,macos_x86_64,linux_arm64,linux_x86_64",
        help="Comma separated list of platforms",
    )
    parser.add_argument(
        "-w",
        "--workers",
        default=multiprocessing.cpu_count(),
        type=int,
        help="Thread pool size",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Verbose output",
    )
    parser.add_argument(
        "path",
        help="Root directory to traverse",
        type=Path,
    )
    parser.add_argument(
        "--mode",
        choices=list(Mode),
        type=Mode,
        default="calculate-sha-and-size",
    )
    parser.add_argument(
        "--version-constraint",
        default=None,
        help="Version constraint to filter versions (e.g., '>2.2.2,<3')",
    )
    parser.add_argument(
        "--max-releases",
        type=int,
        default=64,
        help="Maximum number of releases to fetch when --version-constraint is set (default: 64)",
    )

    args = parser.parse_args()

    if args.version_constraint:
        try:
            SpecifierSet(args.version_constraint)
        except InvalidSpecifier as e:
            parser.error(f"Invalid version constraint: {e}")

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger(__name__).level = level

    logger.info("starting in %s mode", args.mode)

    modules = list(
        find_modules_with_subclasses(
            args.path,
            base_classes={
                "TemplatedExternalTool",
                "ExternalHelmPlugin",
            },
            exclude=EXCLUDE_TOOLS,
        )
    )

    logger.debug("found tools: %s", modules)

    pool = ThreadPool(processes=args.workers)
    platforms = args.platforms.split(",")

    # When a version constraint is specified, fetch more releases (up to --max-releases) to filter
    only_latest = args.version_constraint is None

    mapping: dict[str, Releases | None] = {
        "dl.k8s.io": KubernetesReleases(pool=pool, only_latest=True),
        "github.com": GithubReleases(only_latest=True),
        "get.helm.sh": HelmReleases(only_latest=only_latest),
        "releases.hashicorp.com": None,  # TODO
        "raw.githubusercontent.com": None,  # TODO
        "binaries.pantsbuild.org": None,  # TODO
    }

    tools = {
        (path, class_name): get_class_variables(path, class_name, variables=Tool)
        for path, class_name in modules
    }

    futures = []
    for path, class_name in modules:
        tool = tools[(path, class_name)]

        platform_mapping = tool.default_url_platform_mapping

        domain = urlparse(tool.default_url_template).netloc
        releases = mapping[domain]
        if releases is None:
            logger.warning("can't get versions from %s, not implemented yet", domain)
            continue

        releases = list(releases.get_releases(tool.default_url_template))

        # Limit and filter releases by constraint before downloading binaries
        if args.version_constraint:
            releases = releases[: args.max_releases]
            specifier = SpecifierSet(args.version_constraint)
            releases = [v for v in releases if specifier.contains(v.lstrip("v"))]
            if not releases:
                logger.warning(
                    "No releases for %s match constraint %r, skipping",
                    class_name,
                    args.version_constraint,
                )
                continue

        for version in releases:
            for platform in platforms:
                futures.append(
                    pool.apply_async(
                        fetch_version,
                        kwds=dict(
                            path=path,
                            class_name=class_name,
                            version=version,
                            platform=platform,
                            url_template=tool.default_url_template,
                            platform_mapping=platform_mapping,
                            mode=args.mode,
                        ),
                    )
                )

    results: list[ToolVersion] = [
        result for future in tqdm(futures) if (result := future.get(timeout=60)) is not None
    ]
    results.sort(key=lambda e: (e.path, e.class_name, Version(e.version.version)))

    logger.debug("results: %s", results)

    for group, versions_ in groupby(results, key=lambda e: (e.path, e.class_name)):
        versions = list(versions_)
        tool = tools[group]

        existing_versions = {
            ExternalToolVersion.decode(version) for version in tool.default_known_versions
        }

        path, class_name = group

        external_versions = [v.version for v in versions]
        if args.version_constraint:
            external_versions = filter_versions_by_constraint(
                external_versions, args.version_constraint
            )
            if not external_versions:
                logger.warning(
                    "No fetched versions for %s match constraint %r, skipping",
                    class_name,
                    args.version_constraint,
                )
                continue

        fetched_versions = set(external_versions)

        known_versions = list(existing_versions | fetched_versions)
        known_versions.sort(key=lambda tu: (Version(tu.version), tu.platform), reverse=True)

        if args.version_constraint:
            # Only upgrade if the newest matching version is greater than current default
            filtered_versions = filter_versions_by_constraint(
                known_versions, args.version_constraint
            )
            current_default = Version(tool.default_version.lstrip("v"))
            newest_matching = Version(filtered_versions[0].version.lstrip("v"))
            if newest_matching > current_default:
                default_version = filtered_versions[0].version
            else:
                default_version = tool.default_version
        else:
            default_version = known_versions[0].version

        replace_class_variables(
            path,
            class_name,
            replacements={
                "default_version": default_version,
                "default_known_versions": [v.encode() for v in known_versions],
            },
        )


if __name__ == "__main__":
    main()
