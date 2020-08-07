# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import Optional

from pants.base.specs import (
    AddressLiteralSpec,
    AddressSpec,
    DescendantAddresses,
    FilesystemGlobSpec,
    FilesystemIgnoreSpec,
    FilesystemLiteralSpec,
    FilesystemSpec,
    SiblingAddresses,
)
from pants.base.specs_parser import SpecsParser
from pants.testutil.test_base import TestBase


def address_literal(directory: str, name: Optional[str] = None) -> AddressLiteralSpec:
    name = name if name is not None else os.path.basename(directory)
    return AddressLiteralSpec(directory, name)


def desc(directory: str) -> DescendantAddresses:
    return DescendantAddresses(directory)


def sib(directory: str) -> SiblingAddresses:
    return SiblingAddresses(directory)


def file_literal(file: str) -> FilesystemLiteralSpec:
    return FilesystemLiteralSpec(file)


def file_glob(val: str) -> FilesystemGlobSpec:
    return FilesystemGlobSpec(val)


def ignore(val: str) -> FilesystemIgnoreSpec:
    return FilesystemIgnoreSpec(val)


class SpecsParserTest(TestBase):
    def setUp(self) -> None:
        super().setUp()
        self._spec_parser = SpecsParser(self.build_root)

    def test_address_literal_specs(self) -> None:
        self.assert_address_spec_parsed(":root", address_literal("", "root"))
        self.assert_address_spec_parsed("//:root", address_literal("", "root"))

        self.assert_address_spec_parsed("a", address_literal("a"))
        self.assert_address_spec_parsed("a:a", address_literal("a", "a"))

        self.assert_address_spec_parsed("a/b", address_literal("a/b"))
        self.assert_address_spec_parsed("a/b:b", address_literal("a/b", "b"))
        self.assert_address_spec_parsed("a/b:c", address_literal("a/b", "c"))

    def test_sibling(self) -> None:
        self.assert_address_spec_parsed(":", sib(""))
        self.assert_address_spec_parsed("//:", sib(""))

        self.assert_address_spec_parsed("a:", sib("a"))
        self.assert_address_spec_parsed("//a:", sib("a"))

        self.assert_address_spec_parsed("a/b:", sib("a/b"))
        self.assert_address_spec_parsed("//a/b:", sib("a/b"))

    def test_descendant(self) -> None:
        self.assert_address_spec_parsed("::", desc(""))
        self.assert_address_spec_parsed("//::", desc(""))

        self.assert_address_spec_parsed("a::", desc("a"))
        self.assert_address_spec_parsed("//a::", desc("a"))

        self.assert_address_spec_parsed("a/b::", desc("a/b"))
        self.assert_address_spec_parsed("//a/b::", desc("a/b"))

    def test_files(self) -> None:
        # We assume that specs with an extension are meant to be interpreted as filesystem specs.
        for f in ["a.txt", "a.tmp.cache.txt.bak", "a/b/c.txt", ".a.txt"]:
            self.assert_filesystem_spec_parsed(f, file_literal(f))
        self.assert_filesystem_spec_parsed("./a.txt", file_literal("a.txt"))
        self.assert_filesystem_spec_parsed("//./a.txt", file_literal("a.txt"))

    def test_globs(self) -> None:
        for glob_str in ["*", "**/*", "a/b/*", "a/b/test_*.py", "a/b/**/test_*"]:
            self.assert_filesystem_spec_parsed(glob_str, file_glob(glob_str))

    def test_excludes(self) -> None:
        for glob_str in ["!", "!a/b/", "!/a/b/*"]:
            self.assert_filesystem_spec_parsed(glob_str, ignore(glob_str[1:]))

    def test_files_with_original_targets(self) -> None:
        self.assert_address_spec_parsed("a.txt:tgt", address_literal("a.txt", "tgt"))
        self.assert_address_spec_parsed("a/b/c.txt:tgt", address_literal("a/b/c.txt", "tgt"))
        self.assert_address_spec_parsed("./a.txt:tgt", address_literal("a.txt", "tgt"))
        self.assert_address_spec_parsed("//./a.txt:tgt", address_literal("a.txt", "tgt"))
        self.assert_address_spec_parsed("a/b/c.txt:../tgt", address_literal("a/b/c.txt", "../tgt"))

    def test_ambiguous_files(self) -> None:
        # These could either be files or the shorthand for address_literal addresses. We check if they exist
        # on the file system to disambiguate.
        for spec in ["a", "b/c"]:
            self.assert_address_spec_parsed(spec, address_literal(spec))
            self.create_file(spec)
            self.assert_filesystem_spec_parsed(spec, file_literal(spec))

    def test_absolute(self) -> None:
        self.assert_address_spec_parsed(os.path.join(self.build_root, "a"), address_literal("a"))
        self.assert_address_spec_parsed(
            os.path.join(self.build_root, "a:a"), address_literal("a", "a")
        )
        self.assert_address_spec_parsed(os.path.join(self.build_root, "a:"), sib("a"))
        self.assert_address_spec_parsed(os.path.join(self.build_root, "a::"), desc("a"))
        self.assert_filesystem_spec_parsed(
            os.path.join(self.build_root, "a.txt"), file_literal("a.txt")
        )

        with self.assertRaises(SpecsParser.BadSpecError):
            self.assert_address_spec_parsed("/not/the/buildroot/a", sib("a"))
            self.assert_filesystem_spec_parsed("/not/the/buildroot/a.txt", file_literal("a.txt"))

    def test_absolute_double_slashed(self) -> None:
        # By adding a double slash, we are insisting that this absolute path is actually
        # relative to the buildroot. Thus, it should parse correctly.
        double_absolute_address = "/" + os.path.join(self.build_root, "a")
        double_absolute_file = "/" + os.path.join(self.build_root, "a.txt")
        for spec in [double_absolute_address, double_absolute_file]:
            assert "//" == spec[:2]
        self.assert_address_spec_parsed(
            double_absolute_address, address_literal(double_absolute_address[2:])
        )
        self.assert_filesystem_spec_parsed(
            double_absolute_file, file_literal(double_absolute_file[2:])
        )

    def test_cmd_line_affordances(self) -> None:
        self.assert_address_spec_parsed("./:root", address_literal("", "root"))
        self.assert_address_spec_parsed("//./:root", address_literal("", "root"))
        self.assert_address_spec_parsed("//./a/../:root", address_literal("", "root"))
        self.assert_address_spec_parsed(
            os.path.join(self.build_root, "./a/../:root"), address_literal("", "root")
        )

        self.assert_address_spec_parsed("a/", address_literal("a"))
        self.assert_address_spec_parsed("./a/", address_literal("a"))
        self.assert_address_spec_parsed(os.path.join(self.build_root, "./a/"), address_literal("a"))

        self.assert_address_spec_parsed("a/b/:b", address_literal("a/b", "b"))
        self.assert_address_spec_parsed("./a/b/:b", address_literal("a/b", "b"))
        self.assert_address_spec_parsed(
            os.path.join(self.build_root, "./a/b/:b"), address_literal("a/b", "b")
        )

    def assert_address_spec_parsed(self, spec_str: str, expected_spec: AddressSpec) -> None:
        spec = self._spec_parser.parse_spec(spec_str)
        assert isinstance(spec, AddressSpec)
        assert spec == expected_spec

    def assert_filesystem_spec_parsed(self, spec_str: str, expected_spec: FilesystemSpec) -> None:
        spec = self._spec_parser.parse_spec(spec_str)
        assert isinstance(spec, FilesystemSpec)
        assert spec == expected_spec
