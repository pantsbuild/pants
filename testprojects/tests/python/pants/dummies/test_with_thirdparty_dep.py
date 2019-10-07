# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from colors import red, strip_color


def test_f():
    assert strip_color(red("foo")) == "foo"
