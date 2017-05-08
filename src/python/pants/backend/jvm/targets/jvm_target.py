# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from twitter.common.collections import OrderedSet

from pants.backend.jvm.subsystems.java import Java
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jarable import Jarable
from pants.base.deprecated import deprecated_conditional
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import ExcludesField, PrimitiveField, SetOfPrimitivesField
from pants.build_graph.address import Address
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.java.jar.exclude import Exclude
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
               exports=None,
               fatal_warnings=None,
               zinc_file_manager=None,
               # Some subclasses can have both .java and .scala sources
               # (e.g., JUnitTests, JvmBinary, even ScalaLibrary), so it's convenient
               # to have both plugins settings here, even though for other subclasses
               # (e.g., JavaLibrary) only one will be relevant.
               javac_plugins=None,
               javac_plugin_args=None,
               scalac_plugins=None,
               scalac_plugin_args=None,
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
    :param str platform: The name of the platform (defined under the jvm-platform subsystem) to use
                         for compilation (that is, a key into the --jvm-platform-platforms
                         dictionary). If unspecified, the platform will default to the first one of
                         these that exist: (1) the default_platform specified for jvm-platform,
                         (2) a platform constructed from whatever java version is returned by
                         DistributionLocator.cached().version.
    :param bool strict_deps: When True, only the directly declared deps of the target will be used
                             at compilation time. This enforces that all direct deps of the target
                             are declared, and can improve compilation speed due to smaller
                             classpaths. Transitive deps are always provided at runtime.
    :param list exports: A list of exported targets, which will be accessible to dependents even
                         with strict_deps turned on. A common use case is for library targets to
                         to export dependencies that it knows its dependents will need. Then any
                         dependents of that library target will have access to those dependencies
                         even when strict_deps is True. Note: exports is transitive, which means
                         dependents have access to the closure of exports. An example will be that
                         if A exports B, and B exports C, then any targets that depends on A will
                         have access to both B and C.
    :param bool fatal_warnings: Whether to turn warnings into errors for this target.  If present,
                                takes priority over the language's fatal-warnings option.
    :param bool zinc_file_manager: Whether to use zinc provided file manager that allows
                                   transactional rollbacks, but in certain cases may conflict with
                                   user libraries.
    :param javac_plugins: names of compiler plugins to use when compiling this target with javac.
    :param dict javac_plugin_args: Map from javac plugin name to list of arguments for that plugin.
    :param scalac_plugins: names of compiler plugins to use when compiling this target with scalac.
    :param dict scalac_plugin_args: Map from scalac plugin name to list of arguments for that plugin.
    """
    deprecated_conditional(lambda: resources is not None, '1.5.0.dev0',
                           'The `resources=` JVM target argument', 'Use `dependencies=` instead.')

    self.address = address  # Set in case a TargetDefinitionException is thrown early
    payload = payload or Payload()
    excludes = ExcludesField(self.assert_list(excludes, expected_type=Exclude, key_arg='excludes'))

    payload.add_fields({
      'sources': self.create_sources_field(sources, address.spec_path, key_arg='sources'),
      'provides': provides,
      'excludes': excludes,
      'platform': PrimitiveField(platform),
      'strict_deps': PrimitiveField(strict_deps),
      'exports': SetOfPrimitivesField(exports),
      'fatal_warnings': PrimitiveField(fatal_warnings),
      'zinc_file_manager': PrimitiveField(zinc_file_manager),
      'javac_plugins': SetOfPrimitivesField(javac_plugins),
      'javac_plugin_args': PrimitiveField(javac_plugin_args),
      'scalac_plugins': SetOfPrimitivesField(scalac_plugins),
      'scalac_plugin_args': PrimitiveField(scalac_plugin_args),
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
  def exports(self):
    return self.payload.exports

  @property
  def exports_targets(self):
    """A list of exported targets, which will be accessible to dependents.

    :return: See constructor.
    :rtype: list
    """
    exports_targets = []
    for spec in self.payload.exports:
      addr = Address.parse(spec, relative_to=self.address.spec_path)
      target = self._build_graph.get_target(addr)
      if target.is_thrift:
        for dep in self.dependencies:
          if dep != target and dep.is_synthetic and dep.derived_from == target:
            target = dep
            break

      if target not in self.dependencies:
        # This means the exported target was not injected before "self",
        # thus it's not a valid export.
        raise TargetDefinitionException(self,
          'Invalid exports: "{}" is not a dependency of {}'.format(spec, self))
      exports_targets.append(target)

    return exports_targets

  @property
  def fatal_warnings(self):
    """If set, overrides the platform's default fatal_warnings setting.

    :return: See constructor.
    :rtype: bool or None
    """
    return self.payload.fatal_warnings

  @property
  def zinc_file_manager(self):
    """If false, the default file manager will be used instead of the zinc provided one.

    :return: See constructor.
    :rtype: bool or None
    """
    return self.payload.zinc_file_manager

  @property
  def javac_plugins(self):
    """The names of compiler plugins to use when compiling this target with javac.

    :return: See constructor.
    :rtype: list of strings.
    """
    return self.payload.javac_plugins

  @property
  def javac_plugin_args(self):
    """Map from javac plugin name to list of args for that plugin.

    :return: See constructor.
    :rtype: map from string to list of strings.
    """
    return self.payload.javac_plugin_args

  @property
  def scalac_plugins(self):
    """The names of compiler plugins to use when compiling this target with scalac.

    :return: See constructor.
    :rtype: list of strings.
    """
    return self.payload.scalac_plugins

  @property
  def scalac_plugin_args(self):
    """Map from scalac plugin name to list of args for that plugin.

    :return: See constructor.
    :rtype: map from string to list of strings.
    """
    return self.payload.scalac_plugin_args

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

  @property
  def is_thrift(self):
    return False
