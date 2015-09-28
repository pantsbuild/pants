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

from pants.backend.codegen.targets.python_antlr_library import PythonAntlrLibrary
from pants.backend.codegen.targets.python_thrift_library import PythonThriftLibrary
# TODO(John Sirois): XXX this dep needs to be fixed.  All pants/java utility code needs to live
# in pants java since non-jvm backends depend on it to run things.
from pants.backend.core.targets.resources import Resources
from pants.backend.jvm.subsystems.jvm import JVM
from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.tasks.setup_py import SetupPy
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot
from pants.fs.archive import TGZ
from pants.util.contextutil import temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdir
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase
from pants_test.subsystem.subsystem_util import subsystem_instance


class TestSetupPy(PythonTaskTestBase):
  @classmethod
  def task_type(cls):
    return SetupPy

  def setUp(self):
    super(TestSetupPy, self).setUp()
    distdir = os.path.join(self.build_root, 'dist')
    self.set_options(pants_distdir=distdir)

    self.dependency_calculator = SetupPy.DependencyCalculator(self.build_graph)

  @property
  def alias_groups(self):
    resources = BuildFileAliases(targets={'resources': Resources})
    return super(TestSetupPy, self).alias_groups.merge(resources)

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
    self.set_options(recursive=recursive)
    context = self.context(target_roots=[target])
    setup_py = self.create_task(context)
    yield setup_py.execute()

  def test_execution_reduced_dependencies_1(self):
    dep_map = OrderedDict(foo=['bar'], bar=['baz'], baz=[])
    target_map = self.create_dependencies(dep_map)
    with self.run_execute(target_map['foo'], recursive=False) as created:
      self.assertEqual([target_map['foo']], created.keys())
    with self.run_execute(target_map['foo'], recursive=True) as created:
      self.assertEqual({target_map['baz'], target_map['bar'], target_map['foo']},
                       set(created.keys()))

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
      self.assertEqual([foo], created.keys())

    with self.run_execute(foo, recursive=True) as created:
      self.assertEqual([foo], created.keys())

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
      self.assertEqual([bar], created.keys())

    with self.run_execute(bar, recursive=True) as created:
      self.assertEqual({bar_bin_dep, bar}, set(created.keys()))

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

  @contextmanager
  def extracted_sdist(src, sdist, expected_prefix, collect_suffixes=None):
    collect_suffixes = collect_suffixes or ('.py',)

    def collect(path):
      for suffix in collect_suffixes:
        if path.endswith(suffix):
          return True
      return False

    with temporary_dir() as chroot:
      TGZ.extract(sdist, chroot)

      all_py_files = set()
      for root, _, files in os.walk(chroot):
        all_py_files.update(os.path.join(root, f) for f in files if collect(f))

      def as_full_path(p):
        return os.path.join(chroot, expected_prefix, p)

      yield all_py_files, as_full_path

  def test_resources(self):
    SourceRoot.register('src/python', PythonLibrary, Resources)
    self.create_file(relpath='src/python/monster/j-function.res', contents='196884')
    self.create_file(relpath='src/python/monster/group.res', contents='196883')
    self.create_file(relpath='src/python/monster/__init__.py', contents='')
    self.create_file(relpath='src/python/monster/research_programme.py',
                     contents='# Look for more off-by-one "errors"!')

    # NB: We have to resort to BUILD files on disk here due to the target ownership algorithm in
    # SetupPy needing to walk ancestors in this case which currently requires BUILD files on disk.
    self.add_to_build_file('src/python/monster', dedent("""
      python_library(
        name='conway',
        sources=['__init__.py', 'research_programme.py'],
        resources=['group.res'],
        resource_targets=[
          ':j-function',
        ],
        provides=setup_py(
          name='monstrous.moonshine',
          version='0.0.0',
        )
      )

      resources(
        name='j-function',
        sources=['j-function.res']
      )
      """))
    conway = self.target('src/python/monster:conway')

    with self.run_execute(conway) as created:
      self.assertEqual([conway], created.keys())

      with self.extracted_sdist(sdist=created[conway],
                                expected_prefix='monstrous.moonshine-0.0.0',
                                collect_suffixes=('.py', '.res')) as (py_files, path):
        self.assertEqual({path('setup.py'),
                          path('src/monster/__init__.py'),
                          path('src/monster/research_programme.py'),
                          path('src/monster/group.res'),
                          path('src/monster/j-function.res')},
                         py_files)

        with open(path('src/monster/group.res')) as fp:
          self.assertEqual('196883', fp.read())

        with open(path('src/monster/j-function.res')) as fp:
          self.assertEqual('196884', fp.read())

  def test_exported_antlr(self):
    SourceRoot.register('src/antlr', PythonThriftLibrary)
    self.create_file(relpath='src/antlr/exported/exported.g', contents=dedent("""
      grammar exported;

      options {
        language = Python;
      }

      WORD: ('a'..'z'|'A'..'Z'|'0'..'9'|'-'|'_')+;

      static: WORD;
    """))
    target = self.make_target(spec='src/antlr/exported',
                              target_type=PythonAntlrLibrary,
                              antlr_version='3.1.3',
                              sources=['exported.g'],
                              module='exported',
                              provides=PythonArtifact(name='test.exported', version='0.0.0'))

    # TODO(John Sirois): This hacks around a direct but undeclared dependency
    # `pants.java.distribution.distribution.Distribution` gained in
    # https://rbcommons.com/s/twitter/r/2657
    # Remove this once proper Subsystem dependency chains are re-established.
    with subsystem_instance(JVM):
      with self.run_execute(target) as created:
        self.assertEqual([target], created.keys())

  def test_exported_thrift(self):
    SourceRoot.register('src/thrift', PythonThriftLibrary)
    self.create_file(relpath='src/thrift/exported/exported.thrift', contents=dedent("""
      namespace py pants.constants_only

      const set<string> VALID_IDENTIFIERS = ["Hello", "World", "!"]
    """))
    target = self.make_target(spec='src/thrift/exported',
                              target_type=PythonThriftLibrary,
                              sources=['exported.thrift'],
                              provides=PythonArtifact(name='test.exported', version='0.0.0'))
    with self.run_execute(target) as created:
      self.assertEqual([target], created.keys())

  def test_exported_thrift_issues_2005(self):
    # Issue #2005 highlighted the fact the PythonThriftBuilder was building both a given
    # PythonThriftLibrary's thrift files as well as its transitive dependencies thrift files.
    # We test here to ensure that independently published PythonThriftLibraries each only own their
    # own thrift stubs and the proper dependency links exist between the distributions.

    SourceRoot.register('src/thrift', PythonThriftLibrary)
    self.create_file(relpath='src/thrift/exported/exported.thrift', contents=dedent("""
      namespace py exported

      const set<string> VALID_IDENTIFIERS = ["Hello", "World", "!"]
    """))
    target1 = self.make_target(spec='src/thrift/exported',
                               target_type=PythonThriftLibrary,
                               sources=['exported.thrift'],
                               provides=PythonArtifact(name='test.exported', version='0.0.0'))

    self.create_file(relpath='src/thrift/exported_dependee/exported_dependee.thrift',
                     contents=dedent("""
                       namespace py exported_dependee

                       include "exported/exported.thrift"

                       const set<string> ALIASED_IDENTIFIERS = exported.VALID_IDENTIFIERS
                     """))
    target2 = self.make_target(spec='src/thrift/exported_dependee',
                               target_type=PythonThriftLibrary,
                               sources=['exported_dependee.thrift'],
                               dependencies=[target1],
                               provides=PythonArtifact(name='test.exported_dependee',
                                                       version='0.0.0'))

    with self.run_execute(target2, recursive=True) as created:
      self.assertEqual({target2, target1}, set(created.keys()))

      with self.extracted_sdist(sdist=created[target1],
                                expected_prefix='test.exported-0.0.0') as (py_files, path):
        self.assertEqual({path('setup.py'),
                          path('src/__init__.py'),
                          path('src/exported/__init__.py'),
                          path('src/exported/constants.py'),
                          path('src/exported/ttypes.py')},
                         py_files)

        self.assertFalse(os.path.exists(path('src/test.exported.egg-info/requires.txt')))

      with self.extracted_sdist(sdist=created[target2],
                                expected_prefix='test.exported_dependee-0.0.0') as (py_files, path):
        self.assertEqual({path('setup.py'),
                          path('src/__init__.py'),
                          path('src/exported_dependee/__init__.py'),
                          path('src/exported_dependee/constants.py'),
                          path('src/exported_dependee/ttypes.py')},
                         py_files)

        requirements = path('src/test.exported_dependee.egg-info/requires.txt')
        self.assertTrue(os.path.exists(requirements))
        with open(requirements) as fp:
          self.assertEqual('test.exported==0.0.0', fp.read().strip())


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
