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


def test_address_validate_build_in_spec_path() -> None:
    with pytest.raises(InvalidSpecPath):
        Address("a/b/BUILD")
    with pytest.raises(InvalidSpecPath):
        Address("a/b/BUILD.ext")
    with pytest.raises(InvalidSpecPath):
        Address("a/b/BUILD", target_name="foo")

    # It's fine to use BUILD in the relative_file_path or target_name, though.
    assert Address("a/b", relative_file_path="BUILD").spec == "a/b/BUILD"
    assert Address("a/b", target_name="BUILD").spec == "a/b:BUILD"


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
    def assert_spec(address: Address, *, expected: str, expected_path_spec: str) -> None:
        assert address.spec == expected
        assert str(address) == expected
        assert address.reference() == expected
        assert address.path_safe_spec == expected_path_spec

    assert_spec(Address("a/b"), expected="a/b", expected_path_spec="a.b")
    assert_spec(Address("a/b", target_name="c"), expected="a/b:c", expected_path_spec="a.b.c")
    assert_spec(Address("", target_name="root"), expected="//:root", expected_path_spec=".root")
    assert_spec(
        Address("a/b", relative_file_path="c.txt", target_name="c"),
        expected="a/b/c.txt:c",
        expected_path_spec="a.b.c.txt.c",
    )
    assert_spec(
        Address("", relative_file_path="root.txt", target_name="root"),
        expected="//root.txt:root",
        expected_path_spec=".root.txt.root",
    )
    assert_spec(
        Address("a/b", relative_file_path="subdir/c.txt", target_name="original"),
        expected="a/b/subdir/c.txt:../original",
        expected_path_spec="a.b.subdir.c.txt@original",
    )
    assert_spec(
        Address("a/b", relative_file_path="c.txt"),
        expected="a/b/c.txt",
        expected_path_spec="a.b.c.txt",
    )
    assert_spec(
        Address("a/b", relative_file_path="subdir/f.txt"),
        expected="a/b/subdir/f.txt:../b",
        expected_path_spec="a.b.subdir.f.txt@b",
    )
    assert_spec(
        Address("a/b", relative_file_path="subdir/dir2/f.txt"),
        expected="a/b/subdir/dir2/f.txt:../../b",
        expected_path_spec="a.b.subdir.dir2.f.txt@@b",
    )


def test_address_maybe_convert_to_base_target() -> None:
    def assert_converts_to_base_target(generated_addr: Address, *, expected: Address) -> None:
        assert generated_addr.maybe_convert_to_base_target() == expected

    assert_converts_to_base_target(
        Address("a/b", relative_file_path="c.txt", target_name="c"),
        expected=Address("a/b", target_name="c"),
    )
    assert_converts_to_base_target(
        Address("a/b", relative_file_path="c.txt"), expected=Address("a/b")
    )
    assert_converts_to_base_target(
        Address("a/b", relative_file_path="subdir/f.txt"), expected=Address("a/b")
    )
    assert_converts_to_base_target(
        Address("a/b", relative_file_path="subdir/f.txt", target_name="original"),
        expected=Address("a/b", target_name="original"),
    )

    def assert_base_target_noops(addr: Address) -> None:
        assert addr.maybe_convert_to_base_target() is addr

    assert_base_target_noops(Address("a/b", target_name="c"))
    assert_base_target_noops(Address("a/b"))


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
