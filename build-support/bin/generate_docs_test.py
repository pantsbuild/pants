# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from generate_docs import html_safe, markdown_safe, value_strs_iter


def test_markdown_safe():
    assert "\\*A\\_B&lt;C&amp;" == markdown_safe("*A_B<C&")


def test_html_safe():
    assert "foo <code>bar==&#x27;baz&#x27;</code> qux" == html_safe("foo `bar=='baz'` qux")


def test_gather_value_strs():
    help_info = {
        "a": "foo",
        "b": ["bar", 5, "baz"],
        "c": 42,
        "d": True,
        "e": {"f": 5, "g": "qux", "h": {"i": "quux"}},
    }
    assert set(value_strs_iter(help_info)) == {"foo", "bar", "baz", "qux", "quux"}
