# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Iterable, Type

import pytest

from pants.backend.debian.target_types import DebianSources
from pants.build_graph.address import Address
from pants.engine.rules import QueryRule
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    SourcesPaths,
    SourcesPathsRequest,
)
from pants.testutil.rule_runner import RuleRunner, engine_error


@pytest.fixture
def sources_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(SourcesPaths, [SourcesPathsRequest]),
        ]
    )


def test_sources_expected_num_files(sources_rule_runner: RuleRunner) -> None:
    sources_rule_runner.write_files(
        {
            f: ""
            for f in [
                "f1.txt",
                "f2.txt",
                "dirA/f3.txt",
                "dirB/f4.txt",
                "dirC/f5.txt",
                "dirC/f6.txt",
            ]
        }
    )

    def hydrate(sources_cls: Type[DebianSources], sources: Iterable[str]) -> HydratedSources:
        return sources_rule_runner.request(
            HydratedSources,
            [
                HydrateSourcesRequest(sources_cls(sources, Address("", target_name="example"))),
            ],
        )

    with engine_error(contains="must resolve to at least one file"):
        hydrate(DebianSources, [])

    with engine_error(contains="must resolve to at least one file"):
        hydrate(DebianSources, ["non-existing-dir/*"])

    with engine_error(contains="Individual files were found"):
        hydrate(DebianSources, ["f1.txt", "f2.txt"])

    with engine_error(contains="Multiple directories were found"):
        hydrate(DebianSources, ["dirA/f3.txt", "dirB/f4.txt"])

    # Also check that we support valid sources declarations.
    assert hydrate(DebianSources, ["dirC/f5.txt", "dirC/f6.txt"]).snapshot.files == (
        "dirC/f5.txt",
        "dirC/f6.txt",
    )
    assert hydrate(DebianSources, ["dirC/*"]).snapshot.files == ("dirC/f5.txt", "dirC/f6.txt")
