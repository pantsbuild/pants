# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import unittest
from contextlib import contextmanager

from pants.base.build_root import BuildRoot
from pants.build_graph.address import (
    Address,
    BuildFileAddress,
    InvalidSpecPath,
    InvalidTargetName,
    parse_spec,
)
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import touch


class ParseSpecTest(unittest.TestCase):
    def test_parse_spec(self) -> None:
        spec_path, target_name = parse_spec("a/b/c")
        self.assertEqual(spec_path, "a/b/c")
        self.assertEqual(target_name, "c")

        spec_path, target_name = parse_spec("a/b/c:c")
        self.assertEqual(spec_path, "a/b/c")
        self.assertEqual(target_name, "c")

        spec_path, target_name = parse_spec(
            "a/b/c", relative_to="here"
        )  # no effect - we have a path
        self.assertEqual(spec_path, "a/b/c")
        self.assertEqual(target_name, "c")

    def test_parse_local_spec(self) -> None:
        spec_path, target_name = parse_spec(":c")
        self.assertEqual(spec_path, "")
        self.assertEqual(target_name, "c")

        spec_path, target_name = parse_spec(":c", relative_to="here")
        self.assertEqual(spec_path, "here")
        self.assertEqual(target_name, "c")

    def test_parse_absolute_spec(self) -> None:
        spec_path, target_name = parse_spec("//a/b/c")
        self.assertEqual(spec_path, "a/b/c")
        self.assertEqual(target_name, "c")

        spec_path, target_name = parse_spec("//a/b/c:c")
        self.assertEqual(spec_path, "a/b/c")
        self.assertEqual(target_name, "c")

        spec_path, target_name = parse_spec("//:c")
        self.assertEqual(spec_path, "")
        self.assertEqual(target_name, "c")

    def test_parse_bad_spec_non_normalized(self) -> None:
        self.do_test_bad_spec_path("..")
        self.do_test_bad_spec_path(".")

        self.do_test_bad_spec_path("//..")
        self.do_test_bad_spec_path("//.")

        self.do_test_bad_spec_path("a/.")
        self.do_test_bad_spec_path("a/..")
        self.do_test_bad_spec_path("../a")
        self.do_test_bad_spec_path("a/../a")

        self.do_test_bad_spec_path("a/")
        self.do_test_bad_spec_path("a/b/")

    def test_parse_bad_spec_bad_path(self) -> None:
        self.do_test_bad_spec_path("/a")
        self.do_test_bad_spec_path("///a")

    def test_parse_bad_spec_bad_name(self) -> None:
        self.do_test_bad_target_name("a:")
        self.do_test_bad_target_name("a::")
        self.do_test_bad_target_name("//")

    def test_parse_bad_spec_build_trailing_path_component(self) -> None:
        self.do_test_bad_spec_path("BUILD")
        self.do_test_bad_spec_path("BUILD.suffix")
        self.do_test_bad_spec_path("//BUILD")
        self.do_test_bad_spec_path("//BUILD.suffix")
        self.do_test_bad_spec_path("a/BUILD")
        self.do_test_bad_spec_path("a/BUILD.suffix")
        self.do_test_bad_spec_path("//a/BUILD")
        self.do_test_bad_spec_path("//a/BUILD.suffix")
        self.do_test_bad_spec_path("a/BUILD:b")
        self.do_test_bad_spec_path("a/BUILD.suffix:b")
        self.do_test_bad_spec_path("//a/BUILD:b")
        self.do_test_bad_spec_path("//a/BUILD.suffix:b")

    def test_banned_chars_in_target_name(self) -> None:
        with self.assertRaises(InvalidTargetName):
            Address(*parse_spec("a/b:c@d"))

    def do_test_bad_spec_path(self, spec: str) -> None:
        with self.assertRaises(InvalidSpecPath):
            Address(*parse_spec(spec))

    def do_test_bad_target_name(self, spec: str) -> None:
        with self.assertRaises(InvalidTargetName):
            Address(*parse_spec(spec))

    def test_subproject_spec(self) -> None:
        # Ensure that a spec referring to a subproject gets assigned to that subproject properly.
        def parse(spec, relative_to):
            return parse_spec(
                spec,
                relative_to=relative_to,
                subproject_roots=["subprojectA", "path/to/subprojectB"],
            )

        # Ensure that a spec in subprojectA is determined correctly.
        spec_path, target_name = parse("src/python/alib", "subprojectA/src/python")
        self.assertEqual("subprojectA/src/python/alib", spec_path)
        self.assertEqual("alib", target_name)

        spec_path, target_name = parse("src/python/alib:jake", "subprojectA/src/python/alib")
        self.assertEqual("subprojectA/src/python/alib", spec_path)
        self.assertEqual("jake", target_name)

        spec_path, target_name = parse(":rel", "subprojectA/src/python/alib")
        self.assertEqual("subprojectA/src/python/alib", spec_path)
        self.assertEqual("rel", target_name)

        # Ensure that a spec in subprojectB, which is more complex, is correct.
        spec_path, target_name = parse("src/python/blib", "path/to/subprojectB/src/python")
        self.assertEqual("path/to/subprojectB/src/python/blib", spec_path)
        self.assertEqual("blib", target_name)

        spec_path, target_name = parse(
            "src/python/blib:jane", "path/to/subprojectB/src/python/blib"
        )
        self.assertEqual("path/to/subprojectB/src/python/blib", spec_path)
        self.assertEqual("jane", target_name)

        spec_path, target_name = parse(":rel", "path/to/subprojectB/src/python/blib")
        self.assertEqual("path/to/subprojectB/src/python/blib", spec_path)
        self.assertEqual("rel", target_name)

        # Ensure that a spec in the parent project is not mapped.
        spec_path, target_name = parse("src/python/parent", "src/python")
        self.assertEqual("src/python/parent", spec_path)
        self.assertEqual("parent", target_name)

        spec_path, target_name = parse("src/python/parent:george", "src/python")
        self.assertEqual("src/python/parent", spec_path)
        self.assertEqual("george", target_name)

        spec_path, target_name = parse(":rel", "src/python/parent")
        self.assertEqual("src/python/parent", spec_path)
        self.assertEqual("rel", target_name)


class BaseAddressTest(unittest.TestCase):
    @contextmanager
    def workspace(self, *buildfiles):
        with temporary_dir() as root_dir:
            with BuildRoot().temporary(root_dir):
                with pushd(root_dir):
                    for buildfile in buildfiles:
                        touch(os.path.join(root_dir, buildfile))
                    yield os.path.realpath(root_dir)

    def assert_address(self, spec_path: str, target_name: str, address: Address) -> None:
        self.assertEqual(spec_path, address.spec_path)
        self.assertEqual(target_name, address.target_name)


class AddressTest(BaseAddressTest):
    def test_equivalence(self) -> None:
        self.assertNotEqual("Not really an address", Address("a/b", "c"))

        self.assertEqual(Address("a/b", "c"), Address("a/b", "c"))
        self.assertEqual(Address("a/b", "c"), Address.parse("a/b:c"))
        self.assertEqual(Address.parse("a/b:c"), Address.parse("a/b:c"))

    def test_parse(self) -> None:
        self.assert_address("a/b", "target", Address.parse("a/b:target"))
        self.assert_address("a/b", "target", Address.parse("//a/b:target"))
        self.assert_address("a/b", "b", Address.parse("a/b"))
        self.assert_address("a/b", "b", Address.parse("//a/b"))
        self.assert_address("a/b", "target", Address.parse(":target", relative_to="a/b"))
        self.assert_address("", "target", Address.parse("//:target", relative_to="a/b"))
        self.assert_address("", "target", Address.parse(":target"))
        self.assert_address("a/b", "target", Address.parse(":target", relative_to="a/b"))


def test_build_file_address() -> None:
    bfa = BuildFileAddress(rel_path="dir/BUILD", target_name="example")
    assert bfa.spec == "dir:example"
    assert bfa.to_address() == Address("dir", "example")
