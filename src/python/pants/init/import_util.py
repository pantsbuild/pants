# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.metadata
import re
from collections.abc import Generator
from importlib.metadata import Distribution

from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version


def normalize_name(name: str) -> str:
    """Normalize package names in similar manner to `pkg_resources.safe_name`.

    Replace runs of non-alphanumeric characters with a single `-`. Convert to lower case since the
    official Python packaging regex for names is case-insensitive.
    """
    return re.sub("[^A-Za-z0-9.]+", "-", name).lower()


def distribution_matches_requirement(dist: Distribution, requirement: Requirement) -> bool:
    # Check whether the normalized names match.
    dist_name = normalize_name(dist.name)
    req_name = normalize_name(requirement.name)
    if dist_name != req_name:
        return False

    # If there is no version specifier, a name match is sufficient.
    if not requirement.specifier:
        return True

    # Otherwise, check version specifier and see if version is contained.
    try:
        dist_version = Version(dist.version)
        return requirement.specifier.contains(dist_version)
    except InvalidVersion:
        # If we can't parse the version, assume it doesn't match
        return False


def find_matching_distributions(
    requirement: Requirement | None,
) -> Generator[Distribution, None, None]:
    """Yield distributions matching the given requirement or all active distributions if
    `requirement` is `None`."""
    seen_dist_names: set[str] = set()
    for dist in importlib.metadata.distributions():
        # Skip non-active distributions. Python prefers the first distribution on `sys.path`.
        normalized_dist_name = normalize_name(dist.name)
        if normalized_dist_name in seen_dist_names:
            continue
        seen_dist_names.add(normalized_dist_name)
        if requirement is None or distribution_matches_requirement(dist, requirement):
            yield dist
