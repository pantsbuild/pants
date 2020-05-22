# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
import unittest

from pants.backend.project_info.source_file_validator import Matcher, MultiMatcher, RegexMatchResult


# Note that some parts of these tests are just exercising various capabilities of the regex engine.
# This is not something we technically need to test, but it's useful for sanity checking, and for
# showcasing common use-cases.
class MatcherTest(unittest.TestCase):
    def test_match(self):
        m = Matcher(r"Here is a two-digit number: \d\d")
        self.assertTrue(m.matches("Here is a two-digit number: 42"))
        self.assertFalse(m.matches("Here is a two-digit number: 4"))

    def test_inverse_match(self):
        m = Matcher(r"Here is a two-digit number: \d\d", inverted=True)
        self.assertFalse(m.matches("Here is a two-digit number: 42"))
        self.assertTrue(m.matches("Here is a two-digit number: 4"))

    def test_multiline_match(self):
        m = Matcher("^bar$")
        self.assertFalse(m.matches("foo\nbar\nbaz\n"))
        m = Matcher("(?m)^bar$")
        self.assertTrue(m.matches("foo\nbar\nbaz\n"))


class MultiMatcherTest(unittest.TestCase):
    def setUp(self):
        config = {
            "path_patterns": {
                "python_src": {"pattern": r"\.py$"},
                "java_src": {"pattern": r"\.java$"},
                "scala_src": {"pattern": r"\.scala$"},
                "multi_encodings1": {"pattern": r"\.foo$", "content_encoding": "ascii"},
                "multi_encodings2": {"pattern": r"\.foo$"},
            },
            "content_patterns": {
                "python_header": {
                    "pattern": textwrap.dedent(
                        r"""
                        ^# coding=utf-8
                        # Copyright 20\d\d Pants project contributors \(see CONTRIBUTORS.md\)\.
                        # Licensed under the Apache License, Version 2\.0 \(see LICENSE\)\.

                        from __future__ import absolute_import, division, print_function, unicode_literals
                        """
                    ).lstrip()
                },
                "no_six": {
                    "pattern": r"(?m)(^from six(\.\w+)* +import +)|(^import six\s*$)",
                    "inverted": True,
                },
                "jvm_header": {
                    "pattern": textwrap.dedent(
                        r"""
                        // Copyright 20\d\d Pants project contributors (see CONTRIBUTORS.md).
                        // Licensed under the Apache License, Version 2.0 (see LICENSE).
                        """
                    ).lstrip()
                },
                "dummy": {"pattern": "dummy"},
            },
            "required_matches": {
                "python_src": ("python_header", "no_six"),
                "java_src": ("jvm_header",),
                "scala_src": ("jvm_header",),
                "multi_encodings1": ("dummy",),
                "multi_encodings2": ("dummy",),
            },
        }
        self._rm = MultiMatcher(config)

    def test_get_applicable_content_pattern_names(self):
        def check(expected_content_pattern_names, expected_encoding, path):
            content_pattern_names, encoding = self._rm.get_applicable_content_pattern_names(path)
            self.assertEqual(expected_content_pattern_names, content_pattern_names)
            self.assertEqual(expected_encoding, encoding)

        check({"python_header", "no_six"}, "utf8", "foo/bar/baz.py")
        check({"jvm_header"}, "utf8", "foo/bar/baz.java")
        check({"jvm_header"}, "utf8", "foo/bar/baz.scala")
        check(set(), None, "foo/bar/baz.c")
        check(set(), None, "foo/bar/bazpy")

    def test_check_content(self):
        py_file_content = (
            textwrap.dedent(
                """
                # coding=utf-8
                # Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
                # Licensed under the Apache License, Version 2.0 (see LICENSE).

                from __future__ import absolute_import, division, print_function, unicode_literals

                from foo import bar
                from six.blah import something

                def baz():
                  return bar()
                """
            )
            .lstrip()
            .encode("utf8")
        )
        self.assertEqual(
            (("python_header",), ("no_six",)),
            self._rm.check_content(("python_header", "no_six"), py_file_content, "utf8"),
        )

        self.assertEqual(
            RegexMatchResult("foo/bar/baz.py", ("python_header",), ("no_six",)),
            self._rm.check_source_file("foo/bar/baz.py", py_file_content),
        )

    def test_multiple_encodings_error(self):
        with self.assertRaisesRegex(
            ValueError,
            r"Path matched patterns with multiple content "
            r"encodings \(ascii, utf8\): hello\/world.foo",
        ):
            self._rm.get_applicable_content_pattern_names("hello/world.foo")

    def test_pattern_name_checks(self):
        bad_config1 = {
            "required_matches": {"unknown_path_pattern1": (), "unknown_path_pattern2": ()}
        }
        with self.assertRaisesRegex(
            ValueError,
            "required_matches uses unknown path pattern names: "
            "unknown_path_pattern1, unknown_path_pattern2",
        ):
            MultiMatcher(bad_config1)

        bad_config2 = {
            "path_patterns": {"dummy": {"pattern": "dummy"}},
            "required_matches": {"dummy": ("unknown_content_pattern1",)},
        }
        with self.assertRaisesRegex(
            ValueError,
            "required_matches uses unknown content " "pattern names: unknown_content_pattern1",
        ):
            MultiMatcher(bad_config2)
