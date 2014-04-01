# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import unittest
from contextlib import contextmanager

import pytest
from mock import MagicMock, Mock, call
from twitter.common.collections import OrderedSet
from twitter.common.collections import OrderedSet
from twitter.common.contextutil import temporary_dir, temporary_file
from twitter.common.dirutil import safe_mkdir, touch
from twitter.common.dirutil.chroot import Chroot

from pants.base.parse_context import ParseContext
from pants.base.target import Target, TargetDefinitionException
from pants.commands.setup_py import SetupPy
from pants.targets.pants_target import Pants as pants
from pants.targets.python_artifact import PythonArtifact as setup_py
from pants.targets.python_binary import PythonBinary as python_binary
from pants.targets.python_library import PythonLibrary as python_library


def create_dependencies(depmap):
  target_map = {}
  with ParseContext.temp():
    for name, deps in depmap.items():
      target_map[name] = python_library(
        name=name,
        provides=setup_py(name=name, version='0.0.0'),
        dependencies=[pants(':%s' % dep) for dep in deps]
      )
  return target_map


class MockableSetupPyCommand(SetupPy):
  def __init__(self, target):
    self.target = target


class TestSetupPy(unittest.TestCase):
  def tearDown(self):
    Target._clear_all_addresses()

  def test_minified_dependencies_1(self):
    # foo -> bar -> baz
    dep_map = {'foo': ['bar'], 'bar': ['baz'], 'baz': []}
    target_map = create_dependencies(dep_map)
    assert SetupPy.minified_dependencies(target_map['foo']) == OrderedSet([target_map['bar']])
    assert SetupPy.minified_dependencies(target_map['bar']) == OrderedSet([target_map['baz']])
    assert SetupPy.minified_dependencies(target_map['baz']) == OrderedSet()

  @classmethod
  @contextmanager
  def run_execute(cls, target, recursive=False):
    setup_py = MockableSetupPyCommand(target)
    setup_py.options = MagicMock()
    setup_py.options.recursive = recursive
    setup_py.run_one = MagicMock()
    setup_py.run_one.return_value = True
    setup_py.execute()
    yield setup_py

  def test_execution_minified_dependencies_1(self):
    dep_map = {'foo': ['bar'], 'bar': ['baz'], 'baz': []}
    target_map = create_dependencies(dep_map)
    with self.run_execute(target_map['foo'], recursive=False) as setup_py:
      setup_py.run_one.assert_called_with(target_map['foo'])
    with self.run_execute(target_map['foo'], recursive=True) as setup_py:
      setup_py.run_one.assert_has_calls([
          call(target_map['foo']),
          call(target_map['bar']),
          call(target_map['baz'])
      ], any_order=True)

  def test_minified_dependencies_2(self):
    # foo --> baz
    #  |      ^
    #  v      |
    # bar ----'
    dep_map = {'foo': ['bar', 'baz'], 'bar': ['baz'], 'baz': []}
    target_map = create_dependencies(dep_map)
    assert SetupPy.minified_dependencies(target_map['foo']) == OrderedSet([target_map['bar']])
    assert SetupPy.minified_dependencies(target_map['bar']) == OrderedSet([target_map['baz']])
    assert SetupPy.minified_dependencies(target_map['baz']) == OrderedSet()

  def test_minified_dependencies_diamond(self):
    #   bar <-- foo --> baz
    #    |               |
    #    `----> bak <----'
    dep_map = {'foo': ['bar', 'baz'], 'bar': ['bak'], 'baz': ['bak'], 'bak': []}
    target_map = create_dependencies(dep_map)
    assert SetupPy.minified_dependencies(target_map['foo']) == OrderedSet(
        [target_map['bar'], target_map['baz']])
    assert SetupPy.minified_dependencies(target_map['bar']) == OrderedSet([target_map['bak']])
    assert SetupPy.minified_dependencies(target_map['baz']) == OrderedSet([target_map['bak']])

  def test_binary_target_injected_into_minified_dependencies(self):
    with ParseContext.temp():
      foo = python_library(
        name = 'foo',
        provides = setup_py(
          name = 'foo',
          version = '0.0.0',
        ).with_binaries(
          foo_binary = pants(':foo_bin')
        )
      )

      foo_bin = python_binary(
        name = 'foo_bin',
        entry_point = 'foo.bin.foo',
        dependencies = [ pants(':foo_bin_dep') ]
      )

      foo_bin_dep = python_library(
        name = 'foo_bin_dep'
      )

    assert SetupPy.minified_dependencies(foo) == OrderedSet([foo_bin, foo_bin_dep])
    entry_points = dict(SetupPy.iter_entry_points(foo))
    assert entry_points == {'foo_binary': 'foo.bin.foo'}

    with self.run_execute(foo, recursive=False) as setup_py_command:
      setup_py_command.run_one.assert_called_with(foo)

    with self.run_execute(foo, recursive=True) as setup_py_command:
      setup_py_command.run_one.assert_called_with(foo)

  def test_binary_target_injected_into_minified_dependencies_with_provider(self):
    with ParseContext.temp():
      bar = python_library(
        name = 'bar',
        provides = setup_py(
          name = 'bar',
          version = '0.0.0',
        ).with_binaries(
          bar_binary = pants(':bar_bin')
        )
      )

      bar_bin = python_binary(
        name = 'bar_bin',
        entry_point = 'bar.bin.bar',
        dependencies = [ pants(':bar_bin_dep') ]
      )

      bar_bin_dep = python_library(
        name = 'bar_bin_dep',
        provides = setup_py(
          name = 'bar_bin_dep',
          version = '0.0.0',
        )
      )

    assert SetupPy.minified_dependencies(bar) == OrderedSet([bar_bin, bar_bin_dep])
    entry_points = dict(SetupPy.iter_entry_points(bar))
    assert entry_points == {'bar_binary': 'bar.bin.bar'}

    with self.run_execute(bar, recursive=False) as setup_py_command:
      setup_py_command.run_one.assert_called_with(bar)

    with self.run_execute(bar, recursive=True) as setup_py_command:
      setup_py_command.run_one.assert_has_calls([
          call(bar),
          call(bar_bin_dep)
      ], any_order=True)

  def test_binary_cycle(self):
    with ParseContext.temp():
      foo = python_library(
        name = 'foo',
        provides = setup_py(
          name = 'foo',
          version = '0.0.0',
        ).with_binaries(
          foo_binary = pants(':foo_bin')
        )
      )

      foo_bin = python_binary(
        name = 'foo_bin',
        entry_point = 'foo.bin.foo',
        dependencies = [ pants(':foo') ]
      )

    with pytest.raises(TargetDefinitionException):
      SetupPy.minified_dependencies(foo)


def test_detect_namespace_packages():
  def has_ns(stmt):
    with temporary_file() as fp:
      fp.write(stmt)
      fp.flush()
      return SetupPy.declares_namespace_package(fp.name)

  assert not has_ns('')
  assert not has_ns('add(1, 2); foo(__name__); self.shoot(__name__)')
  assert not has_ns('declare_namespace(bonk)')
  assert has_ns('__import__("pkg_resources").declare_namespace(__name__)')
  assert has_ns('import pkg_resources; pkg_resources.declare_namespace(__name__)')
  assert has_ns('from pkg_resources import declare_namespace; declare_namespace(__name__)')


@contextmanager
def yield_chroot(packages, namespace_packages, resources):
  def to_path(package):
    return package.replace('.', os.path.sep)

  with temporary_dir() as td:
    def write(package, name, content):
      package_path = os.path.join(td, SetupPy.SOURCE_ROOT, to_path(package))
      safe_mkdir(os.path.dirname(os.path.join(package_path, name)))
      with open(os.path.join(package_path, name), 'w') as fp:
        fp.write(content)
    for package in packages:
      write(package, '__init__.py', '')
    for package in namespace_packages:
      write(package, '__init__.py', '__import__("pkg_resources").declare_namespace(__name__)')
    for package, resource_list in resources.items():
      for resource in resource_list:
        write(package, resource, 'asdfasdf')

    chroot_mock = Mock(spec=Chroot)
    chroot_mock.path.return_value = td
    yield chroot_mock


def test_find_packages():
  def assert_single_chroot(packages, namespace_packages, resources):
    with yield_chroot(packages, namespace_packages, resources) as chroot:
      p, n_p, r = SetupPy.find_packages(chroot)
      assert p == set(packages + namespace_packages)
      assert n_p == set(namespace_packages)
      assert r == dict((k, set(v)) for (k, v) in resources.items())

  # assert both packages and namespace packages work
  assert_single_chroot(['twitter'], [], {})
  assert_single_chroot(['twitter'], ['twitter'], {})

  # assert resources work
  assert_single_chroot(['twitter'], [], {'twitter': ['blork.dat']})

  resources = {
    'twitter': [
      'README.rst',
      os.path.join('pants', 'templates', 'ivy.mk'),
      os.path.join('pants', 'templates', 'maven.mk'),
    ]
  }
  assert_single_chroot(['twitter'], [], resources)

  # assert that nearest-submodule is honored
  with yield_chroot(['twitter', 'pants'], [], resources) as chroot:
    _, _, r = SetupPy.find_packages(chroot)
    assert r == {
      'twitter': set(['README.rst']),
      'pants': set([
        os.path.join('templates', 'ivy.mk'),
        os.path.join('templates', 'maven.mk'),
      ])
    }

  # assert that nearest submodule splits on module prefixes
  with yield_chroot(
      ['twitter', 'twitter.util'],
      [],
      {'twitter.utilization': ['README.rst']}) as chroot:

    _, _, r = SetupPy.find_packages(chroot)
    assert r == {'twitter': set(['utilization/README.rst'])}


def test_nearest_subpackage():
  # degenerate
  assert SetupPy.nearest_subpackage('twitter', []) == 'twitter'
  assert SetupPy.nearest_subpackage('twitter', ['twitter']) == 'twitter'
  assert SetupPy.nearest_subpackage('twitter', ['foursquare']) == 'twitter'

  # common prefix
  assert 'twitter' == SetupPy.nearest_subpackage('twitter.util', ['twitter'])
  assert 'twitter.util' == SetupPy.nearest_subpackage(
      'twitter.util', ['twitter', 'twitter.util'])
  assert 'twitter.util' == SetupPy.nearest_subpackage(
      'twitter.util.topo', ['twitter', 'twitter.util'])
  assert 'twitter' == SetupPy.nearest_subpackage(
      'twitter.utilization', ['twitter', 'twitter.util'])
