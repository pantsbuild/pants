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
from pants.base.payload import Payload
from pants.base.payload_field import ExcludesField, PrimitiveField, SetOfPrimitivesField
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
      'resources': PrimitiveField(self.assert_list(resources, key_arg='resources')),
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

    super(JvmTarget, self).__init__(address=address, payload=payload, **kwargs)

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

  @classmethod
  def compute_dependency_specs(cls, kwargs=None, payload=None):
    for spec in super(JvmTarget, cls).compute_dependency_specs(kwargs, payload):
      yield spec

    target_representation = kwargs or payload.as_dict()
    resources = target_representation.get('resources')
    if resources:
      for spec in resources:
        yield spec

    # TODO: https://github.com/pantsbuild/pants/issues/3409
    if Java.is_initialized():
      # Add deps on anything we might need to find plugins.
      # Note that this will also add deps from scala targets to javac plugins, but there's
      # no real harm in that, and the alternative is to check for .java sources, which would
      # eagerly evaluate all the globs, which would be a performance drag for goals that
      # otherwise wouldn't do that (like `list`).
      for spec in Java.global_instance().injectables_specs_for_key('plugin'):
        yield spec

  @property
  def provides(self):
    return self.payload.provides

  @property
  def resources(self):
    # TODO: We should deprecate this method, but doing so will require changes to JVM publishing.
    #   see https://github.com/pantsbuild/pants/issues/4568
    return [dependency for dependency in self.dependencies if isinstance(dependency, Resources)]

  @property
  def excludes(self):
    return self.payload.excludes

  @property
  def services(self):
    return self._services
