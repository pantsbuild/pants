# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

import pytest


def provide_compile_strategy(testmethod):
  """A decorator for test methods that provides the compilation strategy.

  This is a workaround for the fact that pytest.mark.parametrize does not support methods.
  """
  def wrapped(self):
    for strategy in ['global', 'isolated']:
      try:
        testmethod(self, strategy)
      except Exception as e:
        print("failed for strategy '{}'".format(strategy), file=sys.stderr)
        raise e
  return wrapped
