# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.util.argutil import ensure_arg, remove_arg


class ArgutilTest(unittest.TestCase):
    def test_ensure_arg(self) -> None:
        self.assertEqual(["foo"], ensure_arg([], "foo"))
        self.assertEqual(["foo"], ensure_arg(["foo"], "foo"))
        self.assertEqual(["bar", "foo"], ensure_arg(["bar"], "foo"))
        self.assertEqual(["bar", "foo"], ensure_arg(["bar", "foo"], "foo"))

        self.assertEqual(["foo", "baz"], ensure_arg([], "foo", param="baz"))
        self.assertEqual(
            ["qux", "foo", "baz"], ensure_arg(["qux", "foo", "bar"], "foo", param="baz")
        )
        self.assertEqual(["foo", "baz"], ensure_arg(["foo", "bar"], "foo", param="baz"))
        self.assertEqual(
            ["qux", "foo", "baz", "foobar"],
            ensure_arg(["qux", "foo", "bar", "foobar"], "foo", param="baz"),
        )

    def test_remove_arg(self) -> None:
        self.assertEqual([], remove_arg([], "foo"))
        self.assertEqual([], remove_arg(["foo"], "foo"))
        self.assertEqual(["bar"], remove_arg(["foo", "bar"], "foo"))
        self.assertEqual(["bar"], remove_arg(["bar", "foo"], "foo"))
        self.assertEqual(["bar", "baz"], remove_arg(["bar", "foo", "baz"], "foo"))

        self.assertEqual([], remove_arg([], "foo", has_param=True))
        self.assertEqual([], remove_arg(["foo", "bar"], "foo", has_param=True))
        self.assertEqual(["baz"], remove_arg(["baz", "foo", "bar"], "foo", has_param=True))
        self.assertEqual(["baz"], remove_arg(["foo", "bar", "baz"], "foo", has_param=True))
        self.assertEqual(
            ["qux", "foobar"], remove_arg(["qux", "foo", "bar", "foobar"], "foo", has_param=True)
        )
