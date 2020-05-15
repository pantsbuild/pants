# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import unittest
from contextlib import contextmanager
from textwrap import dedent

from pants.base.exceptions import DuplicateNameError, UnaddressableObjectError
from pants.base.specs import AddressSpec, AddressSpecs, SingleAddress
from pants.build_graph.address import Address
from pants.engine.addresses import Addresses
from pants.engine.collection import Collection
from pants.engine.fs import create_fs_rules
from pants.engine.internals.build_files import create_graph_rules
from pants.engine.internals.examples.parsers import JsonParser
from pants.engine.internals.mapper import (
    AddressFamily,
    AddressMap,
    AddressMapper,
    DifferingFamiliesError,
)
from pants.engine.internals.parser import BuildFilePreludeSymbols, HydratedStruct, SymbolTable
from pants.engine.internals.scheduler_test_base import SchedulerTestBase
from pants.engine.internals.struct import Struct
from pants.engine.rules import rule
from pants.engine.selectors import Get, MultiGet
from pants.testutil.engine.util import TARGET_TABLE, Target
from pants.util.dirutil import safe_open
from pants.util.frozendict import FrozenDict


class Thing:
    def __init__(self, **kwargs):
        self._kwargs = kwargs

    def _asdict(self):
        return self._kwargs

    def _key(self):
        return {k: v for k, v in self._kwargs.items() if k != "type_alias"}

    def __eq__(self, other):
        return isinstance(other, Thing) and self._key() == other._key()


class AddressMapTest(unittest.TestCase):
    _parser = JsonParser(SymbolTable({"thing": Thing}))

    @contextmanager
    def parse_address_map(self, json):
        path = "/dev/null"
        address_map = AddressMap.parse(
            path, json, self._parser, BuildFilePreludeSymbols(FrozenDict())
        )
        self.assertEqual(path, address_map.path)
        yield address_map

    def test_parse(self) -> None:
        with self.parse_address_map(
            dedent(
                """
                {
                  "type_alias": "thing",
                  "name": "one",
                  "age": 42
                }
                {
                  "type_alias": "thing",
                  "name": "two",
                  "age": 37
                }
                """
            )
        ) as address_map:

            self.assertEqual(
                {"one": Thing(name="one", age=42), "two": Thing(name="two", age=37)},
                address_map.objects_by_name,
            )

    def test_not_serializable(self) -> None:
        with self.assertRaises(UnaddressableObjectError):
            with self.parse_address_map("{}"):
                self.fail()

    def test_not_named(self) -> None:
        with self.assertRaises(UnaddressableObjectError):
            with self.parse_address_map('{"type_alias": "thing"}'):
                self.fail()

    def test_duplicate_names(self) -> None:
        with self.assertRaises(DuplicateNameError):
            with self.parse_address_map(
                '{"type_alias": "thing", "name": "one"}' '{"type_alias": "thing", "name": "one"}'
            ):
                self.fail()


class AddressFamilyTest(unittest.TestCase):
    def test_create_single(self) -> None:
        address_family = AddressFamily.create(
            "",
            [AddressMap("0", {"one": Thing(name="one", age=42), "two": Thing(name="two", age=37)})],
        )
        self.assertEqual("", address_family.namespace)
        self.assertEqual(
            {
                Address.parse("//:one"): Thing(name="one", age=42),
                Address.parse("//:two"): Thing(name="two", age=37),
            },
            address_family.addressables,
        )

    def test_create_multiple(self) -> None:
        address_family = AddressFamily.create(
            "name/space",
            [
                AddressMap("name/space/0", {"one": Thing(name="one", age=42)}),
                AddressMap("name/space/1", {"two": Thing(name="two", age=37)}),
            ],
        )

        self.assertEqual("name/space", address_family.namespace)
        self.assertEqual(
            {
                Address.parse("name/space:one"): Thing(name="one", age=42),
                Address.parse("name/space:two"): Thing(name="two", age=37),
            },
            address_family.addressables,
        )

    def test_create_empty(self) -> None:
        # Case where directory exists but is empty.
        address_family = AddressFamily.create("name/space", [])
        self.assertEqual(dict(), address_family.addressables)

    def test_mismatching_paths(self) -> None:
        with self.assertRaises(DifferingFamiliesError):
            AddressFamily.create(
                "one", [AddressMap("/dev/null/one/0", {}), AddressMap("/dev/null/two/0", {})]
            )

    def test_duplicate_names(self) -> None:
        with self.assertRaises(DuplicateNameError):
            AddressFamily.create(
                "name/space",
                [
                    AddressMap("name/space/0", {"one": Thing(name="one", age=42)}),
                    AddressMap("name/space/1", {"one": Thing(name="one", age=37)}),
                ],
            )


class HydratedStructs(Collection[HydratedStruct]):
    pass


@rule
async def unhydrated_structs(addresses: Addresses) -> HydratedStructs:
    tacs = await MultiGet(Get[HydratedStruct](Address, a) for a in addresses)
    return HydratedStructs(tacs)


class AddressMapperTest(unittest.TestCase, SchedulerTestBase):
    def setUp(self) -> None:
        # Set up a scheduler that supports address mapping.
        address_mapper = AddressMapper(
            parser=JsonParser(TARGET_TABLE),
            prelude_glob_patterns=(),
            build_patterns=("*.BUILD.json",),
        )

        # We add the `unhydrated_structs` rule because it is otherwise not used in the core engine.
        rules = [unhydrated_structs] + create_fs_rules() + create_graph_rules(address_mapper)

        project_tree = self.mk_fs_tree(
            os.path.join(os.path.dirname(__file__), "examples/mapper_test")
        )
        self.build_root = project_tree.build_root
        self.scheduler = self.mk_scheduler(rules=rules, project_tree=project_tree)

        self.a_b = Address.parse("a/b")
        self.a_b_target = Target(
            address=self.a_b,
            dependencies=["//a/d/e"],
            configurations=["//a/d/e", Struct(embedded="yes")],
            type_alias="target",
        )

    def resolve(self, address_spec: AddressSpec):
        (tacs,) = self.scheduler.product_request(HydratedStructs, [AddressSpecs([address_spec])])
        return [tac.value for tac in tacs]

    def test_no_address_no_family(self) -> None:
        spec = SingleAddress("a/c", "c")

        # Does not exist.
        with self.assertRaises(Exception):
            self.resolve(spec)

        build_file = os.path.join(self.build_root, "a/c", "c.BUILD.json")
        with safe_open(build_file, "w") as fp:
            fp.write('{"type_alias": "struct", "name": "c"}')
        self.scheduler.invalidate_files(["a/c"])

        # Success.
        resolved = self.resolve(spec)
        self.assertEqual(1, len(resolved))
        self.assertEqual([Struct(address=Address.parse("a/c"), type_alias="struct")], resolved)

    def test_resolve(self) -> None:
        resolved = self.resolve(SingleAddress("a/b", "b"))
        self.assertEqual(1, len(resolved))
        self.assertEqual(self.a_b, resolved[0].address)
