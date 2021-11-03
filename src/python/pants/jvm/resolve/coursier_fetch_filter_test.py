# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import DefaultDict, Sequence
from unittest import mock

import pytest

from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.jvm.resolve.coursier_fetch import (
    Coordinate,
    Coordinates,
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
    FilterDependenciesRequest,
)
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *util_rules(),
            QueryRule(CoursierResolvedLockfile, (FilterDependenciesRequest,)),
        ],
    )
    return rule_runner


coord1 = Coordinate("test", "art1", "1.0.0")
coord2 = Coordinate("test", "art2", "1.0.0")
coord3 = Coordinate("test", "art3", "1.0.0")
coord4 = Coordinate("test", "art4", "1.0.0")
coord5 = Coordinate("test", "art5", "1.0.0")


# No depedencies (coord1)
# 1 direct dependency, more transitive dependencies (coord2)
# 1 where direct dependencies provide no transitive dependencies (coord 4)
# 1 where direct dependencies provide repeated dependencies (coord5)
direct: dict[Coordinate, set[Coordinate]] = {
    coord1: set(),
    coord2: {
        coord3,
    },  # 1, 2, 3, 4, 5
    coord3: {coord1, coord4, coord5},  # 1, 3, 4, 5
    coord4: {
        coord1,
    },  # 1, 4
    coord5: {coord1, coord4},  # 1, 4, 5
}


@pytest.fixture
def lockfile() -> CoursierResolvedLockfile:

    # Calculate transitive deps
    transitive_ = {(i, k) for i, j in direct.items() for k in j}
    while True:
        old_len = len(transitive_)
        transitive_ |= {(i, k) for i, j in transitive_ for k in direct[j]}
        if old_len == len(transitive_):
            break
    transitive = DefaultDict(set)
    for (i, j) in transitive_:
        transitive[i].add(j)

    entries = (
        CoursierLockfileEntry(
            coord=coord,
            file_name=f"{coord.artifact}.jar",
            direct_dependencies=Coordinates(direct[coord]),
            dependencies=Coordinates(transitive[coord]),
            file_digest=mock.Mock(),
        )
        for coord in direct
    )

    return CoursierResolvedLockfile(entries=tuple(entries))


def test_no_deps(rule_runner: RuleRunner, lockfile: CoursierResolvedLockfile) -> None:
    filtered = filter(rule_runner, [coord1], lockfile, False)
    assert filtered == [coord1]


def test_filter_non_transitive_ignores_deps(
    rule_runner: RuleRunner, lockfile: CoursierResolvedLockfile
) -> None:
    filtered = filter(rule_runner, [coord2], lockfile, False)
    assert filtered == [coord2]


def test_filter_transitive_includes_transitive_deps(
    rule_runner: RuleRunner, lockfile: CoursierResolvedLockfile
) -> None:
    filtered = filter(rule_runner, [coord2], lockfile, True)
    assert set(filtered) == {coord1, coord2, coord3, coord4, coord5}
    # Entries should only appear once.
    assert len(filtered) == 5


def filter(rule_runner, coordinates, lockfile, transitive) -> Sequence[Coordinate]:
    filtered = rule_runner.request(
        CoursierResolvedLockfile,
        [FilterDependenciesRequest(Coordinates(coordinates), lockfile, transitive)],
    )
    return list(i.coord for i in filtered.entries)
