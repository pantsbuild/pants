# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional

import pytest

from pants.build_graph.address import Address, AddressInput, InvalidSpecPath, InvalidTargetName


def assert_address_input_parsed(
    spec: str,
    *,
    path_component: str,
    target_component: Optional[str],
    relative_to: Optional[str] = None
) -> None:
    ai = AddressInput.parse(spec, relative_to=relative_to)
    assert ai.path_component == path_component
    if target_component is None:
        assert ai.target_component is None
    else:
        assert ai.target_component == target_component


def test_address_input_parse_spec() -> None:
    assert_address_input_parsed("a/b/c", path_component="a/b/c", target_component=None)
    assert_address_input_parsed("a/b/c:c", path_component="a/b/c", target_component="c")
    # The relative_to has no effect because we have a path.
    assert_address_input_parsed(
        "a/b/c", relative_to="here", path_component="a/b/c", target_component=None
    )

    # Relative address spec
    assert_address_input_parsed(":c", path_component="", target_component="c")
    assert_address_input_parsed(
        ":c", relative_to="here", path_component="here", target_component="c"
    )
    assert_address_input_parsed("//:c", relative_to="here", path_component="", target_component="c")

    # Absolute spec
    assert_address_input_parsed("//a/b/c", path_component="a/b/c", target_component=None)
    assert_address_input_parsed("//a/b/c:c", path_component="a/b/c", target_component="c")
    assert_address_input_parsed("//:c", path_component="", target_component="c")
    assert_address_input_parsed("//:c", relative_to="here", path_component="", target_component="c")

    # Files
    assert_address_input_parsed("f.txt", path_component="f.txt", target_component=None)
    assert_address_input_parsed("//f.txt", path_component="f.txt", target_component=None)
    assert_address_input_parsed("a/b/c.txt", path_component="a/b/c.txt", target_component=None)
    assert_address_input_parsed("a/b/c.txt:tgt", path_component="a/b/c.txt", target_component="tgt")
    assert_address_input_parsed(
        "a/b/c.txt:../tgt", path_component="a/b/c.txt", target_component="../tgt"
    )
    assert_address_input_parsed(
        "//a/b/c.txt:tgt", path_component="a/b/c.txt", target_component="tgt"
    )
    assert_address_input_parsed(
        "./f.txt", relative_to="here", path_component="here/f.txt", target_component=None
    )
    assert_address_input_parsed(
        "./subdir/f.txt:tgt",
        relative_to="here",
        path_component="here/subdir/f.txt",
        target_component="tgt",
    )
    assert_address_input_parsed(
        "subdir/f.txt", relative_to="here", path_component="subdir/f.txt", target_component=None
    )


def test_address_input_parse_bad_path_component() -> None:
    def assert_bad_path_component(spec: str) -> None:
        with pytest.raises(InvalidSpecPath):
            AddressInput.parse(spec)

    assert_bad_path_component("..")
    assert_bad_path_component(".")

    assert_bad_path_component("//..")
    assert_bad_path_component("//.")

    assert_bad_path_component("a/.")
    assert_bad_path_component("a/..")
    assert_bad_path_component("../a")
    assert_bad_path_component("a/../a")

    assert_bad_path_component("a/:a")
    assert_bad_path_component("a/b/:b")

    # Absolute paths are banned.
    assert_bad_path_component("/a")
    assert_bad_path_component("///a")

    # The path_component should not end in BUILD.
    assert_bad_path_component("BUILD")
    assert_bad_path_component("BUILD.suffix")
    assert_bad_path_component("//BUILD")
    assert_bad_path_component("//BUILD.suffix")
    assert_bad_path_component("a/BUILD")
    assert_bad_path_component("a/BUILD.suffix")
    assert_bad_path_component("//a/BUILD")
    assert_bad_path_component("//a/BUILD.suffix")
    assert_bad_path_component("a/BUILD:b")
    assert_bad_path_component("a/BUILD.suffix:b")
    assert_bad_path_component("//a/BUILD:b")
    assert_bad_path_component("//a/BUILD.suffix:b")


def test_address_input_parse_bad_target_component() -> None:
    def assert_bad_target_component(spec: str) -> None:
        with pytest.raises(InvalidTargetName):
            print(repr(AddressInput.parse(spec)))

    # Missing target_component
    assert_bad_target_component("")
    assert_bad_target_component("a:")
    assert_bad_target_component("a::")
    assert_bad_target_component("//")
    assert_bad_target_component("//:")

    # Banned chars
    assert_bad_target_component("//:@t")
    assert_bad_target_component("//:!t")
    assert_bad_target_component("//:?t")
    assert_bad_target_component("//:=t")


def test_subproject_spec() -> None:
    # Ensure that a spec referring to a subproject gets assigned to that subproject properly.
    def parse(spec, relative_to):
        return AddressInput.parse(
            spec, relative_to=relative_to, subproject_roots=["subprojectA", "path/to/subprojectB"],
        )

    # Ensure that a spec in subprojectA is determined correctly.
    ai = parse("src/python/alib", "subprojectA/src/python")
    assert "subprojectA/src/python/alib" == ai.path_component
    assert ai.target_component is None

    ai = parse("src/python/alib:jake", "subprojectA/src/python/alib")
    assert "subprojectA/src/python/alib" == ai.path_component
    assert "jake" == ai.target_component

    ai = parse(":rel", "subprojectA/src/python/alib")
    assert "subprojectA/src/python/alib" == ai.path_component
    assert "rel" == ai.target_component

    # Ensure that a spec in subprojectB, which is more complex, is correct.
    ai = parse("src/python/blib", "path/to/subprojectB/src/python")
    assert "path/to/subprojectB/src/python/blib" == ai.path_component
    assert ai.target_component is None

    ai = parse("src/python/blib:jane", "path/to/subprojectB/src/python/blib")
    assert "path/to/subprojectB/src/python/blib" == ai.path_component
    assert "jane" == ai.target_component

    ai = parse(":rel", "path/to/subprojectB/src/python/blib")
    assert "path/to/subprojectB/src/python/blib" == ai.path_component
    assert "rel" == ai.target_component

    # Ensure that a spec in the parent project is not mapped.
    ai = parse("src/python/parent", "src/python")
    assert "src/python/parent" == ai.path_component
    assert ai.target_component is None

    ai = parse("src/python/parent:george", "src/python")
    assert "src/python/parent" == ai.path_component
    assert "george" == ai.target_component

    ai = parse(":rel", "src/python/parent")
    assert "src/python/parent" == ai.path_component
    assert "rel" == ai.target_component


def test_address_input_from_file() -> None:
    assert AddressInput("a/b/c.txt", target_component=None).file_to_address() == Address(
        "a/b", relative_file_path="c.txt"
    )

    assert AddressInput("a/b/c.txt", target_component="original").file_to_address() == Address(
        "a/b", target_name="original", relative_file_path="c.txt"
    )
    assert AddressInput("a/b/c.txt", target_component="../original").file_to_address() == Address(
        "a", target_name="original", relative_file_path="b/c.txt"
    )
    assert AddressInput(
        "a/b/c.txt", target_component="../../original"
    ).file_to_address() == Address("", target_name="original", relative_file_path="a/b/c.txt")

    # These refer to targets "below" the file, which is illegal.
    with pytest.raises(InvalidTargetName):
        AddressInput("f.txt", target_component="subdir/tgt").file_to_address()
    with pytest.raises(InvalidTargetName):
        AddressInput("f.txt", target_component="subdir../tgt").file_to_address()
    with pytest.raises(InvalidTargetName):
        AddressInput("a/f.txt", target_component="../a/original").file_to_address()

    # Top-level files must include a target_name.
    with pytest.raises(InvalidTargetName):
        AddressInput("f.txt").file_to_address()
    assert AddressInput("f.txt", target_component="tgt").file_to_address() == Address(
        "", relative_file_path="f.txt", target_name="tgt"
    )


def test_address_input_from_dir() -> None:
    assert AddressInput("a").dir_to_address() == Address("a")
    assert AddressInput("a", target_component="b").dir_to_address() == Address("a", target_name="b")


def test_address_normalize_target_name() -> None:
    assert Address("a/b/c", target_name="c") == Address("a/b/c", target_name=None)
    assert Address("a/b/c", target_name="c", relative_file_path="f.txt") == Address(
        "a/b/c", target_name=None, relative_file_path="f.txt"
    )


def test_address_equality() -> None:
    assert "Not really an address" != Address("a/b", target_name="c")

    assert Address("a/b", target_name="c") == Address("a/b", target_name="c")
    assert Address("a/b", target_name="c") != Address("a/b", target_name="d")
    assert Address("a/b", target_name="c") != Address("a/z", target_name="c")

    assert Address("a/b", target_name="c") != Address(
        "a/b", relative_file_path="c", target_name="original"
    )
    assert Address("a/b", relative_file_path="c", target_name="original") == Address(
        "a/b", relative_file_path="c", target_name="original"
    )


def test_address_spec() -> None:
    normal_addr = Address("a/b", target_name="c")
    assert normal_addr.spec == "a/b:c" == str(normal_addr) == normal_addr.reference()
    assert normal_addr.path_safe_spec == "a.b.c"

    top_level_addr = Address("", target_name="root")
    assert top_level_addr.spec == "//:root" == str(top_level_addr) == top_level_addr.reference()
    assert top_level_addr.path_safe_spec == ".root"

    generated_addr = Address("a/b", relative_file_path="c.txt", target_name="c")
    assert generated_addr.spec == "a/b/c.txt:c" == str(generated_addr) == generated_addr.reference()
    assert generated_addr.path_safe_spec == "a.b.c.txt.c"

    top_level_generated_addr = Address("", relative_file_path="root.txt", target_name="root")
    assert (
        top_level_generated_addr.spec
        == "//root.txt:root"
        == str(top_level_generated_addr)
        == top_level_generated_addr.reference()
    )
    assert top_level_generated_addr.path_safe_spec == ".root.txt.root"

    generated_subdirectory_addr = Address(
        "a/b", relative_file_path="subdir/c.txt", target_name="original"
    )
    assert (
        generated_subdirectory_addr.spec
        == "a/b/subdir/c.txt:../original"
        == str(generated_subdirectory_addr)
        == generated_subdirectory_addr.reference()
    )
    assert generated_subdirectory_addr.path_safe_spec == "a.b.subdir.c.txt@original"

    generated_addr_from_default_target = Address("a/b", relative_file_path="c.txt")
    assert (
        generated_addr_from_default_target.spec
        == "a/b/c.txt"
        == str(generated_addr_from_default_target)
        == generated_addr_from_default_target.reference()
    )
    assert generated_addr_from_default_target.path_safe_spec == "a.b.c.txt"


def test_address_maybe_convert_to_base_target() -> None:
    generated_addr = Address("a/b", relative_file_path="c.txt", target_name="c")
    assert generated_addr.maybe_convert_to_base_target() == Address("a/b", target_name="c")

    normal_addr = Address("a/b", target_name="c")
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
