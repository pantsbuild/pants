# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.build_graph.address import Address
from pants.engine.target import Configuration
from pants.engine.target import Sources as SourcesField
from pants.engine.target import Tags, Target
from pants.rules.core.filter_empty_sources import (
    ConfigurationsWithSources,
    ConfigurationsWithSourcesRequest,
    TargetsWithSources,
    TargetsWithSourcesRequest,
)
from pants.rules.core.filter_empty_sources import rules as filter_empty_sources_rules
from pants.testutil.test_base import TestBase


class FilterEmptySourcesTest(TestBase):
    @classmethod
    def rules(cls):
        return (*super().rules(), *filter_empty_sources_rules())

    def test_filter_configurations(self) -> None:
        @dataclass(frozen=True)
        class MockConfiguration(Configuration):
            sources: SourcesField
            # Another field to demo that we will preserve the whole Configuration data structure.
            tags: Tags

        self.create_file("f1.txt")
        valid_addr = Address.parse(":valid")
        valid_config = MockConfiguration(
            valid_addr, SourcesField(["f1.txt"], address=valid_addr), Tags(None, address=valid_addr)
        )

        empty_addr = Address.parse(":empty")
        empty_config = MockConfiguration(
            empty_addr, SourcesField(None, address=empty_addr), Tags(None, address=empty_addr)
        )

        result = self.request_single_product(
            ConfigurationsWithSources,
            ConfigurationsWithSourcesRequest([valid_config, empty_config]),
        )
        assert tuple(result) == (valid_config,)

    def test_filter_targets(self) -> None:
        class MockTarget(Target):
            alias = "target"
            core_fields = (SourcesField,)

        class MockTargetWithNoSourcesField(Target):
            alias = "no_sources"
            core_fields = ()

        self.create_file("f1.txt")
        valid_tgt = MockTarget({SourcesField.alias: ["f1.txt"]}, address=Address.parse(":valid"))
        empty_tgt = MockTarget({}, address=Address.parse(":empty"))
        invalid_tgt = MockTargetWithNoSourcesField({}, address=Address.parse(":invalid"))

        result = self.request_single_product(
            TargetsWithSources, TargetsWithSourcesRequest([valid_tgt, empty_tgt, invalid_tgt]),
        )
        assert tuple(result) == (valid_tgt,)
