# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

import pytest


"""Helpers to provide compile strategies to unit tests.

These methods work around the fact that pytest.mark.parametrize does not support methods.
"""

_STRATEGIES = ['global', 'isolated']
_SCOPES = ['apt', 'java', 'scala']

def _wrap(testmethod, setupfun):
  def wrapped(self):
    for strategy in _STRATEGIES:
      try:
        setupfun(self, testmethod, strategy)
      except Exception as e:
        print("failed for strategy '{}'".format(strategy), file=sys.stderr)
        raise e
  return wrapped

def provide_compile_strategies(testmethod):
  """A decorator for test methods that provides the compilation strategy as a parameter."""
  return _wrap(testmethod, lambda self, testmethod, strategy: testmethod(self, strategy))

def set_compile_strategies(testmethod):
  """A decorator for BaseTests which sets strategy options differently for each invoke."""
  def setup(self, testmethod, strategy):
    for scope in _SCOPES:
      self.set_options_for_scope('compile.{}'.format(scope), strategy=strategy)
    testmethod(self)
  return _wrap(testmethod, setup)
