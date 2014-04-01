# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import maybe_list

from pants.base.build_manual import manual
from pants.base.target import Target, TargetDefinitionException
from pants.targets import util
from pants.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.targets.java_library import JavaLibrary
from pants.targets.resources import WithResources


@manual.builddict(tags=['scala'])
class ScalaLibrary(ExportableJvmLibrary, WithResources):
  """A collection of Scala code.

  Normally has conceptually-related sources; invoking the ``compile`` goal
  on this target compiles scala and generates classes. Invoking the ``bundle``
  goal on this target creates a ``.jar``; but that's an unusual thing to do.
  Instead, a ``jvm_binary`` might depend on this library; that binary is a
  more sensible thing to bundle.
  """

  def __init__(self,
               name,
               sources=None,
               java_sources=None,
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
    :param resources: An optional list of paths (DEPRECATED) or ``resources``
      targets containing resources that belong on this library's classpath.
    :param exclusives: An optional list of exclusives tags.
    """
    super(ScalaLibrary, self).__init__(
        name,
        sources,
        provides,
        dependencies,
        excludes,
        exclusives=exclusives)

    if (sources is None) and (resources is None):
      raise TargetDefinitionException(self, 'Must specify sources and/or resources.')

    self.resources = resources

    self._java_sources = []
    self._raw_java_sources = util.resolve(java_sources)

    self.add_labels('scala')

  @property
  def java_sources(self):
    if self._raw_java_sources is not None:
      self._java_sources = list(Target.resolve_all(maybe_list(self._raw_java_sources, Target),
                                                   JavaLibrary))

      self._raw_java_sources = None

      # TODO(John Sirois): reconsider doing this auto-linking.
      # We have circular java/scala dep, add an inbound dependency edge from java to scala in this
      # case to force scala compilation to precede java - since scalac supports generating java
      # stubs for these cycles and javac does not this is both necessary and always correct.
      for java_target in self._java_sources:
        java_target.update_dependencies([self])
    return self._java_sources

  def resolve(self):
    # TODO(John Sirois): Clean this up when BUILD parse refactoring is tackled.
    unused_resolved_java_sources = self.java_sources

    for resolved in super(ScalaLibrary, self).resolve():
      yield resolved
