# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from textwrap import dedent

from pants.util.strutil import (
    camelcase,
    ensure_binary,
    ensure_text,
    pluralize,
    strip_prefix,
    strip_v2_chroot_path,
)


# TODO(Eric Ayers): Backfill tests for other methods in strutil.py
class StrutilTest(unittest.TestCase):
    def test_camelcase(self) -> None:

        self.assertEqual("Foo", camelcase("foo"))
        self.assertEqual("Foo", camelcase("_foo"))
        self.assertEqual("Foo", camelcase("foo_"))
        self.assertEqual("FooBar", camelcase("foo_bar"))
        self.assertEqual("FooBar", camelcase("foo_bar_"))
        self.assertEqual("FooBar", camelcase("_foo_bar"))
        self.assertEqual("FooBar", camelcase("foo__bar"))
        self.assertEqual("Foo", camelcase("-foo"))
        self.assertEqual("Foo", camelcase("foo-"))
        self.assertEqual("FooBar", camelcase("foo-bar"))
        self.assertEqual("FooBar", camelcase("foo-bar-"))
        self.assertEqual("FooBar", camelcase("-foo-bar"))
        self.assertEqual("FooBar", camelcase("foo--bar"))
        self.assertEqual("FooBar", camelcase("foo-_bar"))

    def test_pluralize(self) -> None:
        self.assertEqual("1 bat", pluralize(1, "bat"))
        self.assertEqual("1 boss", pluralize(1, "boss"))
        self.assertEqual("2 bats", pluralize(2, "bat"))
        self.assertEqual("2 bosses", pluralize(2, "boss"))
        self.assertEqual("0 bats", pluralize(0, "bat"))
        self.assertEqual("0 bosses", pluralize(0, "boss"))

    def test_ensure_text(self) -> None:
        bytes_val = bytes(bytearray([0xE5, 0xBF, 0xAB]))
        self.assertEqual("快", ensure_text(bytes_val))
        with self.assertRaises(TypeError):
            ensure_text(45)  # type: ignore[arg-type] # intended to fail type check

    def test_ensure_binary(self) -> None:
        unicode_val = "快"
        self.assertEqual(bytearray([0xE5, 0xBF, 0xAB]), ensure_binary(unicode_val))
        with self.assertRaises(TypeError):
            ensure_binary(45)  # type: ignore[arg-type] # intended to fail type check

    def test_strip_prefix(self) -> None:
        self.assertEqual("testString", strip_prefix("testString", "//"))
        self.assertEqual("/testString", strip_prefix("/testString", "//"))
        self.assertEqual("testString", strip_prefix("//testString", "//"))
        self.assertEqual("/testString", strip_prefix("///testString", "//"))
        self.assertEqual("//testString", strip_prefix("////testString", "//"))
        self.assertEqual("test//String", strip_prefix("test//String", "//"))
        self.assertEqual("testString//", strip_prefix("testString//", "//"))


def test_strip_chroot_path() -> None:
    assert (
        strip_v2_chroot_path(
            dedent(
                """\
            Would reformat /private/var/folders/sx/pdpbqz4x5cscn9hhfpbsbqvm0000gn/T/process-execution3zt5Ph/src/python/example.py
            Would reformat /var/folders/sx/pdpbqz4x5cscn9hhfpbsbqvm0000gn/T/process-executionOCnquv/test.py
            Would reformat /custom-tmpdir/process-execution7zt4pH/custom_tmpdir.py

            Some other output.
            """
            )
        )
        == dedent(
            """\
        Would reformat src/python/example.py
        Would reformat test.py
        Would reformat custom_tmpdir.py

        Some other output.
        """
        )
    )

    # A subdir must be prefixed with `process-execution`, then some characters after it.
    assert (
        strip_v2_chroot_path("/var/process_executionOCnquv/test.py")
        == "/var/process_executionOCnquv/test.py"
    )
    assert (
        strip_v2_chroot_path("/var/process-execution/test.py") == "/var/process-execution/test.py"
    )

    # Our heuristic requires absolute paths.
    assert (
        strip_v2_chroot_path("var/process-executionOCnquv/test.py")
        == "var/process-executionOCnquv/test.py"
    )

    # Confirm we can handle values with no chroot path.
    assert strip_v2_chroot_path("") == ""
    assert strip_v2_chroot_path("hello world") == "hello world"
