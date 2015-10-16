# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import os
import unittest
from collections import defaultdict
from tempfile import mkdtemp
from textwrap import dedent

from pants.base.build_file import FilesystemBuildFile
from pants.base.build_root import BuildRoot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot
from pants.build_graph.address import Address
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_address_mapper import BuildFileAddressMapper
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.build_file_parser import BuildFileParser
from pants.build_graph.build_graph import BuildGraph
from pants.build_graph.target import Target
from pants.goal.goal import Goal
from pants.source.source_root import SourceRootConfig
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_mkdir, safe_open, safe_rmtree
from pants_test.base.context_utils import create_context
from pants_test.option.util.fakes import create_options_for_optionables


# TODO: Rename to 'TestBase', for uniformity, and also for logic: This is a baseclass
# for tests, not a test of a thing called 'Base'.
class BaseTest(unittest.TestCase):
  """A baseclass useful for tests requiring a temporary buildroot."""

  def build_path(self, relpath):
    """Returns the canonical BUILD file path for the given relative build path."""
    if os.path.basename(relpath).startswith('BUILD'):
      return relpath
    else:
      return os.path.join(relpath, 'BUILD')

  def create_dir(self, relpath):
    """Creates a directory under the buildroot.

    relpath: The relative path to the directory from the build root.
    """
    path = os.path.join(self.build_root, relpath)
    safe_mkdir(path)
    return path

  def create_file(self, relpath, contents='', mode='wb'):
    """Writes to a file under the buildroot.

    relpath:  The relative path to the file from the build root.
    contents: A string containing the contents of the file - '' by default..
    mode:     The mode to write to the file in - over-write by default.
    """
    path = os.path.join(self.build_root, relpath)
    with safe_open(path, mode=mode) as fp:
      fp.write(contents)
    return path

  def add_to_build_file(self, relpath, target):
    """Adds the given target specification to the BUILD file at relpath.

    relpath: The relative path to the BUILD file from the build root.
    target:  A string containing the target definition as it would appear in a BUILD file.
    """
    self.create_file(self.build_path(relpath), target, mode='a')
    cls = self.address_mapper._build_file_type
    return cls(root_dir=self.build_root, relpath=self.build_path(relpath))

  def make_target(self,
                  spec='',
                  target_type=Target,
                  dependencies=None,
                  derived_from=None,
                  **kwargs):
    """Creates a target and injects it into the test's build graph.

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

    self.build_graph.inject_target(target,
                                   dependencies=[dep.address for dep in dependencies],
                                   derived_from=derived_from)

    # TODO(John Sirois): This re-creates a little bit too much work done by the BuildGraph.
    # Fixup the BuildGraph to deal with non BuildFileAddresses better and just leverage it.
    for traversable_dependency_spec in target.traversable_dependency_specs:
      traversable_dependency_address = Address.parse(traversable_dependency_spec,
                                                     relative_to=address.spec_path)
      traversable_dependency_target = self.build_graph.get_target(traversable_dependency_address)
      if not traversable_dependency_target:
        raise ValueError('Tests must make targets for traversable dependency specs ahead of them '
                         'being traversed, {} tried to traverse {} which does not exist.'
                         .format(target, traversable_dependency_address))
      if traversable_dependency_target not in target.dependencies:
        self.build_graph.inject_dependency(dependent=target.address,
                                           dependency=traversable_dependency_address)
        target.mark_transitive_invalidation_hash_dirty()

    return target

  @property
  def alias_groups(self):
    # NB: In a normal pants deployment, 'target' is an alias for
    # `pants.backend.core.targets.dependencies.Dependencies`.  We avoid that dependency on the core
    # backend here since the `BaseTest` is used by lower level tests in base and since the
    # `Dependencies` type itself is nothing more than an alias for Target that carries along a
    # pydoc for the BUILD dictionary.
    return BuildFileAliases(targets={'target': Target})

  def setUp(self):
    super(BaseTest, self).setUp()
    Goal.clear()
    Subsystem.reset()

    self.real_build_root = BuildRoot().path

    self.build_root = os.path.realpath(mkdtemp(suffix='_BUILD_ROOT'))
    self.addCleanup(safe_rmtree, self.build_root)

    self.pants_workdir = os.path.join(self.build_root, '.pants.d')
    safe_mkdir(self.pants_workdir)

    self.options = defaultdict(dict)  # scope -> key-value mapping.
    self.options[''] = {
      'pants_workdir': self.pants_workdir,
      'pants_supportdir': os.path.join(self.build_root, 'build-support'),
      'pants_distdir': os.path.join(self.build_root, 'dist'),
      'pants_configdir': os.path.join(self.build_root, 'config'),
      'cache_key_gen_version': '0-test',
    }

    # Many tests need source root functionality, so might as well always set it up.
    self.options['source'] = {
    }

    BuildRoot().path = self.build_root
    self.addCleanup(BuildRoot().reset)

    # We need a pants.ini, even if empty. get_buildroot() uses its presence.
    self.create_file('pants.ini')
    self._build_configuration = BuildConfiguration()
    self._build_configuration.register_aliases(self.alias_groups)
    self.build_file_parser = BuildFileParser(self._build_configuration, self.build_root)
    self.address_mapper = BuildFileAddressMapper(self.build_file_parser, FilesystemBuildFile)
    self.build_graph = BuildGraph(address_mapper=self.address_mapper)

  def buildroot_files(self, relpath=None):
    """Returns the set of all files under the test build root.

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
    self.address_mapper = BuildFileAddressMapper(self.build_file_parser, FilesystemBuildFile)
    self.build_graph = BuildGraph(address_mapper=self.address_mapper)

  def set_options_for_scope(self, scope, **kwargs):
    self.options[scope].update(kwargs)

  def context(self, for_task_types=None, options=None, passthru_args=None, target_roots=None,
              console_outstream=None, workspace=None, for_subsystems=None):

    # Many tests need source root functionality, so might as well always set it up.
    optionables = {SourceRootConfig}
    extra_scopes = set()

    for_subsystems = for_subsystems or ()
    for subsystem in for_subsystems:
      if subsystem.options_scope is None:
        raise TaskError('You must set a scope on your subsystem type before using it in tests.')
      optionables.add(subsystem)

    for_task_types = for_task_types or ()
    for task_type in for_task_types:
      scope = task_type.options_scope
      if scope is None:
        raise TaskError('You must set a scope on your task type before using it in tests.')
      optionables.add(task_type)
      extra_scopes.update([si.scope for si in task_type.known_scope_infos()])
      optionables.update(Subsystem.closure(
        set([dep.subsystem_cls for dep in task_type.subsystem_dependencies_iter()]) |
            self._build_configuration.subsystems()))

    # Now default the option values and override with any caller-specified values.
    # TODO(benjy): Get rid of the options arg, and require tests to call set_options.
    options = options.copy() if options else {}
    for s, opts in self.options.items():
      scoped_opts = options.setdefault(s, {})
      scoped_opts.update(opts)

    options = create_options_for_optionables(optionables,
                                             extra_scopes=extra_scopes,
                                             options=options)
    Subsystem._options = options
    context = create_context(options=options,
                             passthru_args=passthru_args,
                             target_roots=target_roots,
                             build_graph=self.build_graph,
                             build_file_parser=self.build_file_parser,
                             address_mapper=self.address_mapper,
                             console_outstream=console_outstream,
                             workspace=workspace)
    return context

  def tearDown(self):
    SourceRoot.reset()
    FilesystemBuildFile.clear_cache()
    Subsystem.reset()

  def target(self, spec):
    """Resolves the given target address to a Target object.

    address: The BUILD target address to resolve.

    Returns the corresponding Target or else None if the address does not point to a defined Target.
    """
    address = Address.parse(spec)
    self.build_graph.inject_address_closure(address)
    return self.build_graph.get_target(address)

  def targets(self, spec):
    """Resolves a target spec to one or more Target objects.

    spec: Either BUILD target address or else a target glob using the siblings ':' or
          descendants '::' suffixes.

    Returns the set of all Targets found.
    """

    spec_parser = CmdLineSpecParser(self.build_root, self.address_mapper)
    addresses = list(spec_parser.parse_addresses(spec))
    for address in addresses:
      self.build_graph.inject_address_closure(address)
    targets = [self.build_graph.get_target(address) for address in addresses]
    return targets

  def create_files(self, path, files):
    """Writes to a file under the buildroot with contents same as file name.

     path:  The relative path to the file from the build root.
     files: List of file names.
    """
    for f in files:
      self.create_file(os.path.join(path, f), contents=f)

  def create_library(self, path, target_type, name, sources=None, **kwargs):
    """Creates a library target of given type at the BUILD file at path with sources

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
            %(resources)s
            %(java_sources)s
            %(provides)s
            %(dependencies)s
          )
        ''' % dict(target_type=target_type,
                   name=name,
                   sources=('sources=%s,' % repr(sources)
                              if sources else ''),
                   resources=('resources=["%s"],' % kwargs.get('resources')
                              if 'resources' in kwargs else ''),
                   java_sources=('java_sources=[%s],'
                                 % ','.join(map(lambda str_target: '"%s"' % str_target,
                                                kwargs.get('java_sources')))
                                 if 'java_sources' in kwargs else ''),
                   provides=('provides=%s,' % kwargs.get('provides')
                              if 'provides' in kwargs else ''),
                   dependencies=('dependencies=%s,' % kwargs.get('dependencies')
                              if 'dependencies' in kwargs else ''),
                   )))
    return self.target('%s:%s' % (path, name))

  def create_resources(self, path, name, *sources):
    return self.create_library(path, 'resources', name, sources)

  def assertUnorderedPrefixEqual(self, expected, actual_iter):
    """Consumes len(expected) items from the given iter, and asserts that they match, unordered."""
    actual = list(itertools.islice(actual_iter, len(expected)))
    self.assertEqual(sorted(expected), sorted(actual))

  def assertPrefixEqual(self, expected, actual_iter):
    """Consumes len(expected) items from the given iter, and asserts that they match, in order."""
    self.assertEqual(expected, list(itertools.islice(actual_iter, len(expected))))
