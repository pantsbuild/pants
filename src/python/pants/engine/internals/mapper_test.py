# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
from textwrap import dedent

import pytest

from pants.backend.project_info.filter_targets import FilterSubsystem, TargetGranularity
from pants.base.exceptions import MappingError
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.target_types import GenericTarget
from pants.engine.env_vars import EnvironmentVars
from pants.engine.internals.defaults import BuildFileDefaults, BuildFileDefaultsParserState
from pants.engine.internals.mapper import (
    AddressFamily,
    AddressMap,
    DifferingFamiliesError,
    DuplicateNameError,
    SpecsFilter,
)
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser, _UnrecognizedSymbol
from pants.engine.internals.target_adaptor import TargetAdaptor as _TargetAdaptor
from pants.engine.target import RegisteredTargetTypes, Tags, Target
from pants.engine.unions import UnionMembership
from pants.testutil.option_util import create_goal_subsystem
from pants.util.frozendict import FrozenDict

TargetAdaptor = functools.partial(_TargetAdaptor, __description_of_origin__="BUILD")


def parse_address_map(build_file: str, *, ignore_unrecognized_symbols: bool = False) -> AddressMap:
    path = "/dev/null"
    parser = Parser(
        build_root="",
        registered_target_types=RegisteredTargetTypes({"thing": GenericTarget}),
        union_membership=UnionMembership({}),
        object_aliases=BuildFileAliases(),
        ignore_unrecognized_symbols=ignore_unrecognized_symbols,
    )
    address_map = AddressMap.parse(
        path,
        build_file,
        parser,
        BuildFilePreludeSymbols(FrozenDict(), ()),
        EnvironmentVars({}),
        False,
        BuildFileDefaultsParserState.create(
            "", BuildFileDefaults({}), RegisteredTargetTypes({}), UnionMembership({})
        ),
        dependents_rules=None,
        dependencies_rules=None,
    )
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


def test_address_map_unrecognized_symbol() -> None:
    build_file = dedent(
        """
        thing(name="one")
        thing(name="bad", age=fake)
        thing(name="two")
        another_fake()
        yet_another()
        thing(name="three")
        and_finally(age=fakey)
        """
    )
    address_map = parse_address_map(build_file, ignore_unrecognized_symbols=True)
    assert {
        "one": TargetAdaptor(type_alias="thing", name="one"),
        "bad": TargetAdaptor(type_alias="thing", name="bad", age=_UnrecognizedSymbol("fake")),
        "two": TargetAdaptor(type_alias="thing", name="two"),
        "three": TargetAdaptor(
            type_alias="thing",
            name="three",
        ),
    } == address_map.name_to_target_adaptor
    with pytest.raises(MappingError):
        parse_address_map(build_file, ignore_unrecognized_symbols=False)


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


def test_specs_filter() -> None:
    class MockTgt1(Target):
        alias = "tgt1"
        core_fields = (Tags,)

    class MockTgt2(Target):
        alias = "tgt2"
        core_fields = (Tags,)

    specs_filter = SpecsFilter.create(
        create_goal_subsystem(
            FilterSubsystem,
            target_type=["tgt1"],
            tag_regex=[],
            address_regex=[],
            granularity=TargetGranularity.all_targets,
        ),
        RegisteredTargetTypes({"tgt1": MockTgt1, "tgt2": MockTgt2}),
        tags=["-a", "+b"],
    )

    def make_tgt1(name: str, tags: list[str] | None = None) -> MockTgt1:
        return MockTgt1({Tags.alias: tags}, Address("", target_name=name))

    def make_tgt2(name: str, tags: list[str] | None = None) -> MockTgt2:
        return MockTgt2({Tags.alias: tags}, Address("", target_name=name))

    untagged_tgt = make_tgt1(name="untagged")
    tagged_tgt = make_tgt1(name="tagged", tags=["b"])

    # Even though this has the tag `b`, it should be excluded because the target type.
    tgt2 = make_tgt2("tgt2", tags=["b"])

    def matches(tgt: Target) -> bool:
        return specs_filter.matches(tgt)

    assert matches(tagged_tgt) is True
    assert matches(untagged_tgt) is False
    assert matches(tgt2) is False
