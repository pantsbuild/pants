# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.build_graph.address import (
    Address,
    AddressInput,
    AddressParseException,
    InvalidParametersError,
    InvalidSpecPathError,
    InvalidTargetNameError,
    UnsupportedWildcardError,
)


def test_address_input_parse_spec() -> None:
    def assert_parsed(
        spec: str,
        *,
        path_component: str,
        target_component: str | None = None,
        parameters: dict[str, str] | None = None,
        generated_component: str | None = None,
        relative_to: str | None = None,
    ) -> None:
        ai = AddressInput.parse(spec, relative_to=relative_to, description_of_origin="tests")
        assert ai.path_component == path_component
        if target_component is None:
            assert ai.target_component is None
        else:
            assert ai.target_component == target_component
        assert ai.parameters == (parameters or {})
        if generated_component is None:
            assert ai.generated_component is None
        else:
            assert ai.generated_component == generated_component

    assert_parsed("a/b/c", path_component="a/b/c")
    assert_parsed("a/b/c:c", path_component="a/b/c", target_component="c")
    assert_parsed("a/b/c#gen", path_component="a/b/c", generated_component="gen")
    assert_parsed(
        "a/b/c:c#gen", path_component="a/b/c", target_component="c", generated_component="gen"
    )
    # The relative_to has no effect because we have a path.
    assert_parsed("a/b/c", relative_to="here", path_component="a/b/c")

    # Relative address spec
    assert_parsed(":c", path_component="", target_component="c")
    assert_parsed(":c", relative_to="here", path_component="here", target_component="c")
    assert_parsed("#gen", relative_to="here", path_component="here", generated_component="gen")
    assert_parsed(
        ":c#gen",
        relative_to="here",
        path_component="here",
        target_component="c",
        generated_component="gen",
    )
    assert_parsed("//:c", relative_to="here", path_component="", target_component="c")
    assert_parsed(
        "//:c#gen",
        relative_to="here",
        path_component="",
        target_component="c",
        generated_component="gen",
    )

    # Parameters
    assert_parsed("a@k=v", path_component="a", parameters={"k": "v"})
    assert_parsed("a@k1=v1,k2=v2", path_component="a", parameters={"k1": "v1", "k2": "v2"})
    assert_parsed(
        "a#gen@k1=v1", generated_component="gen", path_component="a", parameters={"k1": "v1"}
    )
    assert_parsed("a@t", path_component="a@t")
    assert_parsed("a@=", path_component="a@=")
    assert_parsed("a@t,y", path_component="a@t,y")
    assert_parsed("a@2.png:../t", path_component="a@2.png", target_component="../t")

    # Absolute spec
    assert_parsed("//a/b/c", path_component="a/b/c")
    assert_parsed("//a/b/c:c", path_component="a/b/c", target_component="c")
    assert_parsed("//:c", path_component="", target_component="c")
    assert_parsed("//:c", relative_to="here", path_component="", target_component="c")

    # Files
    assert_parsed("f.txt", path_component="f.txt")
    assert_parsed("//f.txt", path_component="f.txt")
    assert_parsed("a/b/c.txt", path_component="a/b/c.txt")
    assert_parsed("a/b/c.txt:tgt", path_component="a/b/c.txt", target_component="tgt")
    assert_parsed("a/b/c.txt:../tgt", path_component="a/b/c.txt", target_component="../tgt")
    assert_parsed("//a/b/c.txt:tgt", path_component="a/b/c.txt", target_component="tgt")
    assert_parsed("./f.txt", relative_to="here", path_component="here/f.txt")
    assert_parsed(
        "./subdir/f.txt:tgt",
        relative_to="here",
        path_component="here/subdir/f.txt",
        target_component="tgt",
    )
    assert_parsed("subdir/f.txt", relative_to="here", path_component="subdir/f.txt")
    assert_parsed("a/b/c.txt#gen", path_component="a/b/c.txt", generated_component="gen")


@pytest.mark.parametrize(
    "spec",
    ["..", ".", "//..", "//.", "a/.", "a/..", "../a", "a/../a", "a/:a", "a/b/:b", "/a", "///a"],
)
def test_address_input_parse_bad_path_component(spec: str) -> None:
    with pytest.raises(InvalidSpecPathError):
        AddressInput.parse(spec, description_of_origin="tests")


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("a@t=,y", "one or more key=value pairs"),
        ("a#", "non-empty generated target name"),
    ],
)
def test_address_input_parse(spec: str, expected: str) -> None:
    with pytest.raises(AddressParseException) as e:
        AddressInput.parse(spec, description_of_origin="tests")
    assert expected in str(e.value)


@pytest.mark.parametrize(
    "spec",
    [
        "",
        "//",
        "//:!t",
        "//:?",
        "//:=",
        r"a:b\c",
        "a:b/c",
        "a:my#tgt#generated",
    ],
)
def test_address_bad_target_component(spec: str) -> None:
    with pytest.raises(InvalidTargetNameError):
        AddressInput.parse(spec, description_of_origin="tests").dir_to_address()


@pytest.mark.parametrize(
    "spec",
    [
        "a::",
        "a:",
        "a:b:",
        "a:b::",
        "a#b:",
    ],
)
def test_address_bad_wildcard(spec: str) -> None:
    with pytest.raises(UnsupportedWildcardError):
        AddressInput.parse(spec, description_of_origin="tests").dir_to_address()


@pytest.mark.parametrize("spec", ["//:t#gen!", "//:t#gen?", "//:t#gen=", "//:t#gen#"])
def test_address_generated_name(spec: str) -> None:
    with pytest.raises(InvalidTargetNameError):
        AddressInput.parse(spec, description_of_origin="tests").dir_to_address()


@pytest.mark.parametrize("spec", ["//:t@k=#gen", "//:t@k#gen=v"])
def test_address_invalid_params(spec: str) -> None:
    with pytest.raises(InvalidParametersError):
        AddressInput.parse(spec, description_of_origin="tests").dir_to_address()


def test_address_input_subproject_spec() -> None:
    # Ensure that a spec referring to a subproject gets assigned to that subproject properly.
    def parse(spec, relative_to):
        return AddressInput.parse(
            spec,
            relative_to=relative_to,
            subproject_roots=["subprojectA", "path/to/subprojectB"],
            description_of_origin="tests",
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
    assert AddressInput.parse(
        "a/b/c.txt", description_of_origin="tests"
    ).file_to_address() == Address("a/b", relative_file_path="c.txt")

    assert AddressInput.parse(
        "a/b/c.txt:original", description_of_origin="tests"
    ).file_to_address() == Address("a/b", target_name="original", relative_file_path="c.txt")
    assert AddressInput.parse(
        "a/b/c.txt:../original", description_of_origin="tests"
    ).file_to_address() == Address("a", target_name="original", relative_file_path="b/c.txt")
    assert AddressInput.parse(
        "a/b/c.txt:../../original", description_of_origin="tests"
    ).file_to_address() == Address("", target_name="original", relative_file_path="a/b/c.txt")

    # These refer to targets "below" the file, which is illegal.
    with pytest.raises(InvalidTargetNameError):
        AddressInput.parse("f.txt:subdir/tgt", description_of_origin="tests").file_to_address()
    with pytest.raises(InvalidTargetNameError):
        AddressInput.parse("f.txt:subdir../tgt", description_of_origin="tests").file_to_address()
    with pytest.raises(InvalidTargetNameError):
        AddressInput.parse("a/f.txt:../a/original", description_of_origin="tests").file_to_address()

    # Top-level files must include a target_name.
    with pytest.raises(InvalidTargetNameError):
        AddressInput.parse("f.txt", description_of_origin="tests").file_to_address()
    assert AddressInput.parse(
        "f.txt:tgt", description_of_origin="tests"
    ).file_to_address() == Address("", relative_file_path="f.txt", target_name="tgt")


def test_address_input_from_dir() -> None:
    assert AddressInput.parse("a", description_of_origin="tests").dir_to_address() == Address("a")
    assert AddressInput.parse("a:b", description_of_origin="tests").dir_to_address() == Address(
        "a", target_name="b"
    )
    assert AddressInput.parse("a:b#gen", description_of_origin="tests").dir_to_address() == Address(
        "a", target_name="b", generated_name="gen"
    )


def test_address_normalize_target_name() -> None:
    assert Address("a/b/c", target_name="c") == Address("a/b/c", target_name=None)
    assert Address("a/b/c", target_name="c", relative_file_path="f.txt") == Address(
        "a/b/c", target_name=None, relative_file_path="f.txt"
    )


def test_address_validate_build_in_spec_path() -> None:
    with pytest.raises(InvalidSpecPathError):
        Address("a/b/BUILD")
    with pytest.raises(InvalidSpecPathError):
        Address("a/b/BUILD.ext")
    with pytest.raises(InvalidSpecPathError):
        Address("a/b/BUILD", target_name="foo")

    # It's fine to use BUILD in the relative_file_path, target_name, or generated_name, though.
    assert Address("a/b", relative_file_path="BUILD").spec == "a/b/BUILD"
    assert Address("a/b", target_name="BUILD").spec == "a/b:BUILD"
    assert Address("a/b", generated_name="BUILD").spec == "a/b#BUILD"


def test_address_equality() -> None:
    assert Address("dir") == Address("dir")
    assert Address("dir") == Address("dir", target_name="dir")
    assert Address("dir") != Address("another_dir")

    assert Address("a/b", target_name="c") == Address("a/b", target_name="c")
    assert Address("a/b", target_name="c") != Address("a/b", target_name="d")
    assert Address("a/b", target_name="c") != Address("a/z", target_name="c")

    assert Address("dir", generated_name="generated") == Address("dir", generated_name="generated")
    assert Address("dir", generated_name="generated") != Address("dir", generated_name="foo")

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
        assert address.path_safe_spec == expected_path_spec

    assert_spec(Address("a/b"), expected="a/b:b", expected_path_spec="a.b")

    assert_spec(Address("a/b", target_name="c"), expected="a/b:c", expected_path_spec="a.b.c")
    assert_spec(Address("", target_name="root"), expected="//:root", expected_path_spec=".root")

    assert_spec(
        Address("a/b", generated_name="generated"),
        expected="a/b#generated",
        expected_path_spec="a.b@generated",
    )
    assert_spec(
        Address("a/b", generated_name="generated/f.ext"),
        expected="a/b#generated/f.ext",
        expected_path_spec="a.b@generated.f.ext",
    )
    assert_spec(
        Address("a/b", target_name="generator", generated_name="generated"),
        expected="a/b:generator#generated",
        expected_path_spec="a.b.generator@generated",
    )
    assert_spec(
        Address("a/b", target_name="generator", generated_name="generated/f.ext"),
        expected="a/b:generator#generated/f.ext",
        expected_path_spec="a.b.generator@generated.f.ext",
    )
    assert_spec(
        Address("", target_name="root", generated_name="generated"),
        expected="//:root#generated",
        expected_path_spec=".root@generated",
    )

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

    assert_spec(
        Address("", target_name="template", parameters={"k1": "v", "k2": "v"}),
        expected="//:template@k1=v,k2=v",
        expected_path_spec=".template@@k1=v,k2=v",
    )
    assert_spec(
        Address("a/b", parameters={"k1": "v", "k2": "v"}),
        expected="a/b@k1=v,k2=v",
        expected_path_spec="a.b@@k1=v,k2=v",
    )
    assert_spec(
        Address("a/b", generated_name="gen", parameters={"k": "v"}),
        expected="a/b#gen@k=v",
        expected_path_spec="a.b@gen@@k=v",
    )
    assert_spec(
        Address("a/b", relative_file_path="f.ext", parameters={"k": "v"}),
        expected="a/b/f.ext@k=v",
        expected_path_spec="a.b.f.ext@@k=v",
    )


@pytest.mark.parametrize(
    "params,expected", (({}, ""), ({"k": "v"}, "@k=v"), ({"k1": "v", "k2": "v"}, "@k1=v,k2=v"))
)
def test_address_parameters_repr(params: dict[str, str], expected: str) -> None:
    assert Address("", target_name="foo", parameters=params).parameters_repr == expected


def test_address_maybe_convert_to_target_generator() -> None:
    def assert_converts(addr: Address, *, expected: Address) -> None:
        assert addr.maybe_convert_to_target_generator() == expected

    assert_converts(
        Address(
            "a/b",
            target_name="c",
            generated_name="generated",
        ),
        expected=Address("a/b", target_name="c"),
    )
    assert_converts(Address("a/b", generated_name="generated"), expected=Address("a/b"))
    assert_converts(Address("a/b", generated_name="subdir/generated"), expected=Address("a/b"))

    assert_converts(
        Address("a/b", relative_file_path="c.txt", target_name="c"),
        expected=Address("a/b", target_name="c"),
    )
    assert_converts(Address("a/b", relative_file_path="c.txt"), expected=Address("a/b"))
    assert_converts(Address("a/b", relative_file_path="subdir/f.txt"), expected=Address("a/b"))
    assert_converts(
        Address("a/b", relative_file_path="subdir/f.txt", target_name="original"),
        expected=Address("a/b", target_name="original"),
    )

    def assert_noops(addr: Address) -> None:
        assert addr.maybe_convert_to_target_generator() is addr

    assert_noops(Address("a/b", target_name="c"))
    assert_noops(Address("a/b"))


def test_address_create_generated() -> None:
    assert Address("dir", target_name="generator").create_generated("generated") == Address(
        "dir", target_name="generator", generated_name="generated"
    )
    with pytest.raises(AssertionError):
        Address("", target_name="t", relative_file_path="f.ext").create_generated("gen")
    with pytest.raises(AssertionError):
        Address("", target_name="t", generated_name="gen").create_generated("gen")


@pytest.mark.parametrize(
    "addr,expected",
    [
        (
            Address("a/b/c"),
            AddressInput.parse("a/b/c:c", description_of_origin="tests"),
        ),
        (
            Address("a/b/c", target_name="tgt"),
            AddressInput.parse("a/b/c:tgt", description_of_origin="tests"),
        ),
        (
            Address("a/b/c", target_name="tgt", generated_name="gen"),
            AddressInput.parse("a/b/c:tgt#gen", description_of_origin="tests"),
        ),
        (
            Address("a/b/c", target_name="tgt", generated_name="dir/gen"),
            AddressInput.parse("a/b/c:tgt#dir/gen", description_of_origin="tests"),
        ),
        (
            Address("a/b/c", relative_file_path="f.txt"),
            AddressInput.parse("a/b/c/f.txt", description_of_origin="tests"),
        ),
        (
            Address("a/b/c", relative_file_path="f.txt", target_name="tgt"),
            AddressInput.parse("a/b/c/f.txt:tgt", description_of_origin="tests"),
        ),
        (
            Address("", target_name="tgt"),
            AddressInput.parse("//:tgt", description_of_origin="tests"),
        ),
        (
            Address("", target_name="tgt", generated_name="gen"),
            AddressInput.parse("//:tgt#gen", description_of_origin="tests"),
        ),
        (
            Address("", target_name="tgt", relative_file_path="f.txt"),
            AddressInput.parse("//f.txt:tgt", description_of_origin="tests"),
        ),
        (
            Address("a/b/c", relative_file_path="subdir/f.txt"),
            AddressInput.parse("a/b/c/subdir/f.txt:../c", description_of_origin="tests"),
        ),
        (
            Address("a/b/c", relative_file_path="subdir/f.txt", target_name="tgt"),
            AddressInput.parse(
                "a/b/c/subdir/f.txt:../tgt",
                description_of_origin="tests",
            ),
        ),
        (
            Address("", target_name="t", parameters={"k": "v"}),
            AddressInput.parse(
                "//:t@k=v",
                description_of_origin="tests",
            ),
        ),
        (
            Address("", target_name="t", parameters={"k": "v"}, generated_name="gen"),
            AddressInput.parse(
                "//:t#gen@k=v",
                description_of_origin="tests",
            ),
        ),
        (
            Address("", target_name="t", parameters={"k": ""}),
            AddressInput.parse(
                "//:t@k=",
                description_of_origin="tests",
            ),
        ),
        (
            Address("", target_name="t", parameters={"k1": "v1", "k2": "v2"}),
            AddressInput.parse(
                "//:t@k1=v1,k2=v2",
                description_of_origin="tests",
            ),
        ),
    ],
)
def test_address_spec_to_address_input(addr: Address, expected: AddressInput) -> None:
    """Check that Address.spec <-> AddressInput.parse() is idempotent."""
    assert AddressInput.parse(addr.spec, description_of_origin="tests") == expected
