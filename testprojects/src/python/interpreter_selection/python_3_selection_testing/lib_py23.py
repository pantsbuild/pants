# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


def say_something():
  print('I am a python 2/3 compatible library method.')
  # Note that ascii exists as a built-in in Python 3 and
  # does not exist in Python 2.
  try:
    ret = ascii
  except NameError:
    ret = 'Python2'
  else:
    ret = 'Python3'
  return ret
