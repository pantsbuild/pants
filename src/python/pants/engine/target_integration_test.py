# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Sequence, Type

from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.build_graph.address import Address
from pants.engine.internals import graph
from pants.engine.selectors import Params
from pants.engine.target import IntField, PluginField, StringField, Target, Targets
from pants.testutil.test_base import TestBase


class CustomField1(IntField):
    alias = "custom_field1"


class CustomField2(StringField):
    alias = "custom_field2"


class Target1(Target):
    alias = "target_1"
    core_fields = ()


class Target2(Target):
    alias = "target_2"
    core_fields = ()


class TargetTest(TestBase):
    @classmethod
    def target_types(cls) -> Sequence[Type[Target]]:
        return (Target1, Target2)

    @classmethod
    def rules(cls):
        return [
            *super().rules(),
            *graph.rules(),
            PluginField(Target1, CustomField1),
            PluginField(Target2, CustomField1),
            PluginField(Target2, CustomField2),
        ]

    def test_plugin_fields(self) -> None:
        self.add_to_build_file("a", "target_1(name='tgt', custom_field1=42)")
        self.add_to_build_file("b", "target_2(name='tgt', custom_field1=37, custom_field2='jake')")
        address_to_targets = {
            target.address: target
            for target in self.request_single_product(
                Targets, subject=Params(AddressSpecs([DescendantAddresses("")]))
            )
        }
        assert len(address_to_targets) == 2

        tgt_a = address_to_targets[Address.parse("a:tgt")]
        assert Target1 is type(tgt_a)
        assert tgt_a.has_field(CustomField1)
        assert not tgt_a.has_field(CustomField2)
        assert 42 == tgt_a[CustomField1].value

        tgt_b = address_to_targets[Address.parse("b:tgt")]
        assert Target2 is type(tgt_b)
        assert tgt_b.has_field(CustomField1)
        assert tgt_b.has_field(CustomField2)
        assert 37 == tgt_b[CustomField1].value
        assert "jake" == tgt_b[CustomField2].value
