# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.base.exceptions import DuplicateNameError
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.mapper import AddressFamily, AddressMap, DifferingFamiliesError
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser, SymbolTable
from pants.engine.internals.struct import TargetAdaptor
from pants.util.frozendict import FrozenDict


class Thing(TargetAdaptor):
    def _key(self):
        return {k: v for k, v in self._kwargs.items() if k != "type_alias"}

    def __eq__(self, other):
        return isinstance(other, Thing) and self._key() == other._key()


def parse_address_map(build_file: str) -> AddressMap:
    path = "/dev/null"
    parser = Parser(SymbolTable({"thing": Thing}), BuildFileAliases())
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
        "one": Thing(name="one", age=42),
        "two": Thing(name="two", age=37),
    } == address_map.name_to_target_adaptor


def test_address_map_duplicate_names() -> None:
    with pytest.raises(DuplicateNameError):
        parse_address_map("thing(name='one')\nthing(name='one')")


def test_address_family_create_single() -> None:
    address_family = AddressFamily.create(
        "", [AddressMap("0", {"one": Thing(name="one", age=42), "two": Thing(name="two", age=37)})],
    )
    assert "" == address_family.namespace
    assert {
        Address.parse("//:one"): Thing(name="one", age=42),
        Address.parse("//:two"): Thing(name="two", age=37),
    } == address_family.addressables


def test_address_family_create_multiple() -> None:
    address_family = AddressFamily.create(
        "name/space",
        [
            AddressMap("name/space/0", {"one": Thing(name="one", age=42)}),
            AddressMap("name/space/1", {"two": Thing(name="two", age=37)}),
        ],
    )

    assert "name/space" == address_family.namespace
    assert {
        Address.parse("name/space:one"): Thing(name="one", age=42),
        Address.parse("name/space:two"): Thing(name="two", age=37),
    } == address_family.addressables


def test_address_family_create_empty() -> None:
    # Case where directory exists but is empty.
    address_family = AddressFamily.create("name/space", [])
    assert {} == address_family.addressables


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
                AddressMap("name/space/0", {"one": Thing(name="one", age=42)}),
                AddressMap("name/space/1", {"one": Thing(name="one", age=37)}),
            ],
        )
