# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from textwrap import dedent

from migrate_to_toml_config import generate_new_config

from pants.util.contextutil import temporary_dir


def assert_rewrite(*, original: str, expected: str) -> None:
    with temporary_dir() as tmpdir:
        build = Path(tmpdir, "pants.ini")
        build.write_text(original)
        result = generate_new_config(build)
    assert result == expected.splitlines()


def test_fully_automatable_config() -> None:
    """We should be able to safely convert all of this config without any issues."""
    assert_rewrite(
        original=dedent(
            """\
            [GLOBAL]
            bool_opt1: false
            bool_opt2: True
            int_opt: 10
            float_opt: 5.0

            [str_values]
            normal: .isort.cfg
            version: isort>=4.8
            target: src/python:example
            path: /usr/bin/test.txt
            glob: *.txt
            fromfile: @build-support/example.txt
            interpolation: %(foo)s/example
            """
        ),
        expected=dedent(
            """\
            [GLOBAL]
            bool_opt1 = false
            bool_opt2 = true
            int_opt = 10
            float_opt = 5.0

            [str_values]
            normal = ".isort.cfg"
            version = "isort>=4.8"
            target = "src/python:example"
            path = "/usr/bin/test.txt"
            glob = "*.txt"
            fromfile = "@build-support/example.txt"
            interpolation = "%(foo)s/example"
            """
        ),
    )


def test_different_key_value_symbols() -> None:
    """You can use both `:` or `=` in INI for key-value pairs."""
    assert_rewrite(
        original=dedent(
            """\
            [GLOBAL]
            o1: a
            o2:  a
            o3 : a
            o4  :  a
            o5 :a
            o6  :a
            o7= a
            o8=  a
            o9 = a
            o10  =  a
            o11 =a
            o12  =a
            """
        ),
        expected=dedent(
            """\
            [GLOBAL]
            o1 = "a"
            o2 = "a"
            o3 = "a"
            o4 = "a"
            o5 = "a"
            o6 = "a"
            o7 = "a"
            o8 = "a"
            o9 = "a"
            o10 = "a"
            o11 = "a"
            o12 = "a"
            """
        ),
    )


def test_comments() -> None:
    """We don't mess with comments."""
    assert_rewrite(
        original=dedent(
            """\
            [GLOBAL]
            bool_opt1: False  # Good riddance!
            bool_opt2: True
            int_opt: 10  ; semicolons matter too
            # commented_out: 10
            ; commented_out: 10

            # Comments on new lines should be preserved
            ; Semicolon comments should also be preserved
            [isort]  # comments on section headers shouldn't matter because we don't convert sections
            config: .isort.cfg
            """
        ),
        expected=dedent(
            """\
            [GLOBAL]
            bool_opt1: False  # Good riddance!
            bool_opt2 = true
            int_opt: 10  ; semicolons matter too
            # commented_out: 10
            ; commented_out: 10

            # Comments on new lines should be preserved
            ; Semicolon comments should also be preserved
            [isort]  # comments on section headers shouldn't matter because we don't convert sections
            config = ".isort.cfg"
            """
        ),
    )


def test_list_options() -> None:
    """We can safely update one-line lists.

    The list members will already be correctly quoted for us. All that we need to update is the
    option->key symbol and simple `+` adds and `-` removes.
    """
    assert_rewrite(
        original=dedent(
            """\
            [GLOBAL]
            l1: []
            l2: [0, 1]
            l3: ["a", "b"]
            l4: ['a', 'b']
            l5: [ "a", 'b' ]
            l6: +["a", "b"]
            l7: -["x", "y"]
            l8: +["a", "b"],-["x", "y"]
            l9: [[0], [1]]
            l10: [0, 1]  # comment
            l11: [0, 1]  ; comment
            """
        ),
        expected=dedent(
            """\
            [GLOBAL]
            l1 = []
            l2 = [0, 1]
            l3 = ["a", "b"]
            l4 = ['a', 'b']
            l5 = [ "a", 'b' ]
            l6.add = ["a", "b"]
            l7.remove = ["x", "y"]
            l8: +["a", "b"],-["x", "y"]
            l9: [[0], [1]]
            l10: [0, 1]  # comment
            l11: [0, 1]  ; comment
            """
        ),
    )


def test_dict_options() -> None:
    """We can safely preserve one-line dict values, which only need to be wrapped in quotes to work
    properly."""
    assert_rewrite(
        original=dedent(
            """\
            [GLOBAL]
            d1: {}
            d2: {"a": 0}
            d3: {'a': 0}
            d4: { "a": 0, "b: 0" }
            d5: {"a": {"nested": 0}}
            d6: {"a": 0}  # comment
            d7: {"a": 0}  ; comment
            """
        ),
        expected=dedent(
            """\
            [GLOBAL]
            d1 = \"""{}\"""
            d2 = \"""{"a": 0}\"""
            d3 = \"""{'a': 0}\"""
            d4 = \"""{ "a": 0, "b: 0" }\"""
            d5: {"a": {"nested": 0}}
            d6: {"a": 0}  # comment
            d7: {"a": 0}  ; comment
            """
        ),
    )


def test_multiline_options_ignored() -> None:
    """Don't mess with multiline options, which are too difficult to get right."""
    original = dedent(
        """\
        [GLOBAL]
        multiline_string: in a galaxy far,
           far, away...

        l1: [
            'foo',
          ]

        l2: ['foo',
             'bar']

        d: {
            'a': 0,
          }
        """
    )
    assert_rewrite(original=original, expected=original)
