# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import doctest

import external_tool_upgrade
from external_tool_upgrade import ExternalToolVersion, filter_versions_by_constraint
from packaging.version import Version


def test_docs() -> None:
    failure_count, test_count = doctest.testmod(external_tool_upgrade)
    assert test_count > 0
    assert failure_count == 0


def test_filter_fetched_versions_with_constraint() -> None:
    fetched = [
        ExternalToolVersion("5.0", "linux_x86_64", "abc", 100),
        ExternalToolVersion("6.0", "linux_x86_64", "def", 200),
        ExternalToolVersion("6.1", "linux_x86_64", "ghi", 300),
    ]

    filtered = filter_versions_by_constraint(fetched, ">=6.0")

    assert len(filtered) == 2
    assert all(isinstance(v, ExternalToolVersion) for v in filtered)
    assert {v.version for v in filtered} == {"6.0", "6.1"}


def test_filter_versions_by_constraint_none() -> None:
    versions = [
        ExternalToolVersion("5.0", "cowsay", "abc", 100),
        ExternalToolVersion("6.0", "cowsay", "def", 200),
    ]
    result = filter_versions_by_constraint(versions, None)
    assert result == versions


def test_filter_versions_by_constraint_basic() -> None:
    versions = [
        ExternalToolVersion("3.0", "cowsay", "abc", 100),
        ExternalToolVersion("4.0", "cowsay", "def", 200),
        ExternalToolVersion("5.0", "cowsay", "ghi", 300),
    ]
    result = filter_versions_by_constraint(versions, ">=4.0,<5.0")
    assert len(result) == 1
    assert result[0].version == "4.0"


def test_filter_versions_by_constraint_with_v_prefix() -> None:
    versions = [
        ExternalToolVersion("v5.0", "cowsay", "abc", 100),
        ExternalToolVersion("v6.0", "cowsay", "def", 200),
    ]
    result = filter_versions_by_constraint(versions, ">5.0")
    assert len(result) == 1
    assert result[0].version == "v6.0"


def test_filter_versions_by_constraint_no_matches() -> None:
    versions = [
        ExternalToolVersion("6.1", "cowsay", "abc", 100),
    ]
    result = filter_versions_by_constraint(versions, ">7.0")
    assert result == []


def test_filter_versions_by_constraint_multiple_matches() -> None:
    versions = [
        ExternalToolVersion("3.0", "cowsay", "abc", 100),
        ExternalToolVersion("4.0", "cowsay", "def", 200),
        ExternalToolVersion("5.0", "cowsay", "ghi", 250),
        ExternalToolVersion("6.0", "cowsay", "jkl", 300),
    ]
    result = filter_versions_by_constraint(versions, ">4.0,<6.0")
    assert len(result) == 1
    assert result[0].version == "5.0"


def _select_default_version_with_constraint(
    known_versions: list[ExternalToolVersion],
    current_default: str,
    constraint: str,
) -> str:
    """Helper that mirrors the upgrade logic in main().

    Returns the new default_version based on the constraint and current default. Only upgrades if
    the newest matching version is greater than current default.
    """
    filtered = filter_versions_by_constraint(known_versions, constraint)
    if not filtered:
        return current_default

    current = Version(current_default.lstrip("v"))
    newest_matching = Version(filtered[0].version.lstrip("v"))

    if newest_matching > current:
        return filtered[0].version
    return current_default


def test_version_constraint_upgrades_when_newer_version_available() -> None:
    known_versions = [
        ExternalToolVersion("6.1", "cowsay", "abc", 100),
        ExternalToolVersion("6.0", "cowsay", "def", 200),
        ExternalToolVersion("5.0", "cowsay", "ghi", 300),
        ExternalToolVersion("4.0", "cowsay", "jkl", 400),
    ]
    current_default = "5.0"
    constraint = ">=6.0,<7"

    result = _select_default_version_with_constraint(known_versions, current_default, constraint)
    assert result == "6.1"


def test_version_constraint_no_upgrade_when_no_newer_matching_version() -> None:
    known_versions = [
        ExternalToolVersion("6.1", "cowsay", "abc", 100),
        ExternalToolVersion("6.0", "cowsay", "def", 200),
        ExternalToolVersion("5.0", "cowsay", "ghi", 300),
        ExternalToolVersion("4.0", "cowsay", "jkl", 400),
    ]
    current_default = "6.0"
    constraint = ">=3.0,<5.0"

    result = _select_default_version_with_constraint(known_versions, current_default, constraint)
    assert result == "6.0"


def test_version_constraint_no_upgrade_when_already_at_newest_matching() -> None:
    known_versions = [
        ExternalToolVersion("6.1", "cowsay", "abc", 100),
        ExternalToolVersion("6.0", "cowsay", "def", 200),
        ExternalToolVersion("5.0", "cowsay", "ghi", 300),
    ]
    current_default = "6.0"
    constraint = ">=5.0,<6.1"

    result = _select_default_version_with_constraint(known_versions, current_default, constraint)
    assert result == "6.0"


def test_version_constraint_with_v_prefix_upgrades_correctly() -> None:
    known_versions = [
        ExternalToolVersion("v6.0", "cowsay", "abc", 100),
        ExternalToolVersion("v5.0", "cowsay", "def", 200),
        ExternalToolVersion("v4.0", "cowsay", "ghi", 300),
    ]
    current_default = "v4.0"
    constraint = ">4.0,<6.0"

    result = _select_default_version_with_constraint(known_versions, current_default, constraint)
    assert result == "v5.0"
