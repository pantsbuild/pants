# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import OrderedDict
from dataclasses import dataclass
from typing import ClassVar, List

from pants.engine.rules import UnionMembership
from pants.engine.target import PluginField, PrimitiveField, Target
from pants.util.memo import memoized_property
from pants.util.ordered_set import OrderedSet


@dataclass(frozen=True)
class HaskellGhcExtensions(PrimitiveField):
    alias: ClassVar = "ghc_extensions"
    unhydrated: List[str]

    @memoized_property
    def hydrated(self) -> List[str]:
        return self.unhydrated


class HaskellField(PluginField):
    pass


class HaskellTarget(Target):
    alias: ClassVar = "haskell"
    core_fields: ClassVar = (HaskellGhcExtensions,)
    plugin_field_type: ClassVar = HaskellField


def test_add_custom_fields() -> None:
    @dataclass(frozen=True)
    class CustomField(PrimitiveField):
        alias: ClassVar = "custom_field"
        unhydrated: bool

        @memoized_property
        def hydrated(self) -> bool:
            return self.unhydrated

    tgt = HaskellTarget(
        union_membership=UnionMembership(OrderedDict({HaskellField: OrderedSet([CustomField])}))
    )
    assert tgt.field_types == (HaskellGhcExtensions, CustomField)
    assert tgt.core_fields == (HaskellGhcExtensions,)
    assert tgt.plugin_fields == (CustomField,)
