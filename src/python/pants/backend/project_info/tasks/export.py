# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
from collections import defaultdict

import six
from twitter.common.collections import OrderedSet

from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.resolve_subsystem import JvmResolveSubsystem
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.coursier_resolve import CoursierMixin
from pants.backend.jvm.tasks.ivy_task_mixin import IvyTaskMixin
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.pex_build_util import has_python_requirements
from pants.backend.python.tasks.resolve_requirements_task_base import ResolveRequirementsTaskBase
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.java.jar.jar_dependency_utils import M2Coordinate
from pants.python.python_repos import PythonRepos
from pants.task.console_task import ConsoleTask
from pants.util.memo import memoized_property


# Changing the behavior of this task may affect the IntelliJ Pants plugin.
# Please add @yic to reviews for this file.
class ExportTask(ResolveRequirementsTaskBase, IvyTaskMixin, CoursierMixin):
  """Base class for generating a json-formattable blob of data about the target graph.

  Subclasses can invoke the generate_targets_map method to get a dictionary of plain datastructures
  (dicts, lists, strings) that can be easily read and exported to various formats.
  """

  # FORMAT_VERSION_NUMBER: Version number for identifying the export file format output. This
  # version number should change when there is a change to the output format.
  #
  # Major Version 1.x.x : Increment this field when there is a major format change
  # Minor Version x.1.x : Increment this field when there is a minor change that breaks backward
  #   compatibility for an existing field or a field is removed.
  # Patch version x.x.1 : Increment this field when a minor format change that just adds information
  #   that an application can safely ignore.
  #
  # Note format changes in src/docs/export.md and update the Changelog section.
  #
  DEFAULT_EXPORT_VERSION = '1.0.10'

  @classmethod
  def subsystem_dependencies(cls):
    return super(ExportTask, cls).subsystem_dependencies() + (
      DistributionLocator, JvmPlatform, PythonSetup, PythonRepos
    )

  class SourceRootTypes(object):
    """Defines SourceRoot Types Constants"""
    SOURCE = 'SOURCE'  # Source Target
    TEST = 'TEST'  # Test Target
    SOURCE_GENERATED = 'SOURCE_GENERATED'  # Code Gen Source Targets
    EXCLUDED = 'EXCLUDED'  # Excluded Target
    RESOURCE = 'RESOURCE'  # Resource belonging to Source Target
    TEST_RESOURCE = 'TEST_RESOURCE'  # Resource belonging to Test Target

  @staticmethod
  def _is_jvm(dep):
    return  isinstance(dep, (JarLibrary, JvmTarget, JvmApp))

  @staticmethod
  def _jar_id(jar):
    """Create a string identifier for the IvyModuleRef key.
    :param IvyModuleRef jar: key for a resolved jar
    :returns: String representing the key as a maven coordinate
    """
    if jar.rev:
      return '{0}:{1}:{2}'.format(jar.org, jar.name, jar.rev)
    else:
      return '{0}:{1}'.format(jar.org, jar.name)

  @staticmethod
  def _exclude_id(jar):
    """Create a string identifier for the Exclude key.
    :param Exclude jar: key for an excluded jar
    :returns: String representing the key as a maven coordinate
    """
    return '{0}:{1}'.format(jar.org, jar.name) if jar.name else jar.org

  @classmethod
  def register_options(cls, register):
    super(ExportTask, cls).register_options(register)
    register('--libraries', default=True, type=bool,
             help='Causes libraries to be output.')
    register('--libraries-sources', type=bool,
             help='Causes libraries with sources to be output.')
    register('--libraries-javadocs', type=bool,
             help='Causes libraries with javadocs to be output.')
    register('--sources', type=bool,
             help='Causes sources to be output.')
    register('--formatted', type=bool, implicit_value=False,
             help='Causes output to be a single line of JSON.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(ExportTask, cls).prepare(options, round_manager)
    if options.libraries or options.libraries_sources or options.libraries_javadocs:
      round_manager.require_data('java')
      round_manager.require_data('scala')

  @memoized_property
  def _interpreter_cache(self):
    return PythonInterpreterCache(PythonSetup.global_instance(),
                                  PythonRepos.global_instance(),
                                  logger=self.context.log.debug)

  def resolve_jars(self, targets):
    # TODO: Why is this computed directly here instead of taking from the actual product
    # computed by the {Ivy,Coursier}Resolve task?
    executor = SubprocessExecutor(DistributionLocator.cached())
    confs = []
    if self.get_options().libraries:
      confs.append('default')
    if self.get_options().libraries_sources:
      confs.append('sources')
    if self.get_options().libraries_javadocs:
      confs.append('javadoc')

    compile_classpath = None

    if confs:
      compile_classpath = ClasspathProducts(self.get_options().pants_workdir)
      if JvmResolveSubsystem.global_instance().get_options().resolver == 'ivy':
        IvyTaskMixin.resolve(self, executor=executor,
                                          targets=targets,
                                          classpath_products=compile_classpath,
                                          confs=confs)
      else:
        CoursierMixin.resolve(self, targets, compile_classpath,
                              sources=self.get_options().libraries_sources,
                              javadoc=self.get_options().libraries_javadocs)

    return compile_classpath

  def generate_targets_map(self, targets, classpath_products=None):
    """Generates a dictionary containing all pertinent information about the target graph.

    The return dictionary is suitable for serialization by json.dumps.
    :param targets: The list of targets to generate the map for.
    :param classpath_products: Optional classpath_products. If not provided when the --libraries
      option is `True`, this task will perform its own jar resolution.
    """
    targets_map = {}
    resource_target_map = {}
    python_interpreter_targets_mapping = defaultdict(list)

    if self.get_options().libraries:
      # NB(gmalmquist): This supports mocking the classpath_products in tests.
      if classpath_products is None:
        classpath_products = self.resolve_jars(targets)
    else:
      classpath_products = None

    target_roots_set = set(self.context.target_roots)

    def process_target(current_target):
      """
      :type current_target:pants.build_graph.target.Target
      """
      def get_target_type(tgt):
        def is_test(t):
          return isinstance(t, JUnitTests) or isinstance(t, PythonTests)
        if is_test(tgt):
          return ExportTask.SourceRootTypes.TEST
        else:
          if (isinstance(tgt, Resources) and
              tgt in resource_target_map and
                is_test(resource_target_map[tgt])):
            return ExportTask.SourceRootTypes.TEST_RESOURCE
          elif isinstance(tgt, Resources):
            return ExportTask.SourceRootTypes.RESOURCE
          else:
            return ExportTask.SourceRootTypes.SOURCE

      info = {
        'targets': [],
        'libraries': [],
        'roots': [],
        'id': current_target.id,
        'target_type': get_target_type(current_target),
        # NB: is_code_gen should be removed when export format advances to 1.1.0 or higher
        'is_code_gen': current_target.is_synthetic,
        'is_synthetic': current_target.is_synthetic,
        'pants_target_type': self._get_pants_target_alias(type(current_target)),
      }

      if not current_target.is_synthetic:
        info['globs'] = current_target.globs_relative_to_buildroot()
        if self.get_options().sources:
          info['sources'] = list(current_target.sources_relative_to_buildroot())

      info['transitive'] = current_target.transitive
      info['scope'] = str(current_target.scope)
      info['is_target_root'] = current_target in target_roots_set

      if isinstance(current_target, PythonRequirementLibrary):
        reqs = current_target.payload.get_field_value('requirements', set())
        """:type : set[pants.backend.python.python_requirement.PythonRequirement]"""
        info['requirements'] = [req.key for req in reqs]

      if isinstance(current_target, PythonTarget):
        interpreter_for_target = self._interpreter_cache.select_interpreter_for_targets(
          [current_target])
        if interpreter_for_target is None:
          raise TaskError('Unable to find suitable interpreter for {}'
                          .format(current_target.address))
        python_interpreter_targets_mapping[interpreter_for_target].append(current_target)
        info['python_interpreter'] = str(interpreter_for_target.identity)

      def iter_transitive_jars(jar_lib):
        """
        :type jar_lib: :class:`pants.backend.jvm.targets.jar_library.JarLibrary`
        :rtype: :class:`collections.Iterator` of
                :class:`pants.java.jar.M2Coordinate`
        """
        if classpath_products:
          jar_products = classpath_products.get_artifact_classpath_entries_for_targets((jar_lib,))
          for _, jar_entry in jar_products:
            coordinate = jar_entry.coordinate
            # We drop classifier and type_ since those fields are represented in the global
            # libraries dict and here we just want the key into that dict (see `_jar_id`).
            yield M2Coordinate(org=coordinate.org, name=coordinate.name, rev=coordinate.rev)

      target_libraries = OrderedSet()
      if isinstance(current_target, JarLibrary):
        target_libraries = OrderedSet(iter_transitive_jars(current_target))
      for dep in current_target.dependencies:
        info['targets'].append(dep.address.spec)
        if isinstance(dep, JarLibrary):
          for jar in dep.jar_dependencies:
            target_libraries.add(M2Coordinate(jar.org, jar.name, jar.rev))
          # Add all the jars pulled in by this jar_library
          target_libraries.update(iter_transitive_jars(dep))
        if isinstance(dep, Resources):
          resource_target_map[dep] = current_target

      if isinstance(current_target, ScalaLibrary):
        for dep in current_target.java_sources:
          info['targets'].append(dep.address.spec)
          process_target(dep)

      if isinstance(current_target, JvmTarget):
        info['excludes'] = [self._exclude_id(exclude) for exclude in current_target.excludes]
        info['platform'] = current_target.platform.name
        if hasattr(current_target, 'test_platform'):
          info['test_platform'] = current_target.test_platform.name

      info['roots'] = map(lambda (source_root, package_prefix): {
        'source_root': source_root,
        'package_prefix': package_prefix
      }, self._source_roots_for_target(current_target))

      if classpath_products:
        info['libraries'] = [self._jar_id(lib) for lib in target_libraries]
      targets_map[current_target.address.spec] = info

    for target in targets:
      process_target(target)

    jvm_platforms_map = {
      'default_platform' : JvmPlatform.global_instance().default_platform.name,
      'platforms': {
        str(platform_name): {
          'target_level' : str(platform.target_level),
          'source_level' : str(platform.source_level),
          'args' : platform.args,
        } for platform_name, platform in JvmPlatform.global_instance().platforms_by_name.items() },
    }

    graph_info = {
      'version': self.DEFAULT_EXPORT_VERSION,
      'targets': targets_map,
      'jvm_platforms': jvm_platforms_map,
      # `jvm_distributions` are static distribution settings from config,
      # `preferred_jvm_distributions` are distributions that pants actually uses for the
      # given platform setting.
      'preferred_jvm_distributions': {}
    }

    for platform_name, platform in JvmPlatform.global_instance().platforms_by_name.items():
      preferred_distributions = {}
      for strict, strict_key in [(True, 'strict'), (False, 'non_strict')]:
        try:
          dist = JvmPlatform.preferred_jvm_distribution([platform], strict=strict)
          preferred_distributions[strict_key] = dist.home
        except DistributionLocator.Error:
          pass

      if preferred_distributions:
        graph_info['preferred_jvm_distributions'][platform_name] = preferred_distributions

    if classpath_products:
      graph_info['libraries'] = self._resolve_jars_info(targets, classpath_products)

    if python_interpreter_targets_mapping:
      # NB: We've selected a python interpreter compatible with each python target individually into
      # the `python_interpreter_targets_mapping`. These python targets may not be compatible, ie: we
      # could have a python target requiring 'CPython>=2.7<3' (ie: CPython-2.7.x) and another
      # requiring 'CPython>=3.6'. To pick a default interpreter then from among these two choices
      # is arbitrary and not to be relied on to work as a default interpreter if ever needed by the
      # export consumer.
      #
      # TODO(John Sirois): consider either eliminating the 'default_interpreter' field and pressing
      # export consumers to make their own choice of a default (if needed) or else use
      # `select.select_interpreter_for_targets` and fail fast if there is no interpreter compatible
      # across all the python targets in-play.
      #
      # For now, make our arbitrary historical choice of a default interpreter explicit and use the
      # lowest version.
      default_interpreter = min(python_interpreter_targets_mapping.keys())

      interpreters_info = {}
      for interpreter, targets in six.iteritems(python_interpreter_targets_mapping):
        req_libs = filter(has_python_requirements, Target.closure_for_targets(targets))
        chroot = self.resolve_requirements(interpreter, req_libs)
        interpreters_info[str(interpreter.identity)] = {
          'binary': interpreter.binary,
          'chroot': chroot.path()
        }

      graph_info['python_setup'] = {
        'default_interpreter': str(default_interpreter.identity),
        'interpreters': interpreters_info
      }

    return graph_info

  def _resolve_jars_info(self, targets, classpath_products):
    """Consults ivy_jar_products to export the external libraries.

    :return: mapping of jar_id -> { 'default'     : <jar_file>,
                                    'sources'     : <jar_file>,
                                    'javadoc'     : <jar_file>,
                                    <other_confs> : <jar_file>,
                                  }
    """
    mapping = defaultdict(dict)
    jar_products = classpath_products.get_artifact_classpath_entries_for_targets(
      targets, respect_excludes=False)
    for conf, jar_entry in jar_products:
      conf = jar_entry.coordinate.classifier or 'default'
      mapping[self._jar_id(jar_entry.coordinate)][conf] = jar_entry.cache_path
    return mapping

  @memoized_property
  def target_aliases_map(self):
    registered_aliases = self.context.build_file_parser.registered_aliases()
    mapping = {}
    for alias, target_types in registered_aliases.target_types_by_alias.items():
      # If a target class is registered under multiple aliases returns the last one.
      for target_type in target_types:
        mapping[target_type] = alias
    return mapping

  def _get_pants_target_alias(self, pants_target_type):
    """Returns the pants target alias for the given target"""
    if pants_target_type in self.target_aliases_map:
      return self.target_aliases_map.get(pants_target_type)
    else:
      return "{}.{}".format(pants_target_type.__module__, pants_target_type.__name__)

  @staticmethod
  def _source_roots_for_target(target):
    """
    :type target:pants.build_graph.target.Target
    """
    def root_package_prefix(source_file):
      source = os.path.dirname(source_file)
      return os.path.join(get_buildroot(), target.target_base, source), source.replace(os.sep, '.')
    return set(map(root_package_prefix, target.sources_relative_to_source_root()))


class Export(ExportTask, ConsoleTask):
  """Export project information in JSON format.

  Intended for exporting project information for IDE, such as the IntelliJ Pants plugin.
  """

  def __init__(self, *args, **kwargs):
    super(ExportTask, self).__init__(*args, **kwargs)

  def console_output(self, targets, classpath_products=None):
    graph_info = self.generate_targets_map(targets, classpath_products=classpath_products)
    if self.get_options().formatted:
      return json.dumps(graph_info, indent=4, separators=(',', ': ')).splitlines()
    else:
      return [json.dumps(graph_info)]
