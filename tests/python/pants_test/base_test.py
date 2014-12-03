# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
from contextlib import contextmanager
import os
from tempfile import mkdtemp
from textwrap import dedent
import unittest2 as unittest

from pants.backend.core.tasks.check_exclusives import ExclusivesMapping
from pants.backend.core.targets.dependencies import Dependencies
from pants.base.address import SyntheticAddress
from pants.base.exceptions import TaskError
from pants.base.build_file_address_mapper import BuildFileAddressMapper
from pants.base.build_configuration import BuildConfiguration
from pants.base.build_file import BuildFile
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.build_file_parser import BuildFileParser
from pants.base.build_graph import BuildGraph
from pants.base.build_root import BuildRoot
from pants.base.config import Config
from pants.base.source_root import SourceRoot
from pants.base.target import Target
from pants.goal.goal import Goal
from pants.util.contextutil import environment_as, pushd, temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdir, safe_open, safe_rmtree, touch
from pants_test.base.context_utils import create_context


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
    return BuildFile(root_dir=self.build_root, relpath=self.build_path(relpath))

  def make_target(self,
                  spec='',
                  target_type=Target,
                  dependencies=None,
                  resources = None,
                  derived_from=None,
                  **kwargs):
    address = SyntheticAddress.parse(spec)
    target = target_type(name=address.target_name,
                         address=address,
                         build_graph=self.build_graph,
                         **kwargs)
    dependencies = dependencies or []
    dependencies.extend(resources or [])

    self.build_graph.inject_target(target,
                                   dependencies=[dep.address for dep in dependencies],
                                   derived_from=derived_from)
    return target

  @property
  def alias_groups(self):
    return BuildFileAliases.create(targets={'target': Dependencies})

  def setUp(self):
    super(BaseTest, self).setUp()
    Goal.clear()
    self.real_build_root = BuildRoot().path
    self.build_root = os.path.realpath(mkdtemp(suffix='_BUILD_ROOT'))
    self.new_options = defaultdict(dict)  # scope -> key-value mapping.
    self.new_options[''] = {
      'pants_workdir': os.path.join(self.build_root, '.pants.d'),
      'pants_supportdir': os.path.join(self.build_root, 'build-support'),
      'pants_distdir': os.path.join(self.build_root, 'dist')
    }
    BuildRoot().path = self.build_root

    self.create_file('pants.ini')
    build_configuration = BuildConfiguration()
    build_configuration.register_aliases(self.alias_groups)
    self.build_file_parser = BuildFileParser(build_configuration, self.build_root)
    self.address_mapper = BuildFileAddressMapper(self.build_file_parser)
    self.build_graph = BuildGraph(address_mapper=self.address_mapper)

  def config(self, overrides=''):
    """Returns a config valid for the test build root."""
    if overrides:
      with temporary_file() as fp:
        fp.write(overrides)
        fp.close()
        with environment_as(PANTS_CONFIG_OVERRIDE=fp.name):
          return Config.load()
    else:
      return Config.load()

  def set_new_options_for_scope(self, scope, **kwargs):
    self.new_options[scope].update(kwargs)

  def context(self, for_task_types=None, config='', options=None, new_options=None,
              target_roots=None, **kwargs):
    for_task_types = for_task_types or []
    new_options = new_options or {}

    new_option_values = defaultdict(dict)

    # Get values for all new-style options registered by the tasks in for_task_types.
    for task_type in for_task_types:
      scope = task_type.options_scope
      if scope is None:
        raise TaskError('You must set a scope on your task type before using it in tests.')

      # We provide our own test-only registration implementation, bypassing argparse.
      # When testing we set option values directly, so we don't care about cmd-line flags, config,
      # env vars etc. In fact, for test isolation we explicitly don't want to look at those.
      def register(*rargs, **rkwargs):
        scoped_options = new_option_values[scope]
        default = rkwargs.get('default')
        if default is None and rkwargs.get('action') == 'append':
          default = []
        for flag_name in rargs:
          option_name = flag_name.lstrip('-').replace('-', '_')
          scoped_options[option_name] = default

      task_type.register_options(register)

    # Now override with any caller-specified values.

    # TODO(benjy): Get rid of the new_options arg, and require tests to call set_new_options.
    for scope, opts in new_options.items():
      for key, val in opts.items():
        new_option_values[scope][key] = val

    for scope, opts in self.new_options.items():
      for key, val in opts.items():
        new_option_values[scope][key] = val

    return create_context(config=self.config(overrides=config),
                          new_options = new_option_values,
                          target_roots=target_roots,
                          build_graph=self.build_graph,
                          build_file_parser=self.build_file_parser,
                          address_mapper=self.address_mapper,
                          **kwargs)

  def tearDown(self):
    BuildRoot().reset()
    SourceRoot.reset()
    safe_rmtree(self.build_root)
    BuildFile.clear_cache()

  def target(self, spec):
    """Resolves the given target address to a Target object.

    address: The BUILD target address to resolve.

    Returns the corresponding Target or else None if the address does not point to a defined Target.
    """
    address = SyntheticAddress.parse(spec)
    self.build_graph.inject_address_closure(address)
    return self.build_graph.get_target(address)

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

  @contextmanager
  def workspace(self, *buildfiles):
    with temporary_dir() as root_dir:
      with BuildRoot().temporary(root_dir):
        with pushd(root_dir):
          for buildfile in buildfiles:
            touch(os.path.join(root_dir, buildfile))
          yield os.path.realpath(root_dir)

  def populate_exclusive_groups(self, context, key=None, classpaths=None, target_predicate=None):
    """
    Helps actual test cases to populate the "exclusives_groups" products data mapping
    in the context, which holds the classpath values for targets.

    :param context: The execution context where the products data mapping lives.
    :param key: key for list of classpaths in the "exclusives_groups" data mapping.
      None is the default value for most common cases.
    :param classpaths: a list of classpath strings. If not specified, ['none'] will be used.
    :param target_predicate: filter predicate for the context.targets(). For most common test
      cases, None value is good enough.
    """
    exclusives_mapping = ExclusivesMapping(context)
    exclusives_mapping.set_base_classpath_for_group(
      key or '<none>', [('default', entry) for entry in classpaths or ['none']])
    exclusives_mapping._populate_target_maps(context.targets(target_predicate))
    context.products.safe_create_data('exclusives_groups', lambda: exclusives_mapping)
