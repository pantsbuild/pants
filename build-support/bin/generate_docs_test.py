# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from generate_docs import html_safe, markdown_safe


def test_markdown_safe():
    assert "\\*A\\_B&lt;C&amp;" == markdown_safe("*A_B<C&")


def test_html_safe():
    assert "foo <code>bar==&#x27;baz&#x27;</code> qux" == html_safe("foo `bar=='baz'` qux")
