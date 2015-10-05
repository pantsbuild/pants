# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re


TIMEOUT_TAG = 'timeout'


class TestTargetMixin(object):
  """Mix this in with test targets to get timeout and other test-specific target parameters."""

  def __init__(self, timeout = None, **kwargs):
    self._timeout = timeout
    super(TestTargetMixin, self).__init__(**kwargs)

  @property
  def timeout(self):
    return self._timeout
