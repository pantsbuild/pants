# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import c_greet
import cpp_greet


def hello():
  print(c_greet.c_greet())
  print(cpp_greet.cpp_greet())
