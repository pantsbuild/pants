# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.build_graph.address import Address
from pants.engine.target import Sources as SourcesField
from pants.engine.target import Tags
from pants.rules.core.configurations_with_sources import (
    ConfigurationsWithSources,
    ConfigurationsWithSourcesRequest,
)
from pants.rules.core.configurations_with_sources import rules as configurations_with_sources_rules
from pants.testutil.test_base import TestBase


@dataclass(frozen=True)
class MockConfiguration:
    sources: SourcesField
    # Another field to demo that we will preserve the whole Configuration data structure.
    tags: Tags


class ConfigurationsWithSourcesTest(TestBase):
    @classmethod
    def rules(cls):
        return (*super().rules(), *configurations_with_sources_rules())

    def test_filter_configurations_with_sources(self) -> None:
        self.create_file("f1.txt")
        valid_addr = Address.parse(":valid")
        valid_config = MockConfiguration(
            SourcesField(["f1.txt"], address=valid_addr), Tags(None, address=valid_addr)
        )

        invalid_addr = Address.parse(":invalid")
        invalid_config = MockConfiguration(
            SourcesField(None, address=invalid_addr), Tags(None, address=invalid_addr)
        )

        result = self.request_single_product(
            ConfigurationsWithSources,
            ConfigurationsWithSourcesRequest([valid_config, invalid_config]),
        )
        assert result.configs == (valid_config,)
