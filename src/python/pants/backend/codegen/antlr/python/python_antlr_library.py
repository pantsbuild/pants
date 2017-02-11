# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.targets.python_target import PythonTarget


class PythonAntlrLibrary(PythonTarget):
  """A Python library generated from Antlr grammar files."""

  # TODO: Deprecate antlr_version=, and replace it with a compiler= argument, that takes logical
  # names (antlr3, antlr4), like JavaAntlrLibrary.
  def __init__(self, module=None, antlr_version='3.1.3', *args, **kwargs):
    """
    :param module: everything beneath module is relative to this module name, None if root namespace
    :param antlr_version:
    """

    super(PythonAntlrLibrary, self).__init__(*args, **kwargs)

    self.module = module
    self.antlr_version = antlr_version
