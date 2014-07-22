# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.python.targets.python_target import PythonTarget


class PythonThriftLibrary(PythonTarget):
  """Generates a stub Python library from thrift IDL files."""

  def __init__(self, **kwargs):
    """
    :param name: Name of library
    :param sources: thrift source files (If more than one tries to use the same
      namespace, beware https://issues.apache.org/jira/browse/THRIFT-515)
    :type sources: ``Fileset`` or list of strings. Paths are relative to the
      BUILD file's directory.
    :param resources: non-Python resources, e.g. templates, keys, other data (it is
      recommended that your application uses the pkgutil package to access these
      resources in a .zip-module friendly way.)
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    :param dict exclusives: An optional dict of exclusives tags. See CheckExclusives for details.
    """

    super(PythonThriftLibrary, self).__init__(**kwargs)
    self.add_labels('codegen')
