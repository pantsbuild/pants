# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.option.optionable import Optionable


class OptionableTest(unittest.TestCase):
    def test_optionable(self) -> None:
        class NoScope(Optionable):
            pass

        with self.assertRaises(TypeError) as cm:
            NoScope()  # type: ignore[abstract]
        assert "with abstract methods options_scope" in str(
            cm.exception
        ) or "with abstract method options_scope" in str(cm.exception)

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
