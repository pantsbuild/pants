# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Script to fetch external tool versions.

Example:

pants run build-support/bin:external-tool-versions -- --tool pants.backend.k8s.kubectl_subsystem:Kubectl > list.txt
"""

from __future__ import annotations

import json
from itertools import groupby
import ast
from dataclasses import dataclass
import os
from pathlib import Path
import argparse
import hashlib
import logging
import re
import textwrap
from typing import Any, Generator, NotRequired, Protocol, TypeVar
from collections.abc import Iterator
from multiprocessing.pool import ThreadPool
from string import Formatter
from urllib.parse import urlparse

import requests
from packaging.version import Version
from tqdm import tqdm

from external_tool.kubectl import KubernetesReleases
from external_tool.github import GithubReleases

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
    """Converts a format string to a regex.

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
    platform_mapping: dict[str, str],
) -> ToolVersion | None:
    url = url_template.format(version=version, platform=platform_mapping[platform])
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
    response = requests.get(url, headers=headers, allow_redirects=True)
    if response.status_code != 200:
        logger.debug("failed to fetch %s version %s: %s", class_name, version, response.text)
        return None

    size = len(response.content)
    sha256 = hashlib.sha256(response.content)
    return ToolVersion(
        path=path,
        class_name=class_name,
        version=ExternalToolVersion(
            version=version,
            platform=platform,
            filesize=size,
            sha256=sha256.hexdigest(),
        ),
    )


T = TypeVar("T")


def get_class_variables(file_path: Path, class_name: str, *, variables: type[T]) -> T:
    """Reads a Python file and retrieves the values of specified class variables."""

    logger.info("parsing %s variables in %s", class_name, file_path)
    with open(file_path, "r", encoding="utf-8") as file:
        source_code = file.read()

    tree = ast.parse(source_code)
    values = {}

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and target.id in variables.__annotations__:
                            values[target.id] = ast.literal_eval(stmt.value)

    return variables(**values)


def replace_class_variables(file_path: Path, class_name: str, replacements: dict[str, Any]) -> None:
    """Reads a Python file, searches for a class by name, and replaces specified class variables with new values."""
    with open(file_path, "r", encoding="utf-8") as file:
        lines = file.readlines()

    tree = ast.parse("".join(lines))

    class_var_ranges = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and target.id in replacements:
                            start_line = stmt.lineno - 1
                            end_line = (
                                stmt.end_lineno if hasattr(stmt, "end_lineno") else start_line
                            )
                            class_var_ranges[target.id] = (start_line, end_line)

    logger.debug("class_var_ranges: %s", class_var_ranges)

    prev_end = 0
    with open(file_path, "w", encoding="utf-8") as file:
        for var, (start, end) in class_var_ranges.items():
            file.writelines(lines[prev_end:start])
            line = textwrap.indent(
                f"{var} = {json.dumps(replacements[var], indent=4)}\n",
                "    ",
            )
            file.writelines([line])
            prev_end = end
        file.writelines(lines[prev_end:])


def find_modules_with_subclasses(
    directory: Path,
    *,
    base_classes: set[str],
    exclude: set[str],
) -> Generator[tuple[Path, str], None, None]:
    """Recursively finds Python modules that contain classes subclassing a given base class."""

    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                file_path = Path(root) / file
                source_code = file_path.read_text()

                tree = ast.parse(source_code)
                for node in tree.body:
                    if isinstance(node, ast.ClassDef) and node.name not in exclude:
                        for base in node.bases:
                            if isinstance(base, ast.Name) and base.id in base_classes:
                                yield file_path, node.name


@dataclass(frozen=True)
class Tool:
    default_known_versions: list[str]
    default_url_template: str
    default_url_platform_mapping: NotRequired[dict[str, str] | None] = None


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
        default=32,
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

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger(__name__).level = level

    modules = list(
        find_modules_with_subclasses(
            args.path,
            base_classes={
                "TemplatedExternalTool",
                "ExternalHelmPlugin",
            },
            exclude={
                "ExternalCCSubsystem",  # doesn't define default_url_template
                "ExternalHelmPlugin",  # is a base class itself
                "Shunit2",  # can't fetch git commits yet
                "TerraformTool",  # handled by a different script
            },
        )
    )

    logger.debug("found tools: %s", modules)

    pool = ThreadPool(processes=args.workers)
    platforms = args.platforms.split(",")

    mapping: dict[str, Releases | None] = {
        "dl.k8s.io": KubernetesReleases(pool=pool, only_latest=True),
        "github.com": GithubReleases(only_latest=True),
        "releases.hashicorp.com": None,  # TODO
        "raw.githubusercontent.com": None,  # TODO
        "get.helm.sh": None,  # TODO
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

        for version in releases.get_releases(tool.default_url_template):
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
        fetched_versions = {version.version for version in versions}

        known_versions = list(existing_versions | fetched_versions)
        known_versions.sort(key=lambda tu: (Version(tu.version), tu.platform))

        path, class_name = group

        replace_class_variables(
            path,
            class_name,
            replacements={
                "default_version": known_versions[-1].version,
                "default_known_versions": [v.encode() for v in known_versions],
            },
        )


if __name__ == "__main__":
    main()
