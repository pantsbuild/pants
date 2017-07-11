# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.targets.python_tests import PythonTests


class PythonLibrary(PythonTarget):
  """A Python library.

  :API: public
  """

  @classmethod
  def alias(cls):
    return 'python_library'

  default_sources_globs = '*.py'
  default_sources_exclude_globs = PythonTests.default_sources_globs
