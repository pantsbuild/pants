# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_manual import manual
from pants.targets.python_target import PythonTarget


@manual.builddict(tags=["python"])
class PythonLibrary(PythonTarget):
  """Produces a Python library."""

  def __init__(self,
               name,
               sources=(),
               resources=(),
               dependencies=(),
               provides=None,
               compatibility=None,
               exclusives=None):
    """
    :param name: Name of library
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param resources: non-Python resources, e.g. templates, keys, other data (it is
      recommended that your application uses the pkgutil package to access these
      resources in a .zip-module friendly way.)
    :param dependencies: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param provides:
      The :ref:`setup_py <bdict_setup_py>` (implemented by
      :class:`pants.targets.artifact.PythonArtifact`)
      to publish that represents this target outside the repo.
    :param dict exclusives: An optional dict of exclusives tags. See CheckExclusives for details.
    """
    PythonTarget.__init__(self,
        name,
        sources=sources,
        resources=resources,
        dependencies=dependencies,
        provides=provides,
        compatibility=compatibility,
        exclusives=exclusives,
    )
