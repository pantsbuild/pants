# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.core.util_rules.filter_empty_sources import (
    FieldSetsWithSources,
    FieldSetsWithSourcesRequest,
    TargetsWithSources,
    TargetsWithSourcesRequest,
)
from pants.core.util_rules.filter_empty_sources import rules as filter_empty_sources_rules
from pants.engine.addresses import Address
from pants.engine.target import FieldSet, Sources, Tags, Target
from pants.testutil.test_base import TestBase


class FilterEmptySourcesTest(TestBase):
    @classmethod
    def rules(cls):
        return (*super().rules(), *filter_empty_sources_rules())

    def test_filter_field_sets(self) -> None:
        @dataclass(frozen=True)
        class MockFieldSet(FieldSet):
            sources: Sources
            # Another field to demo that we will preserve the whole FieldSet data structure.
            tags: Tags

        self.create_file("f1.txt")
        valid_addr = Address.parse(":valid")
        valid_field_set = MockFieldSet(
            valid_addr, Sources(["f1.txt"], address=valid_addr), Tags(None, address=valid_addr)
        )

        empty_addr = Address.parse(":empty")
        empty_field_set = MockFieldSet(
            empty_addr, Sources(None, address=empty_addr), Tags(None, address=empty_addr)
        )

        result = self.request_single_product(
            FieldSetsWithSources, FieldSetsWithSourcesRequest([valid_field_set, empty_field_set]),
        )
        assert tuple(result) == (valid_field_set,)

    def test_filter_targets(self) -> None:
        class MockTarget(Target):
            alias = "target"
            core_fields = (Sources,)

        class MockTargetWithNoSourcesField(Target):
            alias = "no_sources"
            core_fields = ()

        self.create_file("f1.txt")
        valid_tgt = MockTarget({Sources.alias: ["f1.txt"]}, address=Address.parse(":valid"))
        empty_tgt = MockTarget({}, address=Address.parse(":empty"))
        invalid_tgt = MockTargetWithNoSourcesField({}, address=Address.parse(":invalid"))

        result = self.request_single_product(
            TargetsWithSources, TargetsWithSourcesRequest([valid_tgt, empty_tgt, invalid_tgt]),
        )
        assert tuple(result) == (valid_tgt,)
