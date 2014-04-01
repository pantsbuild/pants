# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_manual import manual
from pants.targets.jvm_target import JvmTarget
from pants.targets.resources import WithResources


@manual.builddict(tags=['scala'])
class ScalaTests(JvmTarget, WithResources):
  """Tests a Scala library."""

  def __init__(self,
               name,
               sources=None,
               java_sources=None,
               dependencies=None,
               excludes=None,
               resources=None,
               exclusives=None):

    """
    :param name: The name of this module target, addressable via pants via the portion of the spec
      following the colon
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param java_sources:
      :class:`pants.targets.java_library.JavaLibrary` or list of
      JavaLibrary targets this library has a circular dependency on.
      Prefer using dependencies to express non-circular dependencies.
    :param Artifact provides:
      The :class:`pants.targets.artifact.Artifact`
      to publish that represents this target outside the repo.
    :param dependencies: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param excludes: List of :class:`pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param resources: An optional list of Resources that should be in this target's classpath.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """
    super(ScalaTests, self).__init__(name, sources, dependencies, excludes, exclusives=exclusives)

    # TODO(John Sirois): Merge handling with ScalaLibrary.java_sources - which is different and
    # likely more correct.
    self.java_sources = java_sources

    self.resources = resources
    self.add_labels('scala', 'tests')
