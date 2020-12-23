# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from textwrap import dedent

from pants.util.strutil import (
    ensure_binary,
    ensure_text,
    first_paragraph,
    hard_wrap,
    pluralize,
    strip_prefix,
    strip_v2_chroot_path,
)


# TODO(Eric Ayers): Backfill tests for other methods in strutil.py
class StrutilTest(unittest.TestCase):
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


def test_hard_wrap() -> None:
    assert hard_wrap("Hello world!", width=6) == ["Hello", "world!"]

    # Indents play into the width.
    assert hard_wrap("Hello world!", width=6, indent=2) == ["  Hell", "  o wo", "  rld!"]
    assert hard_wrap("Hello world!", width=8, indent=2) == ["  Hello", "  world!"]

    # Preserve prior newlines.
    assert hard_wrap("- 1\n- 2\n\n") == ["- 1", "- 2", ""]
    assert hard_wrap("Hello world!\n\n- 1 some text\n- 2\n\nHola mundo!", width=6) == [
        "Hello",
        "world!",
        "",
        "- 1",
        "some",
        "text",
        "- 2",
        "",
        "Hola",
        "mundo!",
    ]


def test_first_paragraph() -> None:
    assert (
        first_paragraph(
            dedent(
                """\
            Hello! I'm spread out
            over multiple
               lines.

            Second paragraph.
            """
            )
        )
        == "Hello! I'm spread out over multiple    lines."
    )
    assert first_paragraph("Only one paragraph.") == "Only one paragraph."
