# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.base.payload import Payload
from pants.base.payload_field import JarsField
from pants.build_graph.target import Target


class ManagedJarDependencies(Target):
  """A set of pinned external artifact versions to apply transitively."""

  def __init__(self, payload=None, artifacts=None, **kwargs):
    """
    :param artifacts: List of `jar <#jar>`_\s or specs to jar_library targets with pinned versions.
      Versions are pinned per (org, name, classifier, ext) artifact coordinate (excludes, etc are
      ignored for the purposes of pinning).
    """
    jar_objects, self._library_specs = self._split_jars_and_specs(artifacts)
    payload = payload or Payload()
    payload.add_fields({
      'artifacts': JarsField(jar_objects),
    })
    super(ManagedJarDependencies, self).__init__(payload=payload, **kwargs)

  @property
  def traversable_specs(self):
    return iter(self.library_specs)

  @property
  def library_specs(self):
    """Lists of specs to resolve to jar_libraries containing more jars."""
    return self._library_specs

  def _split_jars_and_specs(self, jars):
    library_specs = []
    jar_objects = []
    for item in jars:
      if isinstance(item, JarDependency):
        jar_objects.append(item)
      else:
        library_specs.append(item)
    return jar_objects, library_specs
