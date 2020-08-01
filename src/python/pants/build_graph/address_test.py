# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.build_graph.address import Address, AddressInput, InvalidSpecPath, InvalidTargetName
from pants.testutil.test_base import TestBase


class AddressTest(TestBase):
    def test_parse_spec(self) -> None:
        ai = AddressInput.parse("a/b/c")
        self.assertEqual(ai.path_component, "a/b/c")
        self.assertEqual(ai.target_component, "c")

        ai = AddressInput.parse("a/b/c:c")
        self.assertEqual(ai.path_component, "a/b/c")
        self.assertEqual(ai.target_component, "c")

        ai = AddressInput.parse("a/b/c", relative_to="here")  # no effect - we have a path
        self.assertEqual(ai.path_component, "a/b/c")
        self.assertEqual(ai.target_component, "c")

    def test_parse_local_spec(self) -> None:
        ai = AddressInput.parse(":c")
        self.assertEqual(ai.path_component, "")
        self.assertEqual(ai.target_component, "c")

        ai = AddressInput.parse(":c", relative_to="here")
        self.assertEqual(ai.path_component, "here")
        self.assertEqual(ai.target_component, "c")

    def test_parse_absolute_spec(self) -> None:
        ai = AddressInput.parse("//a/b/c")
        self.assertEqual(ai.path_component, "a/b/c")
        self.assertEqual(ai.target_component, "c")

        ai = AddressInput.parse("//a/b/c:c")
        self.assertEqual(ai.path_component, "a/b/c")
        self.assertEqual(ai.target_component, "c")

        ai = AddressInput.parse("//:c")
        self.assertEqual(ai.path_component, "")
        self.assertEqual(ai.target_component, "c")

    def test_parse_bad_spec_non_normalized(self) -> None:
        self.do_test_bad_path_component("..")
        self.do_test_bad_path_component(".")

        self.do_test_bad_path_component("//..")
        self.do_test_bad_path_component("//.")

        self.do_test_bad_path_component("a/.")
        self.do_test_bad_path_component("a/..")
        self.do_test_bad_path_component("../a")
        self.do_test_bad_path_component("a/../a")

        self.do_test_bad_path_component("a/:a")
        self.do_test_bad_path_component("a/b/:b")

    def test_parse_bad_spec_bad_path(self) -> None:
        self.do_test_bad_path_component("/a")
        self.do_test_bad_path_component("///a")

    def test_parse_bad_spec_bad_name(self) -> None:
        self.do_test_bad_target_component("a:")
        self.do_test_bad_target_component("a::")
        self.do_test_bad_target_component("//")

    def test_parse_bad_spec_build_trailing_path_component(self) -> None:
        self.do_test_bad_path_component("BUILD")
        self.do_test_bad_path_component("BUILD.suffix")
        self.do_test_bad_path_component("//BUILD")
        self.do_test_bad_path_component("//BUILD.suffix")
        self.do_test_bad_path_component("a/BUILD")
        self.do_test_bad_path_component("a/BUILD.suffix")
        self.do_test_bad_path_component("//a/BUILD")
        self.do_test_bad_path_component("//a/BUILD.suffix")
        self.do_test_bad_path_component("a/BUILD:b")
        self.do_test_bad_path_component("a/BUILD.suffix:b")
        self.do_test_bad_path_component("//a/BUILD:b")
        self.do_test_bad_path_component("//a/BUILD.suffix:b")

    def test_banned_chars_in_target_component(self) -> None:
        with self.assertRaises(InvalidTargetName):
            AddressInput.parse("a/b:c@d")

    def do_test_bad_path_component(self, spec: str) -> None:
        with self.assertRaises(InvalidSpecPath):
            AddressInput.parse(spec)

    def do_test_bad_target_component(self, spec: str) -> None:
        with self.assertRaises(InvalidTargetName):
            AddressInput.parse(spec)

    def test_subproject_spec(self) -> None:
        # Ensure that a spec referring to a subproject gets assigned to that subproject properly.
        def parse(spec, relative_to):
            return AddressInput.parse(
                spec,
                relative_to=relative_to,
                subproject_roots=["subprojectA", "path/to/subprojectB"],
            )

        # Ensure that a spec in subprojectA is determined correctly.
        ai = parse("src/python/alib", "subprojectA/src/python")
        self.assertEqual("subprojectA/src/python/alib", ai.path_component)
        self.assertEqual("alib", ai.target_component)

        ai = parse("src/python/alib:jake", "subprojectA/src/python/alib")
        self.assertEqual("subprojectA/src/python/alib", ai.path_component)
        self.assertEqual("jake", ai.target_component)

        ai = parse(":rel", "subprojectA/src/python/alib")
        self.assertEqual("subprojectA/src/python/alib", ai.path_component)
        self.assertEqual("rel", ai.target_component)

        # Ensure that a spec in subprojectB, which is more complex, is correct.
        ai = parse("src/python/blib", "path/to/subprojectB/src/python")
        self.assertEqual("path/to/subprojectB/src/python/blib", ai.path_component)
        self.assertEqual("blib", ai.target_component)

        ai = parse("src/python/blib:jane", "path/to/subprojectB/src/python/blib")
        self.assertEqual("path/to/subprojectB/src/python/blib", ai.path_component)
        self.assertEqual("jane", ai.target_component)

        ai = parse(":rel", "path/to/subprojectB/src/python/blib")
        self.assertEqual("path/to/subprojectB/src/python/blib", ai.path_component)
        self.assertEqual("rel", ai.target_component)

        # Ensure that a spec in the parent project is not mapped.
        ai = parse("src/python/parent", "src/python")
        self.assertEqual("src/python/parent", ai.path_component)
        self.assertEqual("parent", ai.target_component)

        ai = parse("src/python/parent:george", "src/python")
        self.assertEqual("src/python/parent", ai.path_component)
        self.assertEqual("george", ai.target_component)

        ai = parse(":rel", "src/python/parent")
        self.assertEqual("src/python/parent", ai.path_component)
        self.assertEqual("rel", ai.target_component)


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
    assert generated_addr.relative_spec == "./c.txt"
    assert generated_addr.path_safe_spec == "a.b.c.txt"

    top_level_generated_addr = Address("", "root.txt", generated_base_target_name="root")
    assert (
        top_level_generated_addr.spec
        == "//root.txt"
        == str(top_level_generated_addr)
        == top_level_generated_addr.reference()
    )
    assert top_level_generated_addr.relative_spec == "./root.txt"
    assert top_level_generated_addr.path_safe_spec == ".root.txt"

    generated_subdirectory_addr = Address(
        "a/b", "subdir/c.txt", generated_base_target_name="original"
    )
    assert (
        generated_subdirectory_addr.spec
        == "a/b/subdir/c.txt"
        == str(generated_subdirectory_addr)
        == generated_subdirectory_addr.reference()
    )
    assert generated_subdirectory_addr.relative_spec == "./subdir/c.txt"
    assert generated_subdirectory_addr.path_safe_spec == "a.b.subdir.c.txt"


def test_address_maybe_convert_to_base_target() -> None:
    generated_addr = Address("a/b", "c.txt", generated_base_target_name="c")
    assert generated_addr.maybe_convert_to_base_target() == Address("a/b", "c")

    normal_addr = Address("a/b", "c")
    assert normal_addr.maybe_convert_to_base_target() is normal_addr


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
