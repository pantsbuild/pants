# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import Optional

from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.specs import (
    AddressSpec,
    DescendantAddresses,
    FilesystemGlobSpec,
    FilesystemIgnoreSpec,
    FilesystemLiteralSpec,
    FilesystemSpec,
    SiblingAddresses,
    SingleAddress,
)
from pants.testutil.test_base import TestBase


def single(directory: str, name: Optional[str] = None) -> SingleAddress:
    name = name if name is not None else os.path.basename(directory)
    return SingleAddress(directory, name)


def desc(directory: str) -> DescendantAddresses:
    return DescendantAddresses(directory)


def sib(directory: str) -> SiblingAddresses:
    return SiblingAddresses(directory)


def literal(file: str) -> FilesystemLiteralSpec:
    return FilesystemLiteralSpec(file)


def glob(val: str) -> FilesystemGlobSpec:
    return FilesystemGlobSpec(val)


def ignore(val: str) -> FilesystemIgnoreSpec:
    return FilesystemIgnoreSpec(val)


class CmdLineSpecParserTest(TestBase):
    def setUp(self) -> None:
        super().setUp()
        self._spec_parser = CmdLineSpecParser(self.build_root)

    def test_normal_address_specs(self) -> None:
        self.assert_address_spec_parsed(":root", single("", "root"))
        self.assert_address_spec_parsed("//:root", single("", "root"))

        self.assert_address_spec_parsed("a", single("a"))
        self.assert_address_spec_parsed("a:a", single("a", "a"))

        self.assert_address_spec_parsed("a/b", single("a/b"))
        self.assert_address_spec_parsed("a/b:b", single("a/b", "b"))
        self.assert_address_spec_parsed("a/b:c", single("a/b", "c"))

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
            self.assert_filesystem_spec_parsed(f, literal(f))
        self.assert_filesystem_spec_parsed("./a.txt", literal("a.txt"))
        self.assert_filesystem_spec_parsed("//./a.txt", literal("a.txt"))

    def test_globs(self) -> None:
        for glob_str in ["*", "**/*", "a/b/*", "a/b/test_*.py", "a/b/**/test_*"]:
            self.assert_filesystem_spec_parsed(glob_str, glob(glob_str))

    def test_excludes(self) -> None:
        for glob_str in ["!", "!a/b/", "!/a/b/*"]:
            self.assert_filesystem_spec_parsed(glob_str, ignore(glob_str[1:]))

    def test_ambiguous_files(self) -> None:
        # These could either be files or the shorthand for single addresses. We check if they exist on
        # the file system to disambiguate.
        for spec in ["a", "b/c"]:
            self.assert_address_spec_parsed(spec, single(spec))
            self.create_file(spec)
            self.assert_filesystem_spec_parsed(spec, literal(spec))

    def test_absolute(self) -> None:
        self.assert_address_spec_parsed(os.path.join(self.build_root, "a"), single("a"))
        self.assert_address_spec_parsed(os.path.join(self.build_root, "a:a"), single("a", "a"))
        self.assert_address_spec_parsed(os.path.join(self.build_root, "a:"), sib("a"))
        self.assert_address_spec_parsed(os.path.join(self.build_root, "a::"), desc("a"))
        self.assert_filesystem_spec_parsed(os.path.join(self.build_root, "a.txt"), literal("a.txt"))

        with self.assertRaises(CmdLineSpecParser.BadSpecError):
            self.assert_address_spec_parsed("/not/the/buildroot/a", sib("a"))
            self.assert_filesystem_spec_parsed("/not/the/buildroot/a.txt", literal("a.txt"))

    def test_absolute_double_slashed(self) -> None:
        # By adding a double slash, we are insisting that this absolute path is actually
        # relative to the buildroot. Thus, it should parse correctly.
        double_absolute_address = "/" + os.path.join(self.build_root, "a")
        double_absolute_file = "/" + os.path.join(self.build_root, "a.txt")
        for spec in [double_absolute_address, double_absolute_file]:
            assert "//" == spec[:2], "A sanity check that we have a leading-// absolute spec"
        self.assert_address_spec_parsed(
            double_absolute_address, single(double_absolute_address[2:])
        )
        self.assert_filesystem_spec_parsed(double_absolute_file, literal(double_absolute_file[2:]))

    def test_cmd_line_affordances(self) -> None:
        self.assert_address_spec_parsed("./:root", single("", "root"))
        self.assert_address_spec_parsed("//./:root", single("", "root"))
        self.assert_address_spec_parsed("//./a/../:root", single("", "root"))
        self.assert_address_spec_parsed(
            os.path.join(self.build_root, "./a/../:root"), single("", "root")
        )

        self.assert_address_spec_parsed("a/", single("a"))
        self.assert_address_spec_parsed("./a/", single("a"))
        self.assert_address_spec_parsed(os.path.join(self.build_root, "./a/"), single("a"))

        self.assert_address_spec_parsed("a/b/:b", single("a/b", "b"))
        self.assert_address_spec_parsed("./a/b/:b", single("a/b", "b"))
        self.assert_address_spec_parsed(
            os.path.join(self.build_root, "./a/b/:b"), single("a/b", "b")
        )

    def assert_address_spec_parsed(self, spec_str: str, expected_spec: AddressSpec) -> None:
        spec = self._spec_parser.parse_spec(spec_str)
        assert isinstance(spec, AddressSpec)
        assert spec == expected_spec

    def assert_filesystem_spec_parsed(self, spec_str: str, expected_spec: FilesystemSpec) -> None:
        spec = self._spec_parser.parse_spec(spec_str)
        assert isinstance(spec, FilesystemSpec)
        assert spec == expected_spec
