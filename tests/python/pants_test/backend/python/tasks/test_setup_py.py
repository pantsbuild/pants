# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import OrderedDict
from contextlib import contextmanager
from textwrap import dedent

from mock import Mock
from twitter.common.collections import OrderedSet
from twitter.common.dirutil.chroot import Chroot

from pants.backend.python.tasks.setup_py import SetupPy
from pants.base.exceptions import TaskError
from pants.util.contextutil import temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdir
from pants_test.backend.python.tasks.python_task_test import PythonTaskTest


class TestSetupPy(PythonTaskTest):
  @classmethod
  def task_type(cls):
    return SetupPy

  def setUp(self):
    super(TestSetupPy, self).setUp()

    distdir = os.path.join(self._tmpdir, 'dist')
    self.set_options(pants_distdir=distdir)

    self.dependency_calculator = SetupPy.DependencyCalculator(self.build_graph)

  def create_dependencies(self, depmap):
    target_map = {}
    for name, deps in depmap.items():
      target_map[name] = self.create_python_library(
        relpath=name,
        name=name,
        provides='setup_py(name="{name}", version="0.0.0")'.format(name=name)
      )
    for name, deps in depmap.items():
      target = target_map[name]
      dep_targets = [target_map[name] for name in deps]
      for dep in dep_targets:
        self.build_graph.inject_dependency(target.address, dep.address)
    return target_map

  def assert_requirements(self, target, expected):
    reduced_dependencies = self.dependency_calculator.reduced_dependencies(target)
    self.assertEqual(SetupPy.install_requires(reduced_dependencies), expected)

  def test_reduced_dependencies_1(self):
    # foo -> bar -> baz
    dep_map = OrderedDict(foo=['bar'], bar=['baz'], baz=[])
    target_map = self.create_dependencies(dep_map)
    self.assertEqual(self.dependency_calculator.reduced_dependencies(target_map['foo']),
                     OrderedSet([target_map['bar']]))
    self.assertEqual(self.dependency_calculator.reduced_dependencies(target_map['bar']),
                     OrderedSet([target_map['baz']]))
    self.assertEqual(self.dependency_calculator.reduced_dependencies(target_map['baz']),
                     OrderedSet())
    self.assert_requirements(target_map['foo'], {'bar==0.0.0'})
    self.assert_requirements(target_map['bar'], {'baz==0.0.0'})
    self.assert_requirements(target_map['baz'], set())

  @contextmanager
  def run_execute(self, target, recursive=False):
    self.set_options(recursive=recursive, interpreter=[])
    context = self.context(target_roots=[target])
    setup_py = self.create_task(context)
    yield setup_py.execute()

  def test_execution_reduced_dependencies_1(self):
    dep_map = OrderedDict(foo=['bar'], bar=['baz'], baz=[])
    target_map = self.create_dependencies(dep_map)
    with self.run_execute(target_map['foo'], recursive=False) as created:
      self.assertEqual([target_map['foo']], created)
    with self.run_execute(target_map['foo'], recursive=True) as created:
      self.assertEqual([target_map['baz'], target_map['bar'], target_map['foo']], created)

  def test_reduced_dependencies_2(self):
    # foo --> baz
    #  |      ^
    #  v      |
    # bar ----'
    dep_map = OrderedDict(foo=['bar', 'baz'], bar=['baz'], baz=[])
    target_map = self.create_dependencies(dep_map)
    self.assertEqual(self.dependency_calculator.reduced_dependencies(target_map['foo']),
                     OrderedSet([target_map['bar'], target_map['baz']]))
    self.assertEqual(self.dependency_calculator.reduced_dependencies(target_map['bar']),
                     OrderedSet([target_map['baz']]))
    self.assertEqual(self.dependency_calculator.reduced_dependencies(target_map['baz']),
                     OrderedSet())

  def test_reduced_dependencies_diamond(self):
    #   bar <-- foo --> baz
    #    |               |
    #    `----> bak <----'
    dep_map = OrderedDict(foo=['bar', 'baz'], bar=['bak'], baz=['bak'], bak=[])
    target_map = self.create_dependencies(dep_map)
    self.assertEqual(self.dependency_calculator.reduced_dependencies(target_map['foo']),
                     OrderedSet([target_map['bar'], target_map['baz']]))
    self.assertEqual(self.dependency_calculator.reduced_dependencies(target_map['bar']),
                     OrderedSet([target_map['bak']]))
    self.assertEqual(self.dependency_calculator.reduced_dependencies(target_map['baz']),
                     OrderedSet([target_map['bak']]))
    self.assert_requirements(target_map['foo'], {'bar==0.0.0', 'baz==0.0.0'})
    self.assert_requirements(target_map['bar'], {'bak==0.0.0'})
    self.assert_requirements(target_map['baz'], {'bak==0.0.0'})

  def test_binary_target_injected_into_reduced_dependencies(self):
    foo_bin_dep = self.create_python_library(relpath='foo/dep', name='dep')

    foo_bin = self.create_python_binary(
      relpath='foo/bin',
      name='bin',
      entry_point='foo.bin:foo',
      dependencies=[
        'foo/dep',
      ]
    )

    foo = self.create_python_library(
      relpath='foo',
      name='foo',
      provides=dedent("""
      setup_py(
        name='foo',
        version='0.0.0'
      ).with_binaries(
        foo_binary='foo/bin'
      )
      """)
    )

    self.assertEqual(self.dependency_calculator.reduced_dependencies(foo),
                     OrderedSet([foo_bin, foo_bin_dep]))
    entry_points = dict(SetupPy.iter_entry_points(foo))
    self.assertEqual(entry_points, {'foo_binary': 'foo.bin:foo'})

    with self.run_execute(foo, recursive=False) as created:
      self.assertEqual([foo], created)

    with self.run_execute(foo, recursive=True) as created:
      self.assertEqual([foo], created)

  def test_binary_target_injected_into_reduced_dependencies_with_provider(self):
    bar_bin_dep = self.create_python_library(
      relpath='bar/dep',
      name='dep',
      provides=dedent("""
      setup_py(
        name='bar_bin_dep',
        version='0.0.0'
      )
      """)
    )

    bar_bin = self.create_python_binary(
      relpath='bar/bin',
      name='bin',
      entry_point='bar.bin:bar',
      dependencies=[
        'bar/dep'
      ],
    )

    bar = self.create_python_library(
      relpath='bar',
      name='bar',
      provides=dedent("""
      setup_py(
        name='bar',
        version='0.0.0'
      ).with_binaries(
        bar_binary='bar/bin'
      )
      """)
    )

    self.assertEqual(self.dependency_calculator.reduced_dependencies(bar),
                     OrderedSet([bar_bin, bar_bin_dep]))
    self.assert_requirements(bar, {'bar_bin_dep==0.0.0'})
    entry_points = dict(SetupPy.iter_entry_points(bar))
    self.assertEqual(entry_points, {'bar_binary': 'bar.bin:bar'})

    with self.run_execute(bar, recursive=False) as created:
      self.assertEqual([bar], created)

    with self.run_execute(bar, recursive=True) as created:
      self.assertEqual([bar_bin_dep, bar], created)

  def test_pants_contrib_case(self):
    def create_requirement_lib(name):
      return self.create_python_requirement_library(
        relpath=name,
        name=name,
        requirements=[
          '{}==1.1.1'.format(name)
        ]
      )

    req1 = create_requirement_lib('req1')
    create_requirement_lib('req2')
    req3 = create_requirement_lib('req3')

    self.create_python_library(
      relpath='src/python/pants/base',
      name='base',
      dependencies=[
        'req1',
        'req2',
      ]
    )
    self.create_python_binary(
      relpath='src/python/pants/bin',
      name='bin',
      entry_point='pants.bin.pants_exe:main',
      dependencies=[
        # Should be stripped in reduced_dependencies since pants_packaged provides these sources.
        'src/python/pants/base',
      ]
    )
    pants_packaged = self.create_python_library(
      relpath='src/python/pants',
      name='pants_packaged',
      provides=dedent("""
      setup_py(
        name='pants_packaged',
        version='0.0.0'
      ).with_binaries(
        # Should be stripped in reduced_dependencies since pants_packaged provides this.
        pants_bin='src/python/pants/bin'
      )
      """)
    )
    contrib_lib = self.create_python_library(
      relpath='contrib/lib/src/python/pants/contrib/lib',
      name='lib',
      dependencies=[
        'req3',
        # Should be stripped in reduced_dependencies since pants_packaged provides these sources.
        'src/python/pants/base',
      ]
    )
    contrib_plugin = self.create_python_library(
      relpath='contrib/lib/src/python/pants/contrib',
      name='plugin',
      provides=dedent("""
      setup_py(
        name='contrib',
        version='0.0.0'
      )
      """),
      dependencies=[
        'contrib/lib/src/python/pants/contrib/lib',
        'src/python/pants:pants_packaged',
        'req1'
      ]
    )
    reduced_dependencies = self.dependency_calculator.reduced_dependencies(contrib_plugin)
    self.assertEqual(reduced_dependencies, OrderedSet([contrib_lib, req3, pants_packaged, req1]))

  def test_no_exported(self):
    foo = self.create_python_library(relpath='foo', name='foo')
    with self.assertRaises(TaskError):
      with self.run_execute(foo):
        self.fail('Should not have gotten past run_execute.')

  def test_no_owner(self):
    self.create_python_library(relpath='foo', name='foo')
    exported = self.create_python_library(
      relpath='bar',
      name='bar',
      dependencies=[
        'foo'
      ],
      provides=dedent("""
      setup_py(
        name='bar',
        version='0.0.0'
      )
      """),
    )
    # `foo` is not in `bar`'s address space and has no owner in its own address space.
    with self.assertRaises(self.dependency_calculator.NoOwnerError):
      self.dependency_calculator.reduced_dependencies(exported)


  def test_ambiguous_owner(self):
    self.create_python_library(relpath='foo/bar', name='bar')
    self.create_file(relpath=self.build_path('foo'), contents=dedent("""
    python_library(
      name='foo1',
      dependencies=[
        'foo/bar'
      ],
      provides=setup_py(
        name='foo1',
        version='0.0.0'
      )
    )
    python_library(
      name='foo2',
      dependencies=[
        'foo/bar'
      ],
      provides=setup_py(
        name='foo2',
        version='0.0.0'
      )
    )
    """))

    with self.assertRaises(self.dependency_calculator.AmbiguousOwnerError):
      self.dependency_calculator.reduced_dependencies(self.target('foo:foo1'))

    with self.assertRaises(self.dependency_calculator.AmbiguousOwnerError):
      self.dependency_calculator.reduced_dependencies(self.target('foo:foo2'))


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
      'foo': {'f0'},
      'foo.bar': {os.path.join('baz', 'f1'), os.path.join('baz', 'f2')}
    }

  # assert that nearest submodule splits on module prefixes
  with yield_chroot(
      ['foo', 'foo.bar'],
      [],
      {'foo.bar1': ['f0']}) as chroot:

    _, _, r = SetupPy.find_packages(chroot)
    assert r == {'foo': {'bar1/f0'}}


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
