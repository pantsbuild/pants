# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_manual import manual
from pants.base.target import TargetDefinitionException
from pants.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.targets.resources import WithResources


@manual.builddict(tags=['java'])
class JavaLibrary(ExportableJvmLibrary, WithResources):
  """A collection of Java code.

  Normally has conceptually-related sources; invoking the ``compile`` goal
  on this target compiles Java and generates classes. Invoking the ``jar``
  goal on this target creates a ``.jar``; but that's an unusual thing to do.
  Instead, a ``jvm_binary`` might depend on this library; that binary is a
  more sensible thing to bundle.
  """

  def __init__(self,
               name,
               sources=None,
               provides=None,
               dependencies=None,
               excludes=None,
               resources=None,
               exclusives=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param Artifact provides:
      The :class:`pants.targets.artifact.Artifact`
      to publish that represents this target outside the repo.
    :param dependencies: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param excludes: List of :class:`pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param resources: An optional list of file paths (DEPRECATED) or
      ``resources`` targets (which in turn point to file paths). The paths
      indicate text file resources to place in this module's jar.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """
    super(JavaLibrary, self).__init__(
        name,
        sources,
        provides,
        dependencies,
        excludes,
        exclusives=exclusives)

    if (sources is None) and (resources is None):
      raise TargetDefinitionException(self, 'Must specify sources and/or resources.')

    self.resources = resources
    self.add_labels('java')
