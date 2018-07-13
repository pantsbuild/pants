# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

# hello_package is a python module within the fasthello python_distribution.
from hello_package import hello


# Example of writing a test that depends on a python_dist target.
def test_fasthello():
  assert hello.hello() == '\n'.join([
    'Hello from C!',
    'Hello from C++!',
  ])
