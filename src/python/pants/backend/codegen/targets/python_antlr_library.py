# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import OrderedSet

from pants.base.build_manual import manual
from pants.backend.python.targets.python_target import PythonTarget


@manual.builddict(tags=["python"])
class PythonAntlrLibrary(PythonTarget):
  """Generates a stub Python library from Antlr grammar files."""

  def __init__(self, module=None, antlr_version='3.1.3', *args, **kwargs):
    """
    :param name: Name of library
    :param module: everything beneath module is relative to this module name, None if root namespace
    :param antlr_version:
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param resources: non-Python resources, e.g. templates, keys, other data (it is
        recommended that your application uses the pkgutil package to access these
        resources in a .zip-module friendly way.)
    :param dependencies: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param dict exclusives: An optional dict of exclusives tags. See CheckExclusives for details.
    """

    super(PythonAntlrLibrary, self).__init__(*args, **kwargs)

    self.module = module
    self.antlr_version = antlr_version
