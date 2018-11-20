# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import itertools
import logging
import os
import unittest
from builtins import object, open
from collections import defaultdict
from contextlib import contextmanager
from tempfile import mkdtemp
from textwrap import dedent

from future.utils import PY2

from pants.base.build_file import BuildFile
from pants.base.build_root import BuildRoot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.deprecated import deprecated_module
from pants.base.exceptions import TaskError
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.build_graph.address import Address
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_address_mapper import BuildFileAddressMapper
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.build_file_parser import BuildFileParser
from pants.build_graph.mutable_build_graph import MutableBuildGraph
from pants.build_graph.target import Target
from pants.init.util import clean_global_runtime_state
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.scope import GLOBAL_SCOPE
from pants.source.source_root import SourceRootConfig
from pants.subsystem.subsystem import Subsystem
from pants.task.goal_options_mixin import GoalOptionsMixin
from pants.util.dirutil import safe_mkdir, safe_open, safe_rmtree
from pants_test.base.context_utils import create_context_from_options
from pants_test.option.util.fakes import create_options_for_optionables


# Fix this during a dev release
deprecated_module('1.13.0.dev1', 'Use pants_test.test_base instead')


class TestGenerator(object):
  """A mixin that facilitates test generation at runtime."""

  @classmethod
  def generate_tests(cls):
    """Generate tests for a given class.

    This should be called against the composing class in it's defining module, e.g.

      class ThingTest(TestGenerator):
        ...

      ThingTest.generate_tests()

    """
    raise NotImplementedError()

  @classmethod
  def add_test(cls, method_name, method):
    """A classmethod that adds dynamic test methods to a given class.

    :param string method_name: The name of the test method (e.g. `test_thing_x`).
    :param callable method: A callable representing the method. This should take a 'self' argument
                            as its first parameter for instance method binding.
    """
    assert not hasattr(cls, method_name), (
      'a test with name `{}` already exists on `{}`!'.format(method_name, cls.__name__)
    )
    assert method_name.startswith('test_'), '{} is not a valid test name!'.format(method_name)
    setattr(cls, method_name, method)


class BaseTest(unittest.TestCase):
  """A baseclass useful for tests requiring a temporary buildroot.

  :API: public

  """

  def build_path(self, relpath):
    """Returns the canonical BUILD file path for the given relative build path.

    :API: public
    """
    if os.path.basename(relpath).startswith('BUILD'):
      return relpath
    else:
      return os.path.join(relpath, 'BUILD')

  def create_dir(self, relpath):
    """Creates a directory under the buildroot.

    :API: public

    relpath: The relative path to the directory from the build root.
    """
    path = os.path.join(self.build_root, relpath)
    safe_mkdir(path)
    return path

  def create_workdir_dir(self, relpath):
    """Creates a directory under the work directory.

    :API: public

    relpath: The relative path to the directory from the work directory.
    """
    path = os.path.join(self.pants_workdir, relpath)
    safe_mkdir(path)
    return path

  def create_file(self, relpath, contents='', mode='w'):
    """Writes to a file under the buildroot.

    :API: public

    relpath:  The relative path to the file from the build root.
    contents: A string containing the contents of the file - '' by default..
    mode:     The mode to write to the file in - over-write by default.
    """
    path = os.path.join(self.build_root, relpath)
    with safe_open(path, mode=mode) as fp:
      fp.write(contents)
    return path

  def create_workdir_file(self, relpath, contents='', mode='w'):
    """Writes to a file under the work directory.

    :API: public

    relpath:  The relative path to the file from the work directory.
    contents: A string containing the contents of the file - '' by default..
    mode:     The mode to write to the file in - over-write by default.
    """
    path = os.path.join(self.pants_workdir, relpath)
    with safe_open(path, mode=mode) as fp:
      fp.write(contents)
    return path

  def add_to_build_file(self, relpath, target):
    """Adds the given target specification to the BUILD file at relpath.

    :API: public

    relpath: The relative path to the BUILD file from the build root.
    target:  A string containing the target definition as it would appear in a BUILD file.
    """
    self.create_file(self.build_path(relpath), target, mode='a')
    return BuildFile(self.address_mapper._project_tree, relpath=self.build_path(relpath))

  def make_target(self,
                  spec='',
                  target_type=Target,
                  dependencies=None,
                  derived_from=None,
                  synthetic=False,
                  **kwargs):
    """Creates a target and injects it into the test's build graph.

    :API: public

    :param string spec: The target address spec that locates this target.
    :param type target_type: The concrete target subclass to create this new target from.
    :param list dependencies: A list of target instances this new target depends on.
    :param derived_from: The target this new target was derived from.
    :type derived_from: :class:`pants.build_graph.target.Target`
    """
    address = Address.parse(spec)
    target = target_type(name=address.target_name,
                         address=address,
                         build_graph=self.build_graph,
                         **kwargs)
    dependencies = dependencies or []

    self.build_graph.apply_injectables([target])
    self.build_graph.inject_target(target,
                                   dependencies=[dep.address for dep in dependencies],
                                   derived_from=derived_from,
                                   synthetic=synthetic)

    # TODO(John Sirois): This re-creates a little bit too much work done by the BuildGraph.
    # Fixup the BuildGraph to deal with non BuildFileAddresses better and just leverage it.
    traversables = [target.compute_dependency_specs(payload=target.payload)]

    for dependency_spec in itertools.chain(*traversables):
      dependency_address = Address.parse(dependency_spec, relative_to=address.spec_path)
      dependency_target = self.build_graph.get_target(dependency_address)
      if not dependency_target:
        raise ValueError('Tests must make targets for dependency specs ahead of them '
                         'being traversed, {} tried to traverse {} which does not exist.'
                         .format(target, dependency_address))
      if dependency_target not in target.dependencies:
        self.build_graph.inject_dependency(dependent=target.address,
                                           dependency=dependency_address)
        target.mark_transitive_invalidation_hash_dirty()

    return target

  @property
  def alias_groups(self):
    """
    :API: public
    """
    return BuildFileAliases(targets={'target': Target})

  @property
  def build_ignore_patterns(self):
    """
    :API: public
    """
    return None

  def setUp(self):
    """
    :API: public
    """
    super(BaseTest, self).setUp()
    # Avoid resetting the Runtracker here, as that is specific to fork'd process cleanup.
    clean_global_runtime_state(reset_subsystem=True)

    self.real_build_root = BuildRoot().path

    self.build_root = os.path.realpath(mkdtemp(suffix='_BUILD_ROOT'))
    self.subprocess_dir = os.path.join(self.build_root, '.pids')
    self.addCleanup(safe_rmtree, self.build_root)

    self.pants_workdir = os.path.join(self.build_root, '.pants.d')
    safe_mkdir(self.pants_workdir)

    self.options = defaultdict(dict)  # scope -> key-value mapping.
    self.options[GLOBAL_SCOPE] = {
      'pants_workdir': self.pants_workdir,
      'pants_supportdir': os.path.join(self.build_root, 'build-support'),
      'pants_distdir': os.path.join(self.build_root, 'dist'),
      'pants_configdir': os.path.join(self.build_root, 'config'),
      'pants_subprocessdir': self.subprocess_dir,
      'cache_key_gen_version': '0-test',
    }
    self.options['cache'] = {
      'read_from': [],
      'write_to': [],
    }

    BuildRoot().path = self.build_root
    self.addCleanup(BuildRoot().reset)

    self._build_configuration = BuildConfiguration()
    self._build_configuration.register_aliases(self.alias_groups)
    self.build_file_parser = BuildFileParser(self._build_configuration, self.build_root)
    self.project_tree = FileSystemProjectTree(self.build_root)
    self.reset_build_graph()

  def buildroot_files(self, relpath=None):
    """Returns the set of all files under the test build root.

    :API: public

    :param string relpath: If supplied, only collect files from this subtree.
    :returns: All file paths found.
    :rtype: set
    """
    def scan():
      for root, dirs, files in os.walk(os.path.join(self.build_root, relpath or '')):
        for f in files:
          yield os.path.relpath(os.path.join(root, f), self.build_root)
    return set(scan())

  def reset_build_graph(self):
    """Start over with a fresh build graph with no targets in it."""
    self.address_mapper = BuildFileAddressMapper(self.build_file_parser, self.project_tree,
                                                 build_ignore_patterns=self.build_ignore_patterns)
    self.build_graph = MutableBuildGraph(address_mapper=self.address_mapper)

  def set_options_for_scope(self, scope, **kwargs):
    self.options[scope].update(kwargs)

  def context(self, for_task_types=None, for_subsystems=None, options=None,
              target_roots=None, console_outstream=None, workspace=None,
              scheduler=None, **kwargs):
    """
    :API: public

    :param dict **kwargs: keyword arguments passed in to `create_options_for_optionables`.
    """
    # Many tests use source root functionality via the SourceRootConfig.global_instance().
    # (typically accessed via Target.target_base), so we always set it up, for convenience.
    for_subsystems = set(for_subsystems or ())
    for subsystem in for_subsystems:
      if subsystem.options_scope is None:
        raise TaskError('You must set a scope on your subsystem type before using it in tests.')

    optionables = {SourceRootConfig} | self._build_configuration.subsystems() | for_subsystems

    for_task_types = for_task_types or ()
    for task_type in for_task_types:
      scope = task_type.options_scope
      if scope is None:
        raise TaskError('You must set a scope on your task type before using it in tests.')
      optionables.add(task_type)
      # If task is expected to inherit goal-level options, register those directly on the task,
      # by subclassing the goal options registrar and settings its scope to the task scope.
      if issubclass(task_type, GoalOptionsMixin):
        subclass_name = 'test_{}_{}_{}'.format(
          task_type.__name__, task_type.goal_options_registrar_cls.options_scope,
          task_type.options_scope)
        if PY2:
          subclass_name = subclass_name.encode('utf-8')
        optionables.add(type(subclass_name, (task_type.goal_options_registrar_cls, ),
                             {'options_scope': task_type.options_scope}))

    # Now expand to all deps.
    all_optionables = set()
    for optionable in optionables:
      all_optionables.update(si.optionable_cls for si in optionable.known_scope_infos())

    # Now default the option values and override with any caller-specified values.
    # TODO(benjy): Get rid of the options arg, and require tests to call set_options.
    options = options.copy() if options else {}
    for s, opts in self.options.items():
      scoped_opts = options.setdefault(s, {})
      scoped_opts.update(opts)

    fake_options = create_options_for_optionables(
      all_optionables, options=options, **kwargs)

    Subsystem.reset(reset_options=True)
    Subsystem.set_options(fake_options)

    context = create_context_from_options(fake_options,
                                          target_roots=target_roots,
                                          build_graph=self.build_graph,
                                          build_file_parser=self.build_file_parser,
                                          address_mapper=self.address_mapper,
                                          console_outstream=console_outstream,
                                          workspace=workspace,
                                          scheduler=scheduler)
    return context

  def tearDown(self):
    """
    :API: public
    """
    super(BaseTest, self).tearDown()
    BuildFile.clear_cache()
    Subsystem.reset()

  def target(self, spec):
    """Resolves the given target address to a Target object.

    :API: public

    address: The BUILD target address to resolve.

    Returns the corresponding Target or else None if the address does not point to a defined Target.
    """
    address = Address.parse(spec)
    self.build_graph.inject_address_closure(address)
    return self.build_graph.get_target(address)

  def targets(self, spec):
    """Resolves a target spec to one or more Target objects.

    :API: public

    spec: Either BUILD target address or else a target glob using the siblings ':' or
          descendants '::' suffixes.

    Returns the set of all Targets found.
    """

    spec = CmdLineSpecParser(self.build_root).parse_spec(spec)
    addresses = list(self.address_mapper.scan_specs([spec]))
    for address in addresses:
      self.build_graph.inject_address_closure(address)
    targets = [self.build_graph.get_target(address) for address in addresses]
    return targets

  def create_files(self, path, files):
    """Writes to a file under the buildroot with contents same as file name.

    :API: public

     path:  The relative path to the file from the build root.
     files: List of file names.
    """
    for f in files:
      self.create_file(os.path.join(path, f), contents=f)

  def create_library(self, path, target_type, name, sources=None, **kwargs):
    """Creates a library target of given type at the BUILD file at path with sources

    :API: public

     path: The relative path to the BUILD file from the build root.
     target_type: valid pants target type.
     name: Name of the library target.
     sources: List of source file at the path relative to path.
     **kwargs: Optional attributes that can be set for any library target.
       Currently it includes support for resources, java_sources, provides
       and dependencies.
    """
    if sources:
      self.create_files(path, sources)
    self.add_to_build_file(path, dedent('''
          %(target_type)s(name='%(name)s',
            %(sources)s
            %(java_sources)s
            %(provides)s
            %(dependencies)s
          )
        ''' % dict(target_type=target_type,
                   name=name,
                   sources=('sources=%s,' % repr(sources)
                              if sources else ''),
                   java_sources=('java_sources=[%s],'
                                 % ','.join('"%s"' % str_target for str_target in kwargs.get('java_sources'))
                                 if 'java_sources' in kwargs else ''),
                   provides=('provides=%s,' % kwargs.get('provides')
                              if 'provides' in kwargs else ''),
                   dependencies=('dependencies=%s,' % kwargs.get('dependencies')
                              if 'dependencies' in kwargs else ''),
                   )))
    return self.target('%s:%s' % (path, name))

  def create_resources(self, path, name, *sources):
    """
    :API: public
    """
    return self.create_library(path, 'resources', name, sources)

  def assertUnorderedPrefixEqual(self, expected, actual_iter):
    """Consumes len(expected) items from the given iter, and asserts that they match, unordered.

    :API: public
    """
    actual = list(itertools.islice(actual_iter, len(expected)))
    self.assertEqual(sorted(expected), sorted(actual))

  def assertPrefixEqual(self, expected, actual_iter):
    """Consumes len(expected) items from the given iter, and asserts that they match, in order.

    :API: public
    """
    self.assertEqual(expected, list(itertools.islice(actual_iter, len(expected))))

  def assertInFile(self, string, file_path):
    """Verifies that a string appears in a file

    :API: public
    """

    with open(file_path, 'r') as f:
      content = f.read()
      self.assertIn(string, content, '"{}" is not in the file {}:\n{}'.format(string, f.name, content))

  def get_bootstrap_options(self, cli_options=()):
    """Retrieves bootstrap options.

    :param cli_options: An iterable of CLI flags to pass as arguments to `OptionsBootstrapper`.
    """
    # Can't parse any options without a pants.ini.
    self.create_file('pants.ini')
    return OptionsBootstrapper(args=cli_options).get_bootstrap_options().for_global_scope()

  class LoggingRecorder(object):
    """Simple logging handler to record warnings."""

    def __init__(self):
      self._records = []
      self.level = logging.DEBUG

    def handle(self, record):
      self._records.append(record)

    def _messages_for_level(self, levelname):
      return ['{}: {}'.format(record.name, record.getMessage())
              for record in self._records if record.levelname == levelname]

    def infos(self):
      return self._messages_for_level('INFO')

    def warnings(self):
      return self._messages_for_level('WARNING')

  @contextmanager
  def captured_logging(self, level=None):
    root_logger = logging.getLogger()

    old_level = root_logger.level
    root_logger.setLevel(level or logging.NOTSET)

    handler = self.LoggingRecorder()
    root_logger.addHandler(handler)
    try:
      yield handler
    finally:
      root_logger.setLevel(old_level)
      root_logger.removeHandler(handler)
