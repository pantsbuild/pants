# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Script to fetch external tool versions.

Example:

pants run build-support/bin:external-tool-versions -- --tool pants.backend.k8s.kubectl_subsystem:Kubectl > list.txt
"""

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


@dataclass(frozen=True)
class ExternalToolVersion:
    version: str
    platform: str
    sha256: str
    filesize: int


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
    response = requests.get(url, allow_redirects=True)
    if response.status_code != 200:
        logger.debug("failed to fetch version: %s\n%s", version, response.text)
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

    with open(file_path, "w", encoding="utf-8") as file:
        for i, line in enumerate(lines):
            replaced = False
            for var, (start, end) in class_var_ranges.items():
                if start <= i <= end:
                    if i == start:
                        new_value = textwrap.indent(
                            f"{var} = {json.dumps(replacements[var])}\n",
                            "    ",
                        )
                        file.write(new_value)
                    replaced = True
                    break
            if not replaced:
                file.write(line)


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
            },
        )
    )

    logger.debug("modules: %s", modules)

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
                logger.debug("fetching version: %s %s", version, platform)
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
        known_versions = {
            # Parse versions to make sure that we don't make duplicates.
            tuple(map(str.strip, version.split("|")))
            for version in tool.default_known_versions
        }
        for version in versions:
            v = version.version
            known_versions.add(
                (
                    v.version,
                    v.platform,
                    v.sha256,
                    str(v.filesize),
                )
            )

        default_known_versions = sorted(known_versions, key=lambda tu: Version(tu[0]))

        path, class_name = group

        replace_class_variables(
            path,
            class_name,
            replacements={
                "default_known_versions": ["|".join(v) for v in default_known_versions],
            },
        )


if __name__ == "__main__":
    main()
