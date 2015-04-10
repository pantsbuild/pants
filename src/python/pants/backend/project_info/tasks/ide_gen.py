# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import shutil
from collections import defaultdict

from twitter.common.collections.orderedset import OrderedSet

from pants import binary_util
from pants.backend.core.tasks.task import Task
from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot
from pants.util.dirutil import safe_mkdir, safe_walk


logger = logging.getLogger(__name__)


# We use custom checks for scala and java targets here for 2 reasons:
# 1.) jvm_binary could have either a scala or java source file attached so we can't do a pure
#     target type test
# 2.) the target may be under development in which case it may not have sources yet - its pretty
#     common to write a BUILD and ./pants idea the target inside to start development at which
#     point there are no source files yet - and the developer intents to add them using the ide.

def is_scala(target):
  return target.has_sources('.scala') or target.is_scala


def is_java(target):
  return target.has_sources('.java') or target.is_java


class IdeGen(JvmToolTaskMixin, Task):

  RESOURCES = "java-resource"
  TEST_RESOURCES = "java-test-resource"

  @classmethod
  def register_options(cls, register):
    super(IdeGen, cls).register_options(register)
    register('--project-name', default='project',
             help='Specifies the name to use for the generated project.')
    register('--project-dir',
             help='Specifies the directory to output the generated project files to.')
    register('--project-cwd',
             help='Specifies the directory the generated project should use as the cwd for '
                  'processes it launches.  Note that specifying this trumps --{0}-project-dir '
                  'and not all project related files will be stored there.'
                  .format(cls.options_scope))
    register('--intransitive', action='store_true', default=False,
             help='Limits the sources included in the generated project to just '
                  'those owned by the targets specified on the command line.')
    register('--python', action='store_true', default=False,
             help='Adds python support to the generated project configuration.')
    register('--java', action='store_true', default=True,
             help='Includes java sources in the project; otherwise compiles them and adds them '
                  'to the project classpath.')
    register('--java-language-level', type=int, default=7,
             help='Sets the java language and jdk used to compile the project\'s java sources.')
    register('--java-jdk-name', default=None,
             help='Sets the jdk used to compile the project\'s java sources. If unset the default '
                  'jdk name for the --java-language-level is used')
    register('--scala', action='store_true', default=True,
             help='Includes scala sources in the project; otherwise compiles them and adds them '
                  'to the project classpath.')
    register('--use-source-root', action='store_true', default=False,
             help='Use source_root() settings to collapse sourcepaths in project and determine '
                  'which paths are used for tests.  This is usually what you want if your repo '
                  ' uses a maven style directory layout.')
    register('--infer-test-from-siblings', action='store_true',
             help='When determining if a path should be added to the IDE, check to see if any of '
                  'its sibling source_root() entries define test targets.  This is usually what '
                  'you want so that resource directories under test source roots are picked up as '
                  'test paths.')
    register('--debug_port', type=int, default=5005,
             help='Port to use for launching tasks under the debugger.')
    register('--source-jars', action='store_true', default=True,
             help='Pull source jars from external dependencies into the project.')
    register('--javadoc-jars', action='store_true', default=True,
             help='Pull javadoc jars from external dependencies into the project')

    # Options intended to be configured primarily in pants.ini
    register('--python_source_paths', action='append', advanced=True,
             help='Always add these paths to the IDE as Python sources.')
    register('--python_test_paths', action='append', advanced=True,
             help='Always add these paths to the IDE as Python test sources.')
    register('--python_lib_paths', action='append', advanced=True,
             help='Always add these paths to the IDE for Python libraries.')
    register('--extra-jvm-source-paths', action='append', advanced=True,
             help='Always add these paths to the IDE for Java sources.')
    register('--extra-jvm-test-paths', action='append', advanced=True,
             help='Always add these paths to the IDE for Java test sources.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(IdeGen, cls).prepare(options, round_manager)
    if options.python:
      round_manager.require('python')
    if options.java:
      round_manager.require('java')
    if options.scala:
      round_manager.require('scala')
    # TODO(Garrett Malmquist): Clean this up by using IvyUtils in the caller, passing it confs as
    # the parameter. See John's comments on RB 716.
    round_manager.require_data('ivy_jar_products')
    round_manager.require('jar_dependencies')
    round_manager.require('jar_map_default')
    if options.source_jars:
      round_manager.require('jar_map_sources')
    if options.javadoc_jars:
      round_manager.require('jar_map_javadoc')

  class Error(TaskError):
    """IdeGen Error."""

  class TargetUtil(object):
    def __init__(self, context):
      self.context = context

    @property
    def build_graph(self):
      return self.context.build_graph

    def get_all_addresses(self, buildfile):
      return set(self.context.address_mapper.addresses_in_spec_path(buildfile.spec_path))

    def get(self, address):
      self.context.build_graph.inject_address_closure(address)
      return self.context.build_graph.get_target(address)

  def __init__(self, *args, **kwargs):
    super(IdeGen, self).__init__(*args, **kwargs)

    self.project_name = self.get_options().project_name
    self.python = self.get_options().python
    self.skip_java = not self.get_options().java
    self.skip_scala = not self.get_options().scala
    self.use_source_root = self.get_options().use_source_root

    self.java_language_level = self.get_options().java_language_level
    if self.get_options().java_jdk_name:
      self.java_jdk = self.get_options().java_jdk_name
    else:
      self.java_jdk = '1.{}'.format(self.java_language_level)

    # Always tack on the project name to the work dir so each project gets its own linked jars,
    # etc. See https://github.com/pantsbuild/pants/issues/564
    if self.get_options().project_dir:
      self.gen_project_workdir = os.path.abspath(
        os.path.join(self.get_options().project_dir, self.project_name))
    else:
      self.gen_project_workdir = os.path.abspath(
        os.path.join(self.workdir, self.__class__.__name__, self.project_name))

    self.cwd = (
      os.path.abspath(self.get_options().project_cwd) if
      self.get_options().project_cwd else self.gen_project_workdir
    )

    self.intransitive = self.get_options().intransitive
    self.debug_port = self.get_options().debug_port

  def _prepare_project(self):
    targets, self._project = self.configure_project(
        self.context.targets(),
        self.debug_port)

    self.configure_compile_context(targets)

  def configure_project(self, targets, debug_port):
    jvm_targets = [t for t in targets if t.has_label('jvm') or t.has_label('java')]
    if self.intransitive:
      jvm_targets = set(self.context.target_roots).intersection(jvm_targets)
    project = Project(self.project_name,
                      self.python,
                      self.skip_java,
                      self.skip_scala,
                      self.use_source_root,
                      get_buildroot(),
                      debug_port,
                      jvm_targets,
                      not self.intransitive,
                      self.TargetUtil(self.context),
                      self.context.options.for_global_scope().spec_excludes)

    if self.python:
      python_source_paths = self.get_options().python_source_paths
      python_test_paths = self.get_options().python_test_paths
      python_lib_paths = self.get_options().python_lib_paths
      project.configure_python(python_source_paths, python_test_paths, python_lib_paths)

    extra_source_paths = self.get_options().extra_jvm_source_paths
    extra_test_paths = self.get_options().extra_jvm_test_paths
    all_targets = project.configure_jvm(extra_source_paths, extra_test_paths)
    return all_targets, project

  def configure_compile_context(self, targets):
    """
      Trims the context's target set to just those targets needed as jars on the IDE classpath.
      All other targets only contribute their external jar dependencies and excludes to the
      classpath definition.
    """
    def is_cp(target):
      return (
        target.is_codegen or
        # Some IDEs need annotation processors pre-compiled, others are smart enough to detect and
        # proceed in 2 compile rounds
        isinstance(target, AnnotationProcessor) or
        (self.skip_java and is_java(target)) or
        (self.skip_scala and is_scala(target)) or
        (self.intransitive and target not in self.context.target_roots)
      )

    jars = OrderedSet()
    excludes = OrderedSet()
    compiles = OrderedSet()
    def prune(target):
      if target.is_jvm:
        if target.excludes:
          excludes.update(target.excludes)
        jars.update(jar for jar in target.jar_dependencies if jar.rev)
        if is_cp(target):
          target.walk(compiles.add)

    for target in targets:
      target.walk(prune)

    # TODO(John Sirois): Restructure to use alternate_target_roots Task lifecycle method
    self.context._replace_targets(compiles)

    self.jar_dependencies = jars

    self.context.log.debug('pruned to cp:\n\t{}'.format(
      '\n\t'.join(str(t) for t in self.context.targets())
    ))

  def map_internal_jars(self, targets):
    internal_jar_dir = os.path.join(self.gen_project_workdir, 'internal-libs')
    safe_mkdir(internal_jar_dir, clean=True)

    internal_source_jar_dir = os.path.join(self.gen_project_workdir, 'internal-libsources')
    safe_mkdir(internal_source_jar_dir, clean=True)

    internal_jars = self.context.products.get('jars')
    internal_source_jars = self.context.products.get('source_jars')
    for target in targets:
      mappings = internal_jars.get(target)
      if mappings:
        for base, jars in mappings.items():
          if len(jars) != 1:
            raise IdeGen.Error('Unexpected mapping, multiple jars for {}: {}'.format(target, jars))

          jar = jars[0]
          cp_jar = os.path.join(internal_jar_dir, jar)
          shutil.copy(os.path.join(base, jar), cp_jar)

          cp_source_jar = None
          mappings = internal_source_jars.get(target)
          if mappings:
            for base, jars in mappings.items():
              if len(jars) != 1:
                raise IdeGen.Error(
                  'Unexpected mapping, multiple source jars for {}: {}'.format(target, jars)
                )
              jar = jars[0]
              cp_source_jar = os.path.join(internal_source_jar_dir, jar)
              shutil.copy(os.path.join(base, jar), cp_source_jar)

          self._project.internal_jars.add(ClasspathEntry(cp_jar, source_jar=cp_source_jar))

  @staticmethod
  def get_jar_infos(ivy_products, confs=None):
    """Returns a list of dicts containing the paths of various jar file resources.

    Keys include 'default' (normal jar path), 'sources' (path to source jar), and 'javadoc'
    (path to doc jar). None of them are guaranteed to be present, but 'sources' and 'javadoc'
    will never be present if 'default' isn't.

    :param ivy_products: ivy_jar_products data from a context
    :param confs: List of key types to return (eg ['default', 'sources']). Just returns 'default' if
      left unspecified.
    :returns {dict}
    """
    classpath_maps = defaultdict(dict)
    if ivy_products:
      for conf, info_group in ivy_products.items():
        if conf not in confs:
          continue # We don't care about it.
        for info in info_group:
          for module in info.modules_by_ref.values():
            for artifact in module.artifacts:
              classpath_maps[module.ref][conf] = artifact.path
    return classpath_maps

  def map_external_jars(self):
    external_jar_dir = os.path.join(self.gen_project_workdir, 'external-libs')
    safe_mkdir(external_jar_dir, clean=True)

    external_source_jar_dir = os.path.join(self.gen_project_workdir, 'external-libsources')
    safe_mkdir(external_source_jar_dir, clean=True)

    external_javadoc_jar_dir = os.path.join(self.gen_project_workdir, 'external-libjavadoc')
    safe_mkdir(external_javadoc_jar_dir, clean=True)

    confs = ['default', 'sources', 'javadoc']
    jar_paths = self.get_jar_infos(self.context.products.get_data('ivy_jar_products'), confs)
    for entry in jar_paths.values():
      jar = entry.get('default')
      if jar:
        cp_jar = os.path.join(external_jar_dir, os.path.basename(jar))
        shutil.copy(jar, cp_jar)

        cp_source_jar = None
        source_jar = entry.get('sources')
        if source_jar:
          cp_source_jar = os.path.join(external_source_jar_dir, os.path.basename(source_jar))
          shutil.copy(source_jar, cp_source_jar)

        cp_javadoc_jar = None
        javadoc_jar = entry.get('javadoc')
        if javadoc_jar:
          cp_javadoc_jar = os.path.join(external_javadoc_jar_dir, os.path.basename(javadoc_jar))
          shutil.copy(javadoc_jar, cp_javadoc_jar)

        self._project.external_jars.add(ClasspathEntry(cp_jar,
                                                       source_jar=cp_source_jar,
                                                       javadoc_jar=cp_javadoc_jar))

  def execute(self):
    """Stages IDE project artifacts to a project directory and generates IDE configuration files."""
    self._prepare_project()

    if self.context.options.is_known_scope('compile.checkstyle'):
      checkstyle_classpath = self.tool_classpath('checkstyle', scope='compile.checkstyle')
    else:  # Checkstyle not enabled.
      checkstyle_classpath = []

    if self.skip_scala:
      scalac_classpath = []
    else:
      scalac_classpath = self.tool_classpath('scalac', scope='compile.scala')

    self._project.set_tool_classpaths(checkstyle_classpath, scalac_classpath)
    targets = self.context.targets()
    self.map_internal_jars(targets)
    self.map_external_jars()

    idefile = self.generate_project(self._project)
    if idefile:
      binary_util.ui_open(idefile)

  def generate_project(self, project):
    raise NotImplementedError('Subclasses must generate a project for an ide')


class ClasspathEntry(object):
  """Represents a classpath entry that may have sources available."""

  def __init__(self, jar, source_jar=None, javadoc_jar=None):
    self.jar = jar
    self.source_jar = source_jar
    self.javadoc_jar = javadoc_jar


class SourceSet(object):
  """Models a set of source files."""

  def __init__(self, root_dir, source_base, path, is_test, content_type=''):
    """
    :param string root_dir: full path to the root of the project containing this source set
    :param string source_base: the relative path from root_dir to the base of this source set
    :param string path: relative path from the source_base to the base of the sources in this set
    :param bool is_test: true iff the sources contained by this set implement test cases
    :param string content_type: Content type resources or test resources for scala/java project
    """

    self.root_dir = root_dir
    self.source_base = source_base
    self.path = path
    self.is_test = is_test
    self._excludes = []
    self.content_type = content_type

  @property
  def excludes(self):
    """Paths relative to self.path that are excluded from this source set."""
    return self._excludes

  @property
  def _key_tuple(self):
    """Creates a tuple from the attributes used as a key to uniquely identify a SourceSet"""
    return (self.root_dir, self.source_base, self.path)

  def __str__(self):
    return str(self._key_tuple)

  def __eq__(self, other):
    return self._key_tuple == other._key_tuple

  def __cmp__(self, other):
    return cmp(self._key_tuple, other._key_tuple)

  def __hash__(self):
    return hash(self._key_tuple)


class Project(object):
  """Models a generic IDE project that is comprised of a set of BUILD targets."""

  @staticmethod
  def extract_resource_extensions(resources):
    """Returns the set of unique extensions (including the .) from the given resource files."""

    if resources:
      for resource in resources:
        _, ext = os.path.splitext(resource)
        yield ext

  @staticmethod
  def _collapse_by_source_root(source_sets):
    """Collapse SourceSets with common source roots into one SourceSet instance.

    Use the registered source roots to collapse all source paths under a root.
    If any test type of target is allowed under the root, the path is determined to be
    a test path.  This method will give unpredictable results if source root entries overlap.

    :param list source_sets: SourceSets to analyze
    :returns: list of SourceSets collapsed to the source root paths.
    """

    roots_found = set()  # remember the roots we've already encountered
    collapsed_source_sets = []
    for source in source_sets:
      query = os.path.join(source.source_base, source.path)
      source_root = SourceRoot.find_by_path(query)
      if not source_root:
        collapsed_source_sets.append(source)
      elif not source_root in roots_found:
        roots_found.add(source_root)
        collapsed_source_sets.append(SourceSet(source.root_dir, source_root, "", source.is_test))
    return collapsed_source_sets

  def __init__(self, name, has_python, skip_java, skip_scala, use_source_root, root_dir,
               debug_port, targets, transitive, target_util, spec_excludes):
    """Creates a new, unconfigured, Project based at root_dir and comprised of the sources visible
    to the given targets."""

    self.target_util = target_util
    self.name = name
    self.root_dir = root_dir
    self.targets = OrderedSet(targets)
    self.transitive = transitive

    self.sources = set()
    self.py_sources = []
    self.py_libs = []
    self.resource_extensions = set()

    self.has_python = has_python
    self.skip_java = skip_java
    self.skip_scala = skip_scala
    self.use_source_root = use_source_root
    self.has_scala = False
    self.has_tests = False

    self.debug_port = debug_port

    self.internal_jars = OrderedSet()
    self.external_jars = OrderedSet()
    self.spec_excludes = spec_excludes

  def configure_python(self, source_roots, test_roots, lib_roots):
    self.py_sources.extend(SourceSet(get_buildroot(), root, None, False) for root in source_roots)
    self.py_sources.extend(SourceSet(get_buildroot(), root, None, True) for root in test_roots)
    for root in lib_roots:
      for path in os.listdir(os.path.join(get_buildroot(), root)):
        if os.path.isdir(os.path.join(get_buildroot(), root, path)) or path.endswith('.egg'):
          self.py_libs.append(SourceSet(get_buildroot(), root, path, False))

  def configure_jvm(self, extra_source_paths, extra_test_paths):
    """
      Configures this project's source sets returning the full set of targets the project is
      comprised of.  The full set can be larger than the initial set of targets when any of the
      initial targets only has partial ownership of its source set's directories.
    """

    # TODO(John Sirois): much waste lies here, revisit structuring for more readable and efficient
    # construction of source sets and excludes ... and add a test!

    analyzed = OrderedSet()
    targeted = set()

    def relative_sources(target):
      sources = target.payload.sources.relative_to_buildroot()
      return [os.path.relpath(source, target.target_base) for source in sources]

    def source_target(target):
      result = ((self.transitive or target in self.targets) and
              target.has_sources() and
              (not (self.skip_java and is_java(target)) and
               not (self.skip_scala and is_scala(target))))
      return result

    def configure_source_sets(relative_base, sources, is_test, content_type=''):
      absolute_base = os.path.join(self.root_dir, relative_base)
      paths = set([os.path.dirname(source) for source in sources])
      for path in paths:
        absolute_path = os.path.join(absolute_base, path)
        # Note, this can add duplicate source paths to self.sources().  We'll de-dup them later,
        # because we want to prefer test paths.
        targeted.add(absolute_path)
        source_set = SourceSet(self.root_dir, relative_base, path, is_test, content_type)
        if source_set in self.sources and content_type:
         # Note, same resource can be added twice.
         # 1. Once with the content_type attached with target.has_resources loop
         # 2. Second without content_type from command line target.
         # We do not want to skip resources in flow 2 as we can have resources on the command line
         # which are not attached to any target.
         self.sources.remove(source_set)
        self.sources.add(source_set)

    def find_source_basedirs(target):
      dirs = set()
      if source_target(target):
        absolute_base = os.path.join(self.root_dir, target.target_base)
        dirs.update([os.path.join(absolute_base, os.path.dirname(source))
                      for source in relative_sources(target)])
      return dirs

    def configure_target(target):
      if target not in analyzed:
        analyzed.add(target)
        self.has_scala = not self.skip_scala and (self.has_scala or is_scala(target))

        # Hack for java_sources and Eclipse/IntelliJ: add java_sources to project
        if isinstance(target, ScalaLibrary):
          for java_source in target.java_sources:
            configure_target(java_source)

        if target.has_resources:
          resources_by_basedir = defaultdict(set)
          for resources in target.resources:
            resources_by_basedir[resources.target_base].update(relative_sources(resources))
          for basedir, resources in resources_by_basedir.items():
            self.resource_extensions.update(Project.extract_resource_extensions(resources))
            if target.is_test:
              configure_source_sets(basedir, resources, is_test=target.is_test,
                                    content_type=IdeGen.TEST_RESOURCES)
            else:
              configure_source_sets(basedir, resources, is_test=target.is_test,
                                    content_type=IdeGen.RESOURCES)

        if target.has_sources():
          test = target.is_test
          self.has_tests = self.has_tests or test
          base = target.target_base
          configure_source_sets(base, relative_sources(target), is_test=test)

        # TODO(Garrett Malmquist): This is dead code, and should be redone/reintegrated.
        # Other BUILD files may specify sources in the same directory as this target. Those BUILD
        # files might be in parent directories (globs('a/b/*.java')) or even children directories if
        # this target globs children as well.  Gather all these candidate BUILD files to test for
        # sources they own that live in the directories this targets sources live in.
        target_dirset = find_source_basedirs(target)
        if target.address.is_synthetic:
          return [] # Siblings don't make sense for synthetic addresses.
        candidates = self.target_util.get_all_addresses(target.address.build_file)
        for ancestor in target.address.build_file.ancestors():
          candidates.update(self.target_util.get_all_addresses(ancestor))
        for sibling in target.address.build_file.siblings():
          candidates.update(self.target_util.get_all_addresses(sibling))
        for descendant in target.address.build_file.descendants(spec_excludes=self.spec_excludes):
          candidates.update(self.target_util.get_all_addresses(descendant))
        def is_sibling(target):
          return source_target(target) and target_dirset.intersection(find_source_basedirs(target))

        return filter(is_sibling, [self.target_util.get(a) for a in candidates if a != target.address])

    for target in self.targets:
      target.walk(configure_target, predicate=source_target)

    def full_path(source_set):
      return os.path.join(source_set.root_dir, source_set.source_base, source_set.path)

    def dedup_sources(source_set_list):
      """Sometimes two targets with the same path are added to the source set. One is a target where
       is_test evaluates to True and the other were it evaluates to False.  When this happens,
       make sure we prefer the SourceSet with is_test set to True.
      """
      deduped_sources = set(filter(lambda source_set: source_set.is_test, source_set_list))
      for source_set in source_set_list:
        if not source_set.is_test and source_set not in deduped_sources:
          deduped_sources.add(source_set)
      # re-sort the list, makes the generated project easier to read.
      return sorted(list(deduped_sources))

    # Check if there are any overlapping source_sets, and output an error message if so.
    # Overlapping source_sets cause serious problems with package name inference.
    overlap_error = ('SourceSets {current} and {previous} evaluate to the same full path.'
                     ' This can be caused by multiple BUILD targets claiming the same source,'
                     ' e.g., if a BUILD target in a parent directory contains an rglobs() while'
                     ' a BUILD target in a subdirectory of that uses a globs() which claims the'
                     ' same sources. This may cause package names to be inferred incorrectly (e.g.,'
                     ' you might see src.com.foo.bar.Main instead of com.foo.bar.Main).')
    source_full_paths = {}
    for source_set in sorted(self.sources, key=full_path):
      full = full_path(source_set)
      if full in source_full_paths:
        previous_set = source_full_paths[full]
        logger.debug(overlap_error.format(current=source_set, previous=previous_set))
      source_full_paths[full] = source_set

    # We need to figure out excludes, in doing so there are 2 cases we should not exclude:
    # 1.) targets depend on A only should lead to an exclude of B
    # A/BUILD
    # A/B/BUILD
    #
    # 2.) targets depend on A and C should not lead to an exclude of B (would wipe out C)
    # A/BUILD
    # A/B
    # A/B/C/BUILD
    #
    # 1 approach: build set of all paths and parent paths containing BUILDs our targets depend on -
    # these are unexcludable

    unexcludable_paths = set()
    for source_set in self.sources:
      parent = os.path.join(self.root_dir, source_set.source_base, source_set.path)
      while True:
        unexcludable_paths.add(parent)
        parent, _ = os.path.split(parent)
        # no need to add the repo root or above, all source paths and extra paths are children
        if parent == self.root_dir:
          break

    for source_set in self.sources:
      paths = set()
      source_base = os.path.join(self.root_dir, source_set.source_base)
      for root, dirs, _ in safe_walk(os.path.join(source_base, source_set.path)):
        if dirs:
          paths.update([os.path.join(root, directory) for directory in dirs])
      unused_children = paths - targeted
      if unused_children:
        for child in unused_children:
          if child not in unexcludable_paths:
            source_set.excludes.append(os.path.relpath(child, source_base))

    targets = OrderedSet()
    for target in self.targets:
      target.walk(lambda target: targets.add(target), source_target)
    targets.update(analyzed - targets)
    self.sources.update(SourceSet(get_buildroot(), p, None, False) for p in extra_source_paths)
    self.sources.update(SourceSet(get_buildroot(), p, None, True) for p in extra_test_paths)
    if self.use_source_root:
      self.sources = Project._collapse_by_source_root(self.sources)
    self.sources = dedup_sources(self.sources)

    return targets

  def set_tool_classpaths(self, checkstyle_classpath, scalac_classpath):
    self.checkstyle_classpath = checkstyle_classpath
    self.scala_compiler_classpath = scalac_classpath
