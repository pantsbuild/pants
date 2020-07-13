# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.build_graph.address import (
    Address,
    BuildFileAddress,
    InvalidSpecPath,
    InvalidTargetName,
    parse_spec,
)


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


def test_address_equality() -> None:
    assert "Not really an address" != Address("a/b", "c")

    assert Address("a/b", "c") == Address("a/b", "c")
    assert Address("a/b", "c") == Address.parse("a/b:c")
    assert Address.parse("a/b:c") == Address.parse("a/b:c")

    assert Address("a/b", "c") != Address("a/b", "c", generated_base_target_name="original")
    assert Address("a/b", "c", generated_base_target_name="original") == Address(
        "a/b", "c", generated_base_target_name="original"
    )


def test_address_spec() -> None:
    normal_addr = Address("a/b", "c")
    assert normal_addr.spec == "a/b:c" == str(normal_addr) == normal_addr.reference()
    assert normal_addr.relative_spec == ":c"
    assert normal_addr.path_safe_spec == "a.b.c"

    top_level_addr = Address("", "root")
    assert top_level_addr.spec == "//:root" == str(top_level_addr) == top_level_addr.reference()
    assert top_level_addr.relative_spec == ":root"
    assert top_level_addr.path_safe_spec == ".root"

    generated_addr = Address("a/b", "c.txt", generated_base_target_name="c")
    assert generated_addr.spec == "a/b/c.txt" == str(generated_addr) == generated_addr.reference()
    assert generated_addr.relative_spec == "c.txt"
    assert generated_addr.path_safe_spec == "a.b.c.txt"

    top_level_generated_addr = Address("", "root.txt", generated_base_target_name="root")
    assert (
        top_level_generated_addr.spec
        == "//root.txt"
        == str(top_level_generated_addr)
        == top_level_generated_addr.reference()
    )
    assert top_level_generated_addr.relative_spec == "root.txt"
    assert top_level_generated_addr.path_safe_spec == ".root.txt"

    generated_subdirectory_addr = Address(
        "a/b", "subdir/c.txt", generated_base_target_name="original"
    )
    assert (
        generated_subdirectory_addr.spec
        == "a/b/subdir/c.txt"
        == str(generated_subdirectory_addr)
        == generated_subdirectory_addr.reference()
        # NB: A relative spec is not safe, so we use the full spec.
        == generated_subdirectory_addr.relative_spec
    )
    assert generated_subdirectory_addr.path_safe_spec == "a.b.subdir.c.txt"


def test_address_parse_method() -> None:
    def assert_parsed(spec_path: str, target_name: str, address: Address) -> None:
        assert spec_path == address.spec_path
        assert target_name == address.target_name

    assert_parsed("a/b", "target", Address.parse("a/b:target"))
    assert_parsed("a/b", "target", Address.parse("//a/b:target"))
    assert_parsed("a/b", "b", Address.parse("a/b"))
    assert_parsed("a/b", "b", Address.parse("//a/b"))
    assert_parsed("a/b", "target", Address.parse(":target", relative_to="a/b"))
    assert_parsed("", "target", Address.parse("//:target", relative_to="a/b"))
    assert_parsed("", "target", Address.parse(":target"))
    assert_parsed("a/b", "target", Address.parse(":target", relative_to="a/b"))

    # Do not attempt to parse generated subtargets, as we would have no way to find the
    # generated_base_target_name.
    assert_parsed("a/b/f.py", "f.py", Address.parse("a/b/f.py"))


def test_build_file_address() -> None:
    bfa = BuildFileAddress(rel_path="dir/BUILD", target_name="example")
    assert bfa.spec == "dir:example"
    assert bfa == Address("dir", "example")
    assert type(bfa.to_address()) is Address
    assert bfa.to_address() == Address("dir", "example")

    generated_bfa = BuildFileAddress(
        rel_path="dir/BUILD", target_name="example.txt", generated_base_target_name="original"
    )
    assert generated_bfa != BuildFileAddress(rel_path="dir/BUILD", target_name="example.txt")
    assert generated_bfa == Address("dir", "example.txt", generated_base_target_name="original")
    assert generated_bfa.spec == "dir/example.txt"
