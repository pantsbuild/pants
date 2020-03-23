# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.util.strutil import camelcase, ensure_binary, ensure_text, pluralize, strip_prefix


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
        self.assertEqual(u"快", ensure_text(bytes_val))
        with self.assertRaises(TypeError):
            ensure_text(45)  # type: ignore[arg-type] # intended to fail type check

    def test_ensure_binary(self) -> None:
        unicode_val = u"快"
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
