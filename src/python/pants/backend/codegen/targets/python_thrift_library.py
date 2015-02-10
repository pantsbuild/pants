# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.targets.python_target import PythonTarget


class PythonThriftLibrary(PythonTarget):
  """Generates a stub Python library from thrift IDL files."""

  def __init__(self, **kwargs):
    """
    :param sources: thrift source files (If more than one tries to use the same
      namespace, beware https://issues.apache.org/jira/browse/THRIFT-515)
    :type sources: ``Fileset`` or list of strings. Paths are relative to the
      BUILD file's directory.
    :param resources: non-Python resources, e.g. templates, keys, other data (it is
      recommended that your application uses the pkgutil package to access these
      resources in a .zip-module friendly way.)
    """

    super(PythonThriftLibrary, self).__init__(**kwargs)
    self.add_labels('codegen')
