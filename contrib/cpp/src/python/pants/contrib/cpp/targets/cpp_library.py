# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.contrib.cpp.targets.cpp_target import CppTarget


class CppLibrary(CppTarget):
  """A statically linked C++ library."""

  # TODO: public headers
  def __init__(self,
               *args,
               **kwargs):
    super(CppLibrary, self).__init__(*args, **kwargs)
