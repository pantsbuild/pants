# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_manual import manual
from pants.targets import util
from pants.targets.internal import InternalTarget
from pants.targets.with_sources import TargetWithSources


@manual.builddict(tags=['jvm'])
class Resources(InternalTarget, TargetWithSources):
  """A set of files accessible as resources from the JVM classpath.

  Looking for loose files in your application bundle? Those are :ref:`bdict_bundle`\ s.

  Resources are Java-style resources accessible via the ``Class.getResource``
  and friends API. In the ``jar`` goal, the resource files are placed in the resulting `.jar`.
  """

  def __init__(self, name, sources, exclusives=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param sources: A list of filenames representing the resources
      this library provides.
    """
    # TODO(John Sirois): XXX Review why this is an InternalTarget
    InternalTarget.__init__(self, name, dependencies=None, exclusives=exclusives)
    TargetWithSources.__init__(self, name, sources=sources, exclusives=exclusives)

  def has_sources(self, extension=None):
    """``Resources`` never own sources of any particular native type, like for example
    ``JavaLibrary``.
    """
    # TODO(John Sirois): track down the reason for this hack and kill or explain better.
    return extension is None


class WithResources(InternalTarget):
  """A mixin for internal targets that have resources."""

  def __init__(self, *args, **kwargs):
    super(WithResources, self).__init__(*args, **kwargs)
    self._resources = []
    self._raw_resources = None

  @property
  def resources(self):
    if self._raw_resources is not None:
      self._resources = list(self.resolve_all(self._raw_resources, Resources))
      self.update_dependencies(self._resources)
      self._raw_resources = None
    return self._resources

  @resources.setter
  def resources(self, resources):
    self._resources = []
    self._raw_resources = util.resolve(resources)

  def resolve(self):
    # TODO(John Sirois): Clean this up when BUILD parse refactoring is tackled.
    unused_resolved_resources = self.resources

    for resolved in super(WithResources, self).resolve():
      yield resolved
