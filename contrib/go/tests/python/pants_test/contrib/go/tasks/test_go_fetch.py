# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
from collections import defaultdict
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot
from pants.base.target import Target
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, touch
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.tasks.go_fetch import GoFetch


class GoFetchTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return GoFetch

  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={
        'go_remote_library': GoRemoteLibrary,
        'target': Target,
      })

  def test_download_zip(self):
    go_fetch = self.create_task(self.context())
    with temporary_dir() as dest:
      with temporary_dir() as src:
        touch(os.path.join(src, 'mydir', 'myfile.go'))
        zfile = shutil.make_archive(os.path.join(src, 'mydir'), 'zip',
                                    root_dir=src, base_dir='mydir')
        go_fetch._download_zip('file://' + zfile, dest)
        self.assertTrue(os.path.isfile(os.path.join(dest, 'myfile.go')))

        with self.assertRaises(TaskError):
          go_fetch._download_zip('file://' + zfile + 'notreal', dest)

  def test_get_remote_import_ids(self):
    go_fetch = self.create_task(self.context())
    self.create_file('github.com/u/a/a.go', contents="""
      package a

      import (
        "fmt"
        "math"
        "sync"

        "github.com/u/b"
        "github.com/u/c"
      )
    """)
    pkg_dir = os.path.join(self.build_root, 'github.com/u/a')
    remote_import_ids = go_fetch._get_remote_import_ids(pkg_dir)
    self.assertItemsEqual(remote_import_ids, ['github.com/u/b', 'github.com/u/c'])

  def test_resolve_and_inject(self):
    go_fetch = self.create_task(self.context())
    SourceRoot.register(os.path.join(self.build_root, '3rdparty'), Target)
    r1 = self.make_target(spec='3rdparty/r1', target_type=Target)
    self.add_to_build_file('3rdparty/r2',
                           'target(name="{}")'.format('r2'))
    r2 = go_fetch._resolve_and_inject(r1, 'r2')
    self.assertEqual(r2.name, 'r2')
    self.assertItemsEqual(r1.dependencies, [r2])

  def test_resolve_and_inject_failure(self):
    go_fetch = self.create_task(self.context())
    SourceRoot.register(os.path.join(self.build_root, '3rdparty'), Target)
    r1 = self.make_target(spec='3rdparty/r1', target_type=Target)
    with self.assertRaises(go_fetch.UndeclaredRemoteLibError) as cm:
      go_fetch._resolve_and_inject(r1, 'r2')
    self.assertEqual(cm.exception.spec_path, '3rdparty/r2')

  def _create_package(self, dir, name, deps):
    """Creates a Go package inside dir named 'name' importing deps."""
    imports = ['import "{}"'.format(d) for d in deps]
    f = os.path.join(dir, '{name}/{name}.go'.format(name=name))
    self.create_file(f, contents=
      """package {name}
        {imports}
      """.format(name=name, imports='\n'.join(imports)))

  def _create_zip(self, src, dest, name):
    """Zips the Go package in src named 'name' into dest."""
    shutil.make_archive(os.path.join(dest, name), 'zip',
                        root_dir=src, base_dir=name)

  def _create_remote_lib_build_file(self, name):
    self.add_to_build_file(
      '3rdparty/{name}'.format(name=name),
       dedent("""
        go_remote_library(
          name='%s',
          zip_url='{host}/{id}.zip'
        )
       """ % name))

  def _init_dep_graph_files(self, src, zipdir, dep_graph):
    """Given a dependency graph, initializes the corresponding BUILD/packages/zip files.

    Packages are placed in src, and their zipped contents are placed in zipdir.
    """
    for t, deps in dep_graph.items():
      self._create_package(src, t, deps)
      self._create_zip(src, zipdir, t)
      self._create_remote_lib_build_file(t)

  def _create_fetch_context(self, zipdir):
    """Given a directory of zipfiles, creates a context for GoFetch."""
    host = 'file://' + zipdir
    self.set_options(remote_lib_host=host)
    context = self.context()
    context.products.safe_create_data('go_remote_lib_src', lambda: defaultdict(str))
    return context

  def _assert_dependency_graph(self, root_target, dep_map):
    """Recursively assert that the dependency graph starting at root_target matches dep_map."""
    if root_target.name not in dep_map:
      return

    expected_spec_paths = set('3rdparty/{}'.format(name)
                              for name in dep_map[root_target.name])
    actual_spec_paths = set(dep.address.spec_path for dep in root_target.dependencies)
    self.assertEqual(actual_spec_paths, expected_spec_paths)

    dep_map = dep_map.copy()
    del dep_map[root_target.name]
    for dep in root_target.dependencies:
      self._assert_dependency_graph(dep, dep_map)

  def test_transitive_download_remote_libs_simple(self):
    with temporary_dir() as src:
      with temporary_dir() as zipdir:
        SourceRoot.register(os.path.join(self.build_root, '3rdparty'), GoRemoteLibrary)

        dep_graph = {
          'r1': ['r2'],
          'r2': ['r3'],
          'r3': []
        }
        self._init_dep_graph_files(src, zipdir, dep_graph)

        r1 = self.target('3rdparty/r1')

        context = self._create_fetch_context(zipdir)
        go_fetch = self.create_task(context)
        undeclared_deps = go_fetch._transitive_download_remote_libs(set([r1]))
        self.assertEqual(undeclared_deps, {})

        self._assert_dependency_graph(r1, dep_graph)

  def test_transitive_download_remote_libs_complex(self):
    with temporary_dir() as src:
      with temporary_dir() as zipdir:
        SourceRoot.register(os.path.join(self.build_root, '3rdparty'), GoRemoteLibrary)

        dep_graph = {
          'r1': ['r3', 'r4'],
          'r2': ['r3'],
          'r3': ['r4'],
          'r4': []
        }
        self._init_dep_graph_files(src, zipdir, dep_graph)

        r1 = self.target('3rdparty/r1')
        r2 = self.target('3rdparty/r2')

        context = self._create_fetch_context(zipdir)
        go_fetch = self.create_task(context)
        undeclared_deps = go_fetch._transitive_download_remote_libs(set([r1, r2]))
        self.assertEqual(undeclared_deps, {})

        self._assert_dependency_graph(r1, dep_graph)
        self._assert_dependency_graph(r2, dep_graph)

  def test_transitive_download_remote_libs_undeclared_deps(self):
    with temporary_dir() as src:
      with temporary_dir() as zipdir:
        SourceRoot.register(os.path.join(self.build_root, '3rdparty'), GoRemoteLibrary)

        dep_graph = {
          'r1': ['r2', 'r3'],
          'r2': ['r4']
        }
        self._init_dep_graph_files(src, zipdir, dep_graph)

        r1 = self.target('3rdparty/r1')

        context = self._create_fetch_context(zipdir)
        go_fetch = self.create_task(context)
        undeclared_deps = go_fetch._transitive_download_remote_libs(set([r1]))
        expected = defaultdict(set)
        expected['r1'] = set([('r3', '3rdparty/r3')])
        expected['r2'] = set([('r4', '3rdparty/r4')])
        self.assertEqual(undeclared_deps, expected)
