# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.targets.python_target import PythonTarget


class PythonLibrary(PythonTarget):
  """A Python library.

  :API: public
  """

  # Note that these defaults allow a library and its tests to coexist in the
  # same dir, if so desired.
  default_sources_globs = '*.py'
  # These are the patterns matched by pytest's test discovery.
  default_sources_excludes_globs = ['test_*.py', '*_test.py']
