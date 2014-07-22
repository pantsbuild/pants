# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import OrderedSet

from pants.backend.python.targets.python_target import PythonTarget


class PythonAntlrLibrary(PythonTarget):
  """Generates a stub Python library from Antlr grammar files."""

  def __init__(self, module=None, antlr_version='3.1.3', *args, **kwargs):
    """
    :param name: Name of library
    :param module: everything beneath module is relative to this module name, None if root namespace
    :param antlr_version:
    :param sources: Source code files to compile. Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    :param resources: non-Python resources, e.g. templates, keys, other data (it is
        recommended that your application uses the pkgutil package to access these
        resources in a .zip-module friendly way.)
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    :param dict exclusives: An optional dict of exclusives tags. See CheckExclusives for details.
    """

    super(PythonAntlrLibrary, self).__init__(*args, **kwargs)

    self.module = module
    self.antlr_version = antlr_version
