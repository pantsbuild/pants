# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from collections.abc import Iterable
from functools import partial
from pathlib import PurePath
from typing import NamedTuple

import pytest

from pants.core.target_types import FileSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.engine.target import MultipleSourcesField, SourcesField
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *source_files_rules(),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
    )


class TargetSources(NamedTuple):
    source_root: str
    source_files: str | list[str]

    @property
    def full_paths(self) -> list[str]:
        return [
            PurePath(self.source_root, name).as_posix()
            for name in (
                self.source_files if isinstance(self.source_files, list) else (self.source_files,)
            )
        ]


SOURCES1 = TargetSources("src/python", ["s1.py", "s2.py", "s3.py"])
SOURCES2 = TargetSources("tests/python", ["t1.py", "t2.java"])
SOURCES3 = TargetSources("src/java", ["j1.java", "j2.java"])


def mock_sources_field(
    rule_runner: RuleRunner,
    sources: TargetSources,
    *,
    include_sources: bool = True,
    sources_field_cls: type[SourcesField] = MultipleSourcesField,
) -> SourcesField:
    sources_field = sources_field_cls(
        sources.source_files if include_sources else [],
        Address(sources.source_root, target_name="lib"),
    )
    rule_runner.write_files(dict.fromkeys(sources.full_paths, ""))
    return sources_field


def assert_sources_resolved(
    rule_runner: RuleRunner,
    sources_fields: Iterable[SourcesField],
    *,
    expected: Iterable[TargetSources],
    expected_unrooted: Iterable[str] = (),
) -> None:
    result = rule_runner.request(SourceFiles, [SourceFilesRequest(sources_fields)])
    assert list(result.snapshot.files) == sorted(
        set(itertools.chain.from_iterable(sources.full_paths for sources in expected))
    )
    assert list(result.unrooted_files) == sorted(expected_unrooted)


def test_address_specs(rule_runner: RuleRunner) -> None:
    mock_sources = partial(mock_sources_field, rule_runner)
    sources_field1 = mock_sources(SOURCES1)
    sources_field2 = mock_sources(SOURCES2)
    sources_field3 = mock_sources(SOURCES3)
    sources_field4 = mock_sources(SOURCES1)

    assert_sources = partial(assert_sources_resolved, rule_runner)
    assert_sources([sources_field1], expected=[SOURCES1])
    assert_sources([sources_field2], expected=[SOURCES2])
    assert_sources([sources_field3], expected=[SOURCES3])
    assert_sources([sources_field4], expected=[SOURCES1])

    # NB: sources_field1 and sources_field4 refer to the same files. We should be able to
    # handle this gracefully.
    assert_sources(
        [sources_field1, sources_field2, sources_field3, sources_field4],
        expected=[SOURCES1, SOURCES2, SOURCES3],
    )


def test_unrooted_sources(rule_runner: RuleRunner) -> None:
    """Any SourcesField with `uses_source_roots=False`, such as `FilesSources`, should be marked as
    unrooted sources."""
    sources = TargetSources("src/python", "README.md")
    field = mock_sources_field(rule_runner, sources, sources_field_cls=FileSourceField)
    assert_sources_resolved(
        rule_runner, [field], expected=[sources], expected_unrooted=sources.full_paths
    )

    class CustomSources(MultipleSourcesField):
        uses_source_roots = False

    sources = TargetSources("src/python", ["README.md"])
    field = mock_sources_field(rule_runner, sources, sources_field_cls=CustomSources)
    assert_sources_resolved(
        rule_runner, [field], expected=[sources], expected_unrooted=sources.full_paths
    )


def test_gracefully_handle_no_sources(rule_runner: RuleRunner) -> None:
    sources_field = mock_sources_field(rule_runner, SOURCES1, include_sources=False)
    assert_sources_resolved(rule_runner, [sources_field], expected=[])
