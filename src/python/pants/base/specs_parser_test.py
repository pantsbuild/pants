# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pants.base.specs import (
    AddressLiteralSpec,
    DirGlobSpec,
    DirLiteralSpec,
    FileGlobSpec,
    FileLiteralSpec,
    RecursiveGlobSpec,
    Spec,
)
from pants.base.specs_parser import SpecsParser
from pants.util.frozendict import FrozenDict


def address_literal(
    directory: str,
    name: str | None = None,
    generated: str | None = None,
    parameters: dict[str, str] | None = None,
) -> AddressLiteralSpec:
    return AddressLiteralSpec(
        directory, name, generated, FrozenDict(sorted(parameters.items()) if parameters else ())
    )


def recursive_glob(directory: str) -> RecursiveGlobSpec:
    return RecursiveGlobSpec(directory)


def dir_glob(directory: str) -> DirGlobSpec:
    return DirGlobSpec(directory)


def dir_literal(v: str) -> DirLiteralSpec:
    return DirLiteralSpec(v)


def file_literal(file: str) -> FileLiteralSpec:
    return FileLiteralSpec(file)


def file_glob(val: str) -> FileGlobSpec:
    return FileGlobSpec(val)


def assert_spec_parsed(
    build_root: Path, spec_str: str, expected_spec: Spec, working_dir: str | None = None
) -> None:
    parser = SpecsParser(root_dir=str(build_root), working_dir=working_dir)
    spec, is_ignore = parser.parse_spec(spec_str)
    assert isinstance(spec, type(expected_spec))
    assert spec == expected_spec
    assert is_ignore is False

    # Check ignores are also parsed correctly.
    spec, is_ignore = parser.parse_spec(f"-{spec_str}")
    assert isinstance(spec, type(expected_spec))
    assert spec == expected_spec
    assert is_ignore is True


@pytest.mark.parametrize(
    "spec,expected",
    [
        (":root", address_literal("", "root")),
        ("//:root", address_literal("", "root")),
        ("a", dir_literal("a")),
        ("a@k=v", address_literal("a", parameters={"k": "v"})),
        ("a@k=v,x=y", address_literal("a", parameters={"k": "v", "x": "y"})),
        ("a:b@k=v", address_literal("a", "b", parameters={"k": "v"})),
        ("a:a", address_literal("a", "a")),
        ("a/b", dir_literal("a/b")),
        ("a/b:b", address_literal("a/b", "b")),
        ("a/b:c", address_literal("a/b", "c")),
        ("//a/b:c", address_literal("a/b", "c")),
        ("//#gen", address_literal("", None, "gen")),
        ("//:tgt#gen", address_literal("", "tgt", "gen")),
        ("dir:tgt#gen", address_literal("dir", "tgt", "gen")),
        ("dir#gen", address_literal("dir", None, "gen")),
        ("//dir:tgt#gen", address_literal("dir", "tgt", "gen")),
    ],
)
def test_address_literal_specs(
    tmp_path: Path, spec: str, expected: AddressLiteralSpec | DirLiteralSpec
) -> None:
    assert_spec_parsed(tmp_path, spec, expected)


@pytest.mark.parametrize(
    "spec,expected",
    [
        (":", dir_glob("")),
        ("//:", dir_glob("")),
        ("a:", dir_glob("a")),
        ("//a:", dir_glob("a")),
        ("a/b:", dir_glob("a/b")),
        ("//a/b:", dir_glob("a/b")),
    ],
)
def test_dir_glob(tmp_path: Path, spec: str, expected: DirGlobSpec) -> None:
    assert_spec_parsed(tmp_path, spec, expected)


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("::", recursive_glob("")),
        ("//::", recursive_glob("")),
        ("a::", recursive_glob("a")),
        ("//a::", recursive_glob("a")),
        ("a/b::", recursive_glob("a/b")),
        ("//a/b::", recursive_glob("a/b")),
    ],
)
def test_recursive_glob(tmp_path: Path, spec: str, expected: RecursiveGlobSpec) -> None:
    assert_spec_parsed(tmp_path, spec, expected)


def test_files(tmp_path: Path) -> None:
    # We assume that specs with an extension are meant to be interpreted as filesystem specs.
    for f in ["a.txt", "a.tmp.cache.txt.bak", "a/b/c.txt", ".a.txt"]:
        assert_spec_parsed(tmp_path, f, file_literal(f))
    assert_spec_parsed(tmp_path, "./a.txt", file_literal("a.txt"))
    assert_spec_parsed(tmp_path, "a.txt/", file_literal("a.txt"))
    assert_spec_parsed(tmp_path, "//./a.txt", file_literal("a.txt"))
    assert_spec_parsed(tmp_path, "//a.txt", file_literal("a.txt"))


@pytest.mark.parametrize("spec", ["*", "**/*", "a/b/*", "a/b/test_*.py", "a/b/**/test_*"])
def test_file_globs(tmp_path: Path, spec: str) -> None:
    assert_spec_parsed(tmp_path, spec, file_glob(spec))


def test_dir_literals(tmp_path: Path) -> None:
    for d in ["dir", "dir/subdir", ".dir"]:
        assert_spec_parsed(tmp_path, d, dir_literal(d))
    assert_spec_parsed(tmp_path, "./dir", dir_literal("dir"))
    assert_spec_parsed(tmp_path, "//./dir", dir_literal("dir"))
    assert_spec_parsed(tmp_path, "//dir", dir_literal("dir"))
    assert_spec_parsed(tmp_path, "./", dir_literal(""))
    assert_spec_parsed(tmp_path, ".", dir_literal(""))


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("a.txt:tgt", address_literal("a.txt", "tgt")),
        ("a/b/c.txt:tgt", address_literal("a/b/c.txt", "tgt")),
        ("./a.txt:tgt", address_literal("a.txt", "tgt")),
        ("//./a.txt:tgt", address_literal("a.txt", "tgt")),
        ("a/b/c.txt:../tgt", address_literal("a/b/c.txt", "../tgt")),
    ],
)
def test_files_with_original_targets(
    tmp_path: Path, spec: str, expected: AddressLiteralSpec
) -> None:
    assert_spec_parsed(tmp_path, spec, expected)


@pytest.mark.parametrize("spec", ["a", "b/c"])
def test_ambiguous_files(tmp_path: Path, spec: str) -> None:
    # These could either be files or directories. We check if they exist on the file system to
    # disambiguate.
    assert_spec_parsed(tmp_path, spec, dir_literal(spec))
    path = tmp_path / spec
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    assert_spec_parsed(tmp_path, spec, file_literal(spec))


@pytest.mark.parametrize(
    "spec_suffix,expected",
    [
        ("a", dir_literal("a")),
        ("a:a", address_literal("a", "a")),
        ("a:", dir_glob("a")),
        ("a::", recursive_glob("a")),
        ("a.txt", file_literal("a.txt")),
    ],
)
def test_absolute(tmp_path: Path, spec_suffix: str, expected: Spec) -> None:
    spec = os.path.join(tmp_path, spec_suffix)
    assert_spec_parsed(tmp_path, spec, expected)


def test_invalid_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(SpecsParser.BadSpecError):
        assert_spec_parsed(tmp_path, "/not/the/buildroot/a", dir_glob("a"))
    with pytest.raises(SpecsParser.BadSpecError):
        assert_spec_parsed(tmp_path, "/not/the/buildroot/a.txt", file_literal("a.txt"))


def test_absolute_double_slashed(tmp_path: Path) -> None:
    # By adding a double slash, we are insisting that this absolute path is actually
    # relative to the buildroot. Thus, it should parse correctly.
    double_absolute_address = "/" + os.path.join(tmp_path, "a")
    double_absolute_file = "/" + os.path.join(tmp_path, "a.txt")
    for spec in [double_absolute_address, double_absolute_file]:
        assert "//" == spec[:2]
    assert_spec_parsed(
        tmp_path, f"{double_absolute_address}:a", address_literal(double_absolute_address[2:], "a")
    )
    assert_spec_parsed(tmp_path, double_absolute_file, file_literal(double_absolute_file[2:]))


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("./:root", address_literal("", "root")),
        ("//./:root", address_literal("", "root")),
        ("//./a/../:root", address_literal("", "root")),
        ("a/", dir_literal("a")),
        ("./a/", dir_literal("a")),
        ("a/b/:b", address_literal("a/b", "b")),
        ("./a/b/:b", address_literal("a/b", "b")),
    ],
)
def test_cmd_line_affordances(
    tmp_path: Path, spec: str, expected: AddressLiteralSpec | DirLiteralSpec
) -> None:
    assert_spec_parsed(tmp_path, spec, expected)


@pytest.mark.parametrize(
    "spec_suffix,expected",
    [
        ("./a/../:root", address_literal("", "root")),
        ("./a/", dir_literal("a")),
        ("./a/b/:b", address_literal("a/b", "b")),
    ],
)
def test_cmd_line_affordances_absolute_path(
    tmp_path: Path, spec_suffix: str, expected: AddressLiteralSpec | DirLiteralSpec
) -> None:
    spec = os.path.join(tmp_path, spec_suffix)
    assert_spec_parsed(tmp_path, spec, expected)


@pytest.mark.parametrize(
    "working_dir, spec, expected",
    [
        ("a/b", "c", dir_literal("a/b/c")),
        ("a/b", "../d", dir_literal("a/d")),
        ("a/b", "//e", dir_literal("e")),
    ],
)
def test_working_dir(tmp_path: Path, working_dir: str, spec: str, expected: Spec) -> None:
    assert_spec_parsed(tmp_path, spec, expected, working_dir)
    assert_spec_parsed(tmp_path, spec, expected, str(tmp_path / working_dir))


def test_invalid_working_dir(tmp_path: Path) -> None:
    with pytest.raises(SpecsParser.BadSpecError):
        assert_spec_parsed(tmp_path, "../../foo", dir_literal("foo"), "a")
    with pytest.raises(SpecsParser.BadSpecError):
        assert_spec_parsed(tmp_path, "../../foo", dir_literal("foo"), str(tmp_path / "a"))
    with pytest.raises(SpecsParser.BadSpecError):
        assert_spec_parsed(tmp_path, "test_invalid_working_dir0/foo", dir_literal("foo"), "..")
    with pytest.raises(SpecsParser.BadSpecError):
        assert_spec_parsed(
            tmp_path, "test_invalid_working_dir0/foo", dir_literal("foo"), str(tmp_path / "..")
        )
