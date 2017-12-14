# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


# A simple example to include in a python 2 binary target

def say_something():
  print('I am a python 2 library method.')
  # Note that ascii exists as a built-in in Python 3 and
  # does not exist in Python 2.
  try:
    ret = ascii
  except NameError:
    ret = None
  assert ret is None
  return ret
