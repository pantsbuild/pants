# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from generate_docs import markdown_safe


def test_markdown_safe():
    assert "\\*A\\_B&lt;C&amp;" == markdown_safe("*A_B<C&")
