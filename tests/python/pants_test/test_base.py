# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
import os
import unittest
import warnings
from abc import ABC, ABCMeta, abstractmethod
from collections import defaultdict
from contextlib import contextmanager
from tempfile import mkdtemp
from textwrap import dedent

from pants.base.build_root import BuildRoot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.exceptions import TaskError
from pants.base.target_roots import TargetRoots
from pants.build_graph.address import Address
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target
from pants.engine.fs import PathGlobs, PathGlobsAndRoot
from pants.engine.legacy.graph import HydratedField
from pants.engine.legacy.structs import SourcesField
from pants.engine.rules import RootRule
from pants.init.engine_initializer import EngineInitializer
from pants.init.util import clean_global_runtime_state
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.source.source_root import SourceRootConfig
from pants.subsystem.subsystem import Subsystem
from pants.task.goal_options_mixin import GoalOptionsMixin
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import (recursive_dirname, relative_symlink, safe_file_dump, safe_mkdir,
                                safe_mkdtemp, safe_open, safe_rmtree)
from pants.util.memo import memoized_method
from pants.util.meta import classproperty
from pants_test.base.context_utils import create_context_from_options
from pants_test.engine.util import init_native
from pants_test.option.util.fakes import create_options_for_optionables
from pants_test.subsystem import subsystem_util


class AbstractTestGenerator(ABC):
  """A mixin that facilitates test generation at runtime."""

  @classmethod
  @abstractmethod
  def generate_tests(cls):
    """Generate tests for a given class.

    This should be called against the composing class in its defining module, e.g.

      class ThingTest(TestGenerator):
        ...

      ThingTest.generate_tests()

    """

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


class TestBase(unittest.TestCase, metaclass=ABCMeta):
  """A baseclass useful for tests requiring a temporary buildroot.

  :API: public
  """

  _scheduler = None
  _local_store_dir = None
  _build_graph = None
  _address_mapper = None

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
    self.invalidate_for(relpath)
    return path

  def create_workdir_dir(self, relpath):
    """Creates a directory under the work directory.

    :API: public

    relpath: The relative path to the directory from the work directory.
    """
    path = os.path.join(self.pants_workdir, relpath)
    safe_mkdir(path)
    self.invalidate_for(relpath)
    return path

  def invalidate_for(self, *relpaths):
    """Invalidates all files from the relpath, recursively up to the root.

    Many python operations implicitly create parent directories, so we assume that touching a
    file located below directories that do not currently exist will result in their creation.
    """
    if self._scheduler is None:
      return
    files = {f for relpath in relpaths for f in recursive_dirname(relpath)}
    return self._scheduler.invalidate_files(files)

  def create_link(self, relsrc, reldst):
    """Creates a symlink within the buildroot.

    :API: public

    relsrc: A relative path for the source of the link.
    reldst: A relative path for the destination of the link.
    """
    src = os.path.join(self.build_root, relsrc)
    dst = os.path.join(self.build_root, reldst)
    relative_symlink(src, dst)
    self.invalidate_for(reldst)

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
    self.invalidate_for(relpath)
    return path

  def create_files(self, path, files):
    """Writes to a file under the buildroot with contents same as file name.

    :API: public

     path:  The relative path to the file from the build root.
     files: List of file names.
    """
    for f in files:
      self.create_file(os.path.join(path, f), contents=f)

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

  def make_target(self,
                  spec='',
                  target_type=Target,
                  dependencies=None,
                  derived_from=None,
                  synthetic=False,
                  make_missing_sources=True,
                  **kwargs):
    """Creates a target and injects it into the test's build graph.

    :API: public

    :param string spec: The target address spec that locates this target.
    :param type target_type: The concrete target subclass to create this new target from.
    :param list dependencies: A list of target instances this new target depends on.
    :param derived_from: The target this new target was derived from.
    :type derived_from: :class:`pants.build_graph.target.Target`
    """
    self._init_target_subsystem()

    address = Address.parse(spec)

    if make_missing_sources and 'sources' in kwargs:
      for source in kwargs['sources']:
        if '*' not in source:
          self.create_file(os.path.join(address.spec_path, source), mode='a', contents='')
      kwargs['sources'] = self.sources_for(kwargs['sources'], address.spec_path)

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

  def sources_for(self, package_relative_path_globs, package_dir=''):
    sources_field = SourcesField(
      Address.parse('{}:_bogus_target_for_test'.format(package_dir)),
      'sources',
      {'globs': package_relative_path_globs},
      None,
      PathGlobs(tuple(os.path.join(package_dir, path) for path in package_relative_path_globs)),
      lambda _: True,
    )
    field = self.scheduler.product_request(HydratedField, [sources_field])[0]
    return field.value

  @classmethod
  def alias_groups(cls):
    """
    :API: public
    """
    return BuildFileAliases(targets={'target': Target})

  @classmethod
  def rules(cls):
    # Required for sources_for:
    return [RootRule(SourcesField)]

  @classmethod
  def build_config(cls):
    build_config = BuildConfiguration()
    build_config.register_aliases(cls.alias_groups())
    build_config.register_rules(cls.rules())
    return build_config

  def setUp(self):
    """
    :API: public
    """
    super().setUp()
    # Avoid resetting the Runtracker here, as that is specific to fork'd process cleanup.
    clean_global_runtime_state(reset_subsystem=True)

    self.addCleanup(self._reset_engine)

    safe_mkdir(self.build_root, clean=True)
    safe_mkdir(self.pants_workdir)
    self.addCleanup(safe_rmtree, self.build_root)

    BuildRoot().path = self.build_root
    self.addCleanup(BuildRoot().reset)

    self.subprocess_dir = os.path.join(self.build_root, '.pids')

    self.options = defaultdict(dict)  # scope -> key-value mapping.
    self.options[''] = {
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

    self._build_configuration = self.build_config()
    self._inited_target = False
    subsystem_util.init_subsystem(Target.TagAssignments)

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

  def _reset_engine(self):
    if self._scheduler is not None:
      self._build_graph.reset()
      self._scheduler.invalidate_all_files()

  @classmethod
  def aggressively_reset_scheduler(cls):
    cls._scheduler = None
    if cls._local_store_dir is not None:
      safe_rmtree(cls._local_store_dir)

  @classmethod
  @contextmanager
  def isolated_local_store(cls):
    cls.aggressively_reset_scheduler()
    cls._init_engine()
    try:
      yield
    finally:
      cls.aggressively_reset_scheduler()

  @property
  def build_root(self):
    return self._build_root()

  @property
  def pants_workdir(self):
    return self._pants_workdir()

  @classmethod
  @memoized_method
  def _build_root(cls):
    return os.path.realpath(mkdtemp(suffix='_BUILD_ROOT'))

  @classmethod
  @memoized_method
  def _pants_workdir(cls):
    return os.path.join(cls._build_root(), '.pants.d')

  @classmethod
  def _init_engine(cls):
    if cls._scheduler is not None:
      return

    cls._local_store_dir = os.path.realpath(safe_mkdtemp())
    safe_mkdir(cls._local_store_dir)

    # NB: This uses the long form of initialization because it needs to directly specify
    # `cls.alias_groups` rather than having them be provided by bootstrap options.
    graph_session = EngineInitializer.setup_legacy_graph_extended(
      pants_ignore_patterns=None,
      local_store_dir=cls._local_store_dir,
      build_file_imports_behavior='allow',
      native=init_native(),
      options_bootstrapper=OptionsBootstrapper.create(args=['--pants-config-files=[]']),
      build_configuration=cls.build_config(),
      build_ignore_patterns=None,
    ).new_session(zipkin_trace_v2=False)
    cls._scheduler = graph_session.scheduler_session
    cls._build_graph, cls._address_mapper = graph_session.create_build_graph(
        TargetRoots([]), cls._build_root()
      )

  @property
  def scheduler(self):
    if self._scheduler is None:
      self._init_engine()
      self.post_scheduler_init()
    return self._scheduler

  def post_scheduler_init(self):
    """Run after initializing the Scheduler, it will have the same lifetime"""
    pass

  @property
  def address_mapper(self):
    if self._address_mapper is None:
      self._init_engine()
    return self._address_mapper

  @property
  def build_graph(self):
    if self._build_graph is None:
      self._init_engine()
    return self._build_graph

  def reset_build_graph(self, reset_build_files=False, delete_build_files=False):
    """Start over with a fresh build graph with no targets in it."""
    if delete_build_files or reset_build_files:
      files = [f for f in self.buildroot_files() if os.path.basename(f) == 'BUILD']
      if delete_build_files:
        for f in files:
          os.remove(os.path.join(self.build_root, f))
      self.invalidate_for(*files)
    if self._build_graph is not None:
      self._build_graph.reset()

  def set_options_for_scope(self, scope, **kwargs):
    self.options[scope].update(kwargs)

  def context(self, for_task_types=None, for_subsystems=None, options=None,
              target_roots=None, console_outstream=None, workspace=None,
              scheduler=None, address_mapper=None, **kwargs):
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

    optionables = {SourceRootConfig} | self._build_configuration.optionables() | for_subsystems

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

    scheduler = scheduler or self.scheduler

    address_mapper = address_mapper or self.address_mapper

    context = create_context_from_options(fake_options,
                                          target_roots=target_roots,
                                          build_graph=self.build_graph,
                                          build_configuration=self._build_configuration,
                                          address_mapper=address_mapper,
                                          console_outstream=console_outstream,
                                          workspace=workspace,
                                          scheduler=scheduler)
    return context

  def tearDown(self):
    """
    :API: public
    """
    super().tearDown()
    Subsystem.reset()

  @classproperty
  def subsystems(cls):
    """Initialize these subsystems when running your test.

    If your test instantiates a target type that depends on any subsystems, those subsystems need to
    be initialized in your test. You can override this property to return the necessary subsystem
    classes.

    :rtype: list of type objects, all subclasses of Subsystem
    """
    return Target.subsystems()

  def _init_target_subsystem(self):
    if not self._inited_target:
      subsystem_util.init_subsystems(self.subsystems)
      self._inited_target = True

  def target(self, spec):
    """Resolves the given target address to a Target object.

    :API: public

    address: The BUILD target address to resolve.

    Returns the corresponding Target or else None if the address does not point to a defined Target.
    """
    self._init_target_subsystem()

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
    targets = []
    for address in self.build_graph.inject_specs_closure([spec]):
      targets.append(self.build_graph.get_target(address))
    return targets

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

  @contextmanager
  def assertRaisesWithMessage(self, exception_type, error_text):
    """Verifies than an exception message is equal to `error_text`.

    :param type exception_type: The exception type which is expected to be raised within the body.
    :param str error_text: Text that the exception message should match exactly with
                           `self.assertEqual()`.
    :API: public
    """
    with self.assertRaises(exception_type) as cm:
      yield cm
    self.assertEqual(error_text, str(cm.exception))

  @contextmanager
  def assertRaisesWithMessageContaining(self, exception_type, error_text):
    """Verifies that the string `error_text` appears in an exception message.

    :param type exception_type: The exception type which is expected to be raised within the body.
    :param str error_text: Text that the exception message should contain with `self.assertIn()`.
    :API: public
    """
    with self.assertRaises(exception_type) as cm:
      yield cm
    self.assertIn(error_text, str(cm.exception))

  def get_bootstrap_options(self, cli_options=()):
    """Retrieves bootstrap options.

    :param cli_options: An iterable of CLI flags to pass as arguments to `OptionsBootstrapper`.
    """
    args = tuple(['--pants-config-files=[]']) + tuple(cli_options)
    return OptionsBootstrapper.create(args=args).bootstrap_options.for_global_scope()

  def make_snapshot(self, files):
    """Makes a snapshot from a collection of files.

    :param files: a dictionary, where key=filename, value=file_content where both are of type String.
    :return: a Snapshot.
    """
    with temporary_dir() as temp_dir:
      for file_name, content in files.items():
        safe_file_dump(os.path.join(temp_dir, file_name), content)
      return self.scheduler.capture_snapshots((
        PathGlobsAndRoot(PathGlobs(('**',)), temp_dir),
      ))[0]

  class LoggingRecorder:
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

    def errors(self):
      return self._messages_for_level('ERROR')

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

  @contextmanager
  def warnings_catcher(self):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter('always')
      yield w

  def assertWarning(self, w, category, warning_text):
    single_warning = assert_single_element(w)
    self.assertEqual(single_warning.category, category)
    warning_message = single_warning.message
    self.assertEqual(warning_text, str(warning_message))

  def retrieve_single_product_at_target_base(self, product_mapping, target):
    mapping_for_target = product_mapping.get(target)
    single_base_dir = assert_single_element(list(mapping_for_target.keys()))
    single_product = assert_single_element(mapping_for_target[single_base_dir])
    return single_product

  def populate_target_dict(self, target_map):
    """Return a dict containing targets with files generated according to `target_map`.

    The keys of `target_map` are target address strings, while the values of `target_map` should be
    a dict which contains keyword arguments fed into `self.make_target()`, along with a few special
    keys. Special keys are:
    - 'key': used to access the target in the returned dict. Defaults to the target address spec.
    - 'filemap': creates files at the specified relative paths to the target.

    An `OrderedDict` of 2-tuples must be used with the targets topologically ordered, if
    they have dependencies on each other. Note that dependency cycles are not currently supported
    with this method.

    :param target_map: Dict mapping each target address to generate -> kwargs for
                       `self.make_target()`, along with a 'key' and optionally a 'filemap' argument.
    :return: Dict mapping the required 'key' argument -> target instance for each element of
             `target_map`.
    :rtype: dict
    """
    target_dict = {}

    # Create a target from each specification and insert it into `target_dict`.
    for target_spec, target_kwargs in target_map.items():
      unprocessed_kwargs = target_kwargs.copy()

      target_base = Address.parse(target_spec).spec_path

      # Populate the target's owned files from the specification.
      filemap = unprocessed_kwargs.pop('filemap', {})
      for rel_path, content in filemap.items():
        buildroot_path = os.path.join(target_base, rel_path)
        self.create_file(buildroot_path, content)

      # Ensure any dependencies exist in the target dict (`target_map` must then be an
      # OrderedDict).
      # The 'key' is used to access the target in `target_dict`, and defaults to `target_spec`.
      target_address = Address.parse(target_spec)
      key = unprocessed_kwargs.pop('key', target_address.target_name)
      dep_targets = []
      for dep_spec in unprocessed_kwargs.pop('dependencies', []):
        existing_tgt_key = target_map[dep_spec]['key']
        dep_targets.append(target_dict[existing_tgt_key])

      # Register the generated target.
      generated_target = self.make_target(
        spec=target_spec, dependencies=dep_targets, **unprocessed_kwargs)
      target_dict[key] = generated_target

    return target_dict
