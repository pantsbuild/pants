# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.option.optionable import Optionable


class OptionableTest(unittest.TestCase):
    def test_optionable(self) -> None:
        class NoScope(Optionable):
            pass

        with self.assertRaises(NotImplementedError):
            NoScope()

        class NoneScope(Optionable):
            options_scope = None

        with self.assertRaises(NotImplementedError):
            NoneScope()

        class NonStringScope(Optionable):
            options_scope = 42  # type: ignore[assignment]

        with self.assertRaises(NotImplementedError):
            NonStringScope()

        class StringScope(Optionable):
            options_scope = "good"

        self.assertEqual("good", StringScope.options_scope)

        class Intermediate(Optionable):
            pass

        class Indirect(Intermediate):
            options_scope = "good"

        self.assertEqual("good", Indirect.options_scope)

    def test_is_valid_scope_name_component(self) -> None:
        def check_true(s: str) -> None:
            self.assertTrue(Optionable.is_valid_scope_name_component(s))

        def check_false(s: str) -> None:
            self.assertFalse(Optionable.is_valid_scope_name_component(s))

        check_true("")
        check_true("foo")
        check_true("foo-bar0")
        check_true("foo-bar0-1ba22z")

        check_false("Foo")
        check_false("fOo")
        check_false("foo.bar")
        check_false("foo_bar")
        check_false("foo--bar")
        check_false("foo-bar-")
