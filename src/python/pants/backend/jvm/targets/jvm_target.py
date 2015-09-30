# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from twitter.common.collections import OrderedSet

from pants.backend.core.targets.resources import Resources
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jarable import Jarable
from pants.base.payload import Payload
from pants.base.payload_field import ExcludesField, PrimitiveField
from pants.build_graph.target import Target
from pants.util.memo import memoized_property


class JvmTarget(Target, Jarable):
  """A base class for all java module targets that provides path and dependency translation."""

  @classmethod
  def subsystems(cls):
    return super(JvmTarget, cls).subsystems() + (JvmPlatform,)

  def __init__(self,
               address=None,
               payload=None,
               sources=None,
               provides=None,
               excludes=None,
               resources=None,
               no_cache=False,
               services=None,
               platform=None,
               **kwargs):
    """
    :param excludes: List of `exclude <#exclude>`_\s to filter this target's
      transitive dependencies against.
    :param sources: Source code files to build. Paths are relative to the BUILD
       file's directory.
    :type sources: ``Fileset`` (from globs or rglobs) or list of strings
    :param no_cache: If True, this should not be stored in the artifact cache
    :param services: A dict mapping service interface names to the classes owned by this target
                     that implement them.  Keys are fully qualified service class names, values are
                     lists of strings, each string the fully qualified class name of a class owned
                     by this target that implements the service interface and should be
                     discoverable by the jvm service provider discovery mechanism described here:
                     https://docs.oracle.com/javase/6/docs/api/java/util/ServiceLoader.html
    :param str platform: The name of the platform (defined under the jvm-platform subsystem) to use
      for compilation (that is, a key into the --jvm-platform-platforms dictionary). If unspecified,
      the platform will default to the first one of these that exist: (1) the default_platform
      specified for jvm-platform, (2) a platform constructed from whatever java version is returned
      by DistributionLocator.cached().version.
    """
    self.address = address  # Set in case a TargetDefinitionException is thrown early
    payload = payload or Payload()
    excludes = ExcludesField(self.assert_list(excludes, expected_type=Exclude, key_arg='excludes'))
    payload.add_fields({
      'sources': self.create_sources_field(sources, address.spec_path, key_arg='sources'),
      'provides': provides,
      'excludes': excludes,
      'platform': PrimitiveField(platform),
    })
    self._resource_specs = self.assert_list(resources, key_arg='resources')

    super(JvmTarget, self).__init__(address=address, payload=payload,
                                    **kwargs)

    # Service info is only used when generating resources, it should not affect, for example, a
    # compile fingerprint or javadoc fingerprint.  As such, its not a payload field.
    self._services = services or {}

    self.add_labels('jvm')
    if no_cache:
      self.add_labels('no_cache')

  @property
  def platform(self):
    """Platform associated with this target.

    :return: The jvm platform object.
    :rtype: JvmPlatformSettings
    """
    return JvmPlatform.global_instance().get_platform_for_target(self)

  @memoized_property
  def jar_dependencies(self):
    return OrderedSet(self.get_jar_dependencies())

  def mark_extra_invalidation_hash_dirty(self):
    del self.jar_dependencies

  def get_jar_dependencies(self):
    jar_deps = OrderedSet()

    def collect_jar_deps(target):
      if isinstance(target, JarLibrary):
        jar_deps.update(target.payload.jars)

    self.walk(work=collect_jar_deps)
    return jar_deps

  @property
  def has_resources(self):
    return len(self.resources) > 0

  @property
  def traversable_dependency_specs(self):
    for spec in super(JvmTarget, self).traversable_dependency_specs:
      yield spec
    for resource_spec in self._resource_specs:
      yield resource_spec

  @property
  def provides(self):
    return self.payload.provides

  @property
  def resources(self):
    # TODO(John Sirois): Consider removing this convenience:
    #   https://github.com/pantsbuild/pants/issues/346
    # TODO(John Sirois): Introduce a label and replace the type test?
    return [dependency for dependency in self.dependencies if isinstance(dependency, Resources)]

  @property
  def excludes(self):
    return self.payload.excludes

  @property
  def services(self):
    return self._services
