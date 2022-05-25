# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap

import pytest

from pants.backend.project_info.regex_lint import (
    Matcher,
    MultiMatcher,
    RegexMatchResult,
    ValidationConfig,
)


# Note that some parts of these tests are just exercising various capabilities of the regex engine.
# This is not something we technically need to test, but it's useful for sanity checking, and for
# showcasing common use-cases.
class TestMatcher:
    def test_match(self):
        m = Matcher(r"Here is a two-digit number: \d\d")
        assert m.matches("Here is a two-digit number: 42")
        assert not m.matches("Here is a two-digit number: 4")

    def test_inverse_match(self):
        m = Matcher(r"Here is a two-digit number: \d\d", inverted=True)
        assert not m.matches("Here is a two-digit number: 42")
        assert m.matches("Here is a two-digit number: 4")

    def test_multiline_match(self):
        m = Matcher("^bar$")
        assert not m.matches("foo\nbar\nbaz\n")
        m = Matcher("(?m)^bar$")
        assert m.matches("foo\nbar\nbaz\n")


class TestMultiMatcherTest:
    @pytest.fixture()
    def matcher(self) -> MultiMatcher:
        config = {
            "path_patterns": [
                {"name": "python_src", "pattern": r"\.py$"},
                {"name": "java_src", "pattern": r"\.java$"},
                {"name": "scala_src", "pattern": r"\.scala$"},
                {"name": "multi_encodings1", "pattern": r"\.foo$", "content_encoding": "ascii"},
                {"name": "multi_encodings2", "pattern": r"\.foo$"},
            ],
            "content_patterns": [
                {
                    "name": "python_header",
                    "pattern": textwrap.dedent(
                        r"""
                        ^# coding=utf-8
                        # Copyright 20\d\d Pants project contributors \(see CONTRIBUTORS.md\)\.
                        # Licensed under the Apache License, Version 2\.0 \(see LICENSE\)\.

                        from __future__ import absolute_import, division, print_function, unicode_literals
                        """
                    ).lstrip(),
                },
                {
                    "name": "no_six",
                    "pattern": r"(?m)(^from six(\.\w+)* +import +)|(^import six\s*$)",
                    "inverted": True,
                },
                {
                    "name": "jvm_header",
                    "pattern": textwrap.dedent(
                        r"""
                        // Copyright 20\d\d Pants project contributors (see CONTRIBUTORS.md).
                        // Licensed under the Apache License, Version 2.0 (see LICENSE).
                        """
                    ).lstrip(),
                },
                {"name": "dummy", "pattern": "dummy"},
            ],
            "required_matches": {
                "python_src": ("python_header", "no_six"),
                "java_src": ("jvm_header",),
                "scala_src": ("jvm_header",),
                "multi_encodings1": ("dummy",),
                "multi_encodings2": ("dummy",),
            },
        }
        return MultiMatcher(ValidationConfig.from_dict(config))

    def test_get_applicable_content_pattern_names(self, matcher: MultiMatcher) -> None:
        def check(expected_content_pattern_names, expected_encoding, path):
            content_pattern_names, encoding = matcher.get_applicable_content_pattern_names(path)
            assert expected_content_pattern_names == content_pattern_names
            assert expected_encoding == encoding

        check({"python_header", "no_six"}, "utf8", "foo/bar/baz.py")
        check({"jvm_header"}, "utf8", "foo/bar/baz.java")
        check({"jvm_header"}, "utf8", "foo/bar/baz.scala")
        check(set(), None, "foo/bar/baz.c")
        check(set(), None, "foo/bar/bazpy")

    def test_check_content(self, matcher: MultiMatcher) -> None:
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
        assert RegexMatchResult("f.py", ("python_header",), ("no_six",)) == matcher.check_content(
            "f.py", py_file_content, ("python_header", "no_six"), "utf8"
        )

    def test_multiple_encodings_error(self, matcher: MultiMatcher) -> None:
        with pytest.raises(
            ValueError,
            match=r"Path matched patterns with multiple content encodings \(ascii, utf8\): hello\/world.foo",
        ):
            matcher.get_applicable_content_pattern_names("hello/world.foo")

    def test_pattern_name_checks(self, matcher: MultiMatcher) -> None:
        bad_config1 = {
            "path_patterns": [],
            "content_patterns": [],
            "required_matches": {"unknown_path_pattern1": (), "unknown_path_pattern2": ()},
        }
        with pytest.raises(
            ValueError,
            match="required_matches uses unknown path pattern names: unknown_path_pattern1, unknown_path_pattern2",
        ):
            MultiMatcher(ValidationConfig.from_dict(bad_config1))

        bad_config2 = {
            "path_patterns": [{"name": "dummy", "pattern": "dummy"}],
            "content_patterns": [],
            "required_matches": {"dummy": ("unknown_content_pattern1",)},
        }
        with pytest.raises(
            ValueError,
            match="required_matches uses unknown content "
            "pattern names: unknown_content_pattern1",
        ):
            MultiMatcher(ValidationConfig.from_dict(bad_config2))
