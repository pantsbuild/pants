# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from twitter.common.collections import OrderedSet

from pants.backend.jvm.subsystems.java import Java
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jarable import Jarable
from pants.base.payload import Payload
from pants.base.payload_field import ExcludesField, PrimitiveField
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.util.memo import memoized_property


class JvmTarget(Target, Jarable):
  """A base class for all java module targets that provides path and dependency translation.

  :API: public
  """

  @classmethod
  def subsystems(cls):
    return super(JvmTarget, cls).subsystems() + (Java, JvmPlatform)

  def __init__(self,
               address=None,
               payload=None,
               sources=None,
               provides=None,
               excludes=None,
               resources=None,
               services=None,
               platform=None,
               strict_deps=None,
               fatal_warnings=None,
               **kwargs):
    """
    :API: public

    :param excludes: List of `exclude <#exclude>`_\s to filter this target's
      transitive dependencies against.
    :param sources: Source code files to build. Paths are relative to the BUILD
      file's directory.
    :type sources: ``Fileset`` (from globs or rglobs) or list of strings
    :param services: A dict mapping service interface names to the classes owned by this target
                     that implement them.  Keys are fully qualified service class names, values are
                     lists of strings, each string the fully qualified class name of a class owned
                     by this target that implements the service interface and should be
                     discoverable by the jvm service provider discovery mechanism described here:
                     https://docs.oracle.com/javase/6/docs/api/java/util/ServiceLoader.html
    :param platform: The name of the platform (defined under the jvm-platform subsystem) to use
      for compilation (that is, a key into the --jvm-platform-platforms dictionary). If unspecified,
      the platform will default to the first one of these that exist: (1) the default_platform
      specified for jvm-platform, (2) a platform constructed from whatever java version is returned
      by DistributionLocator.cached().version.
    :type platform: str
    :param strict_deps: When True, only the directly declared deps of the target will be used at
      compilation time. This enforces that all direct deps of the target are declared, and can
      improve compilation speed due to smaller classpaths. Transitive deps are always provided
      at runtime.
    :type strict_deps: bool
    :param fatal_warnings: Whether to turn warnings into errors for this target.  If present,
                           takes priority over the language's fatal-warnings option.
    :type fatal_warnings: bool
    """
    self.address = address  # Set in case a TargetDefinitionException is thrown early
    payload = payload or Payload()
    excludes = ExcludesField(self.assert_list(excludes, expected_type=Exclude, key_arg='excludes'))

    payload.add_fields({
      'sources': self.create_sources_field(sources, address.spec_path, key_arg='sources'),
      'provides': provides,
      'excludes': excludes,
      'platform': PrimitiveField(platform),
      'strict_deps': PrimitiveField(strict_deps),
      'fatal_warnings': PrimitiveField(fatal_warnings),
    })
    self._resource_specs = self.assert_list(resources, key_arg='resources')

    super(JvmTarget, self).__init__(address=address, payload=payload,
                                    **kwargs)

    # Service info is only used when generating resources, it should not affect, for example, a
    # compile fingerprint or javadoc fingerprint.  As such, its not a payload field.
    self._services = services or {}

    self.add_labels('jvm')

  @property
  def strict_deps(self):
    """If set, whether to limit compile time deps to those that are directly declared.

    :return: See constructor.
    :rtype: bool or None
    """
    return self.payload.strict_deps

  @property
  def fatal_warnings(self):
    """If set, overrides the platform's default fatal_warnings setting.

    :return: See constructor.
    :rtype: bool or None
    """
    return self.payload.fatal_warnings

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
    # Add deps on anything we might need to find plugins.
    # Note that this will also add deps from scala targets to javac plugins, but there's
    # no real harm in that, and the alternative is to check for .java sources, which would
    # eagerly evaluate all the globs, which would be a performance drag for goals that
    # otherwise wouldn't do that (like `list`).
    for spec in Java.global_plugin_dependency_specs():
      # Ensure that if this target is the plugin, we don't create a dep on ourself.
      # Note that we can't do build graph dep checking here, so we will create a dep on our own
      # deps, thus creating a cycle. Therefore an in-repo plugin that has JvmTarget deps
      # can only be applied globally via the Java subsystem if you publish it first and then
      # reference it as a JarLibrary (it can still be applied directly from the repo on targets
      # that explicitly depend on it though). This is an unfortunate gotcha that will be addressed
      # in the new engine.
      if spec != self.address.spec:
        yield spec

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
