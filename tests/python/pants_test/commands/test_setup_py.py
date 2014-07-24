# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from contextlib import contextmanager

from mock import MagicMock, Mock, call
import pytest
from twitter.common.collections import OrderedSet
from twitter.common.dirutil.chroot import Chroot

from pants.backend.python.commands.setup_py import SetupPy
from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.exceptions import TargetDefinitionException
from pants.util.contextutil import temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdir
from pants_test.base_test import BaseTest


class MockableSetupPyCommand(SetupPy):
  def __init__(self, target):
    self.target = target


class TestSetupPy(BaseTest):

  def create_dependencies(self, depmap):
    target_map = {}
    for name, deps in depmap.items():
      target_map[name] = self.make_target(
        spec=name,
        target_type=PythonLibrary,
        provides=PythonArtifact(name=name, version='0.0.0')
      )
    for name, deps in depmap.items():
      target = target_map[name]
      dep_targets = [target_map[name] for name in deps]
      for dep in dep_targets:
        self.build_graph.inject_dependency(target.address, dep.address)
    return target_map

  def test_minified_dependencies_1(self):
    # foo -> bar -> baz
    dep_map = {'foo': ['bar'], 'bar': ['baz'], 'baz': []}
    target_map = self.create_dependencies(dep_map)
    assert SetupPy.minified_dependencies(target_map['foo']) == OrderedSet([target_map['bar']])
    assert SetupPy.minified_dependencies(target_map['bar']) == OrderedSet([target_map['baz']])
    assert SetupPy.minified_dependencies(target_map['baz']) == OrderedSet()
    assert SetupPy.install_requires(target_map['foo']) == set(['bar==0.0.0'])
    assert SetupPy.install_requires(target_map['bar']) == set(['baz==0.0.0'])
    assert SetupPy.install_requires(target_map['baz']) == set([])

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
    target_map = self.create_dependencies(dep_map)
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
    target_map = self.create_dependencies(dep_map)
    assert SetupPy.minified_dependencies(target_map['foo']) == OrderedSet([target_map['bar']])
    assert SetupPy.minified_dependencies(target_map['bar']) == OrderedSet([target_map['baz']])
    assert SetupPy.minified_dependencies(target_map['baz']) == OrderedSet()

  def test_minified_dependencies_diamond(self):
    #   bar <-- foo --> baz
    #    |               |
    #    `----> bak <----'
    dep_map = {'foo': ['bar', 'baz'], 'bar': ['bak'], 'baz': ['bak'], 'bak': []}
    target_map = self.create_dependencies(dep_map)
    assert SetupPy.minified_dependencies(target_map['foo']) == OrderedSet(
        [target_map['baz'], target_map['bar']])
    assert SetupPy.minified_dependencies(target_map['bar']) == OrderedSet([target_map['bak']])
    assert SetupPy.minified_dependencies(target_map['baz']) == OrderedSet([target_map['bak']])
    assert SetupPy.install_requires(target_map['foo']) == set(['bar==0.0.0', 'baz==0.0.0'])
    assert SetupPy.install_requires(target_map['bar']) == set(['bak==0.0.0'])
    assert SetupPy.install_requires(target_map['baz']) == set(['bak==0.0.0'])

  def test_binary_target_injected_into_minified_dependencies(self):
    foo_bin_dep = self.make_target(
      spec = ':foo_bin_dep',
      target_type = PythonLibrary,
    )

    foo_bin = self.make_target(
      spec = ':foo_bin',
      target_type = PythonBinary,
      entry_point = 'foo.bin.foo',
      dependencies = [
        foo_bin_dep,
      ]
    )

    foo = self.make_target(
      spec = ':foo',
      target_type = PythonLibrary,
      provides = PythonArtifact(
        name = 'foo',
        version = '0.0.0',
      ).with_binaries(
        foo_binary = ':foo_bin',
      )
    )

    assert SetupPy.minified_dependencies(foo) == OrderedSet([foo_bin, foo_bin_dep])
    entry_points = dict(SetupPy.iter_entry_points(foo))
    assert entry_points == {'foo_binary': 'foo.bin.foo'}

    with self.run_execute(foo, recursive=False) as setup_py_command:
      setup_py_command.run_one.assert_called_with(foo)

    with self.run_execute(foo, recursive=True) as setup_py_command:
      setup_py_command.run_one.assert_called_with(foo)

  def test_binary_target_injected_into_minified_dependencies_with_provider(self):
    bar_bin_dep = self.make_target(
      spec = ':bar_bin_dep',
      target_type = PythonLibrary,
      provides = PythonArtifact(
        name = 'bar_bin_dep',
        version = '0.0.0',
      )
    )

    bar_bin = self.make_target(
      spec = ':bar_bin',
      target_type = PythonBinary,
      entry_point = 'bar.bin.bar',
      dependencies = [
        bar_bin_dep,
      ],
    )

    bar = self.make_target(
      spec = ':bar',
      target_type = PythonLibrary,
      provides = PythonArtifact(
        name = 'bar',
        version = '0.0.0',
      ).with_binaries(
        bar_binary = ':bar_bin'
      )
    )

    # TODO(pl): Why is this set ordered?  Does the order actually matter?
    assert SetupPy.minified_dependencies(bar) == OrderedSet([bar_bin, bar_bin_dep])
    assert SetupPy.install_requires(bar) == set(['bar_bin_dep==0.0.0'])
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
    foo = self.make_target(
      spec = ':foo',
      target_type = PythonLibrary,
      provides = PythonArtifact(
        name = 'foo',
        version = '0.0.0',
      ).with_binaries(
        foo_binary = ':foo_bin',
      )
    )

    foo_bin = self.make_target(
      spec = ':foo_bin',
      target_type = PythonBinary,
      entry_point = 'foo.bin.foo',
      dependencies = [
        foo,
      ],
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
  assert_single_chroot(['foo'], [], {})
  assert_single_chroot(['foo'], ['foo'], {})

  # assert resources work
  assert_single_chroot(['foo'], [], {'foo': ['blork.dat']})

  resources = {
    'foo': [
      'f0',
      os.path.join('bar', 'baz', 'f1'),
      os.path.join('bar', 'baz', 'f2'),
    ]
  }
  assert_single_chroot(['foo'], [], resources)

  # assert that nearest-submodule is honored
  with yield_chroot(['foo', 'foo.bar'], [], resources) as chroot:
    _, _, r = SetupPy.find_packages(chroot)
    assert r == {
      'foo': set(['f0']),
      'foo.bar': set([
        os.path.join('baz', 'f1'),
        os.path.join('baz', 'f2'),
      ])
    }

  # assert that nearest submodule splits on module prefixes
  with yield_chroot(
      ['foo', 'foo.bar'],
      [],
      {'foo.bar1': ['f0']}) as chroot:

    _, _, r = SetupPy.find_packages(chroot)
    assert r == {'foo': set(['bar1/f0'])}


def test_nearest_subpackage():
  # degenerate
  assert SetupPy.nearest_subpackage('foo', []) == 'foo'
  assert SetupPy.nearest_subpackage('foo', ['foo']) == 'foo'
  assert SetupPy.nearest_subpackage('foo', ['bar']) == 'foo'

  # common prefix
  assert 'foo' == SetupPy.nearest_subpackage('foo.bar', ['foo'])
  assert 'foo.bar' == SetupPy.nearest_subpackage(
      'foo.bar', ['foo', 'foo.bar'])
  assert 'foo.bar' == SetupPy.nearest_subpackage(
      'foo.bar.topo', ['foo', 'foo.bar'])
  assert 'foo' == SetupPy.nearest_subpackage(
      'foo.barization', ['foo', 'foo.bar'])
