# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys


# A simple example to include in a python 3 binary target

def say_something():
  print('I am a python 3 library method.')
  assert 1/2 == 0.5

  # Return 1/2 for testing the `./pants run` task
  # Note that 1/2 = 0 in python 2 and 1/2 = 0.5 in python 3
  return 1/2  
