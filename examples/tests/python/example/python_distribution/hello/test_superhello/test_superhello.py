# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

# hello_package is a python module within the superhello python_distribution.
from hello_package import hello


# Example of writing a test that depends on a python_dist target.
def test_superhello():
  assert hello.hello() == "Super hello"
