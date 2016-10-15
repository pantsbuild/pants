# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class CodegenLibraryMixin(object):
  """Tags a target containing IDL files used in codegen.

  Tasks may use this to detect targets whose associated programming language source files
  (as passed to a compiler or interpreter) were not human-authored (e.g., to exclude
  them from linting.)
  """
