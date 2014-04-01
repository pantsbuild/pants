# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_manual import manual
from pants.targets.python_target import PythonTarget


@manual.builddict(tags=["python"])
class PythonThriftLibrary(PythonTarget):
  """Generates a stub Python library from thrift IDL files."""

  def __init__(self, name,
               sources=None,
               resources=None,
               dependencies=None,
               provides=None,
               exclusives=None):
    """
    :param name: Name of library
    :param sources: thrift source files (If more than one tries to use the same
      namespace, beware https://issues.apache.org/jira/browse/THRIFT-515)
    :param resources: non-Python resources, e.g. templates, keys, other data (it is
      recommended that your application uses the pkgutil package to access these
      resources in a .zip-module friendly way.)
    :param dependencies: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param dict exclusives: An optional dict of exclusives tags. See CheckExclusives for details.
    """
    super(PythonThriftLibrary, self).__init__(name, sources, resources, dependencies, provides,
                                              exclusives=exclusives)
