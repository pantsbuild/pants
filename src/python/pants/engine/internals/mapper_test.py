# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.mapper import (
    AddressFamily,
    AddressMap,
    AddressSpecsFilter,
    DifferingFamiliesError,
    DuplicateNameError,
)
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.util.frozendict import FrozenDict


def parse_address_map(build_file: str) -> AddressMap:
    path = "/dev/null"
    parser = Parser(target_type_aliases=["thing"], object_aliases=BuildFileAliases())
    address_map = AddressMap.parse(path, build_file, parser, BuildFilePreludeSymbols(FrozenDict()))
    assert path == address_map.path
    return address_map


def test_address_map_parse() -> None:
    address_map = parse_address_map(
        dedent(
            """
            thing(
              name="one",
              age=42,
            )

            thing(
              name="two",
              age=37,
            )
            """
        )
    )
    assert {
        "one": TargetAdaptor(type_alias="thing", name="one", age=42),
        "two": TargetAdaptor(type_alias="thing", name="two", age=37),
    } == address_map.name_to_target_adaptor


def test_address_map_duplicate_names() -> None:
    with pytest.raises(DuplicateNameError):
        parse_address_map("thing(name='one')\nthing(name='one')")


def test_address_family_create_single() -> None:
    address_family = AddressFamily.create(
        "",
        [
            AddressMap(
                "0",
                {
                    "one": TargetAdaptor(type_alias="thing", name="one", age=42),
                    "two": TargetAdaptor(type_alias="thing", name="two", age=37),
                },
            )
        ],
    )
    assert "" == address_family.namespace
    assert {
        Address("", target_name="one"): TargetAdaptor(type_alias="thing", name="one", age=42),
        Address("", target_name="two"): TargetAdaptor(type_alias="thing", name="two", age=37),
    } == dict(address_family.addresses_to_target_adaptors.items())


def test_address_family_create_multiple() -> None:
    address_family = AddressFamily.create(
        "name/space",
        [
            AddressMap(
                "name/space/0", {"one": TargetAdaptor(type_alias="thing", name="one", age=42)}
            ),
            AddressMap(
                "name/space/1", {"two": TargetAdaptor(type_alias="thing", name="two", age=37)}
            ),
        ],
    )

    assert "name/space" == address_family.namespace
    assert {
        Address("name/space", target_name="one"): TargetAdaptor(
            type_alias="thing", name="one", age=42
        ),
        Address("name/space", target_name="two"): TargetAdaptor(
            type_alias="thing", name="two", age=37
        ),
    } == dict(address_family.addresses_to_target_adaptors.items())


def test_address_family_create_empty() -> None:
    # Case where directory exists but is empty.
    address_family = AddressFamily.create("name/space", [])
    assert {} == address_family.addresses_to_target_adaptors
    assert () == address_family.build_file_addresses


def test_address_family_mismatching_paths() -> None:
    with pytest.raises(DifferingFamiliesError):
        AddressFamily.create(
            "one", [AddressMap("/dev/null/one/0", {}), AddressMap("/dev/null/two/0", {})]
        )


def test_address_family_duplicate_names() -> None:
    with pytest.raises(DuplicateNameError):
        AddressFamily.create(
            "name/space",
            [
                AddressMap(
                    "name/space/0", {"one": TargetAdaptor(type_alias="thing", name="one", age=42)}
                ),
                AddressMap(
                    "name/space/1", {"one": TargetAdaptor(type_alias="thing", name="one", age=37)}
                ),
            ],
        )


def test_address_specs_filter() -> None:
    def make_target(target_name: str, **kwargs) -> TargetAdaptor:
        parsed_address = Address("", target_name=target_name)
        return TargetAdaptor(
            type_alias="", name=parsed_address.target_name, address=parsed_address, **kwargs
        )

    untagged_target = make_target(target_name="untagged")
    b_tagged_target = make_target(target_name="b-tagged", tags=["b"])
    a_and_b_tagged_target = make_target(target_name="a-and-b-tagged", tags=["a", "b"])
    none_tagged_target = make_target(target_name="none-tagged-target", tags=None)

    specs_filter = AddressSpecsFilter(tags=["-a", "+b"])

    def matches(tgt: TargetAdaptor) -> bool:
        return specs_filter.matches(tgt.kwargs["address"], tgt)

    assert matches(untagged_target) is False
    assert matches(b_tagged_target) is True
    assert matches(a_and_b_tagged_target) is False
    assert matches(none_tagged_target) is False
