# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
from collections import defaultdict

from pants.build_graph.address import Address
from pants.util.contextutil import temporary_dir
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.go.subsystems.fetchers import ArchiveFetcher, Fetchers
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.tasks.go_fetch import GoFetch


class GoFetchTest(TaskTestBase):

  address = Address.parse

  @classmethod
  def task_type(cls):
    return GoFetch

  def test_get_remote_import_paths(self):
    go_fetch = self.create_task(self.context())
    self.create_file('src/github.com/u/a/a.go', contents="""
      package a

      import (
        "fmt"
        "math"
        "sync"

        "bitbucket.org/u/b"
        "github.com/u/c"
      )
    """)
    remote_import_ids = go_fetch._get_remote_import_paths('github.com/u/a',
                                                          gopath=self.build_root)
    self.assertItemsEqual(remote_import_ids, ['bitbucket.org/u/b', 'github.com/u/c'])

  def test_get_remote_import_paths_relative_ignored(self):
    go_fetch = self.create_task(self.context())
    self.create_file('src/github.com/u/r/a/a_test.go', contents="""
      package a

      import (
        "fmt"
        "math"
        "sync"

        "bitbucket.org/u/b"
        "github.com/u/c"
        "./b"
        "../c/d"
      )
    """)
    remote_import_ids = go_fetch._get_remote_import_paths('github.com/u/r/a',
                                                          gopath=self.build_root)
    self.assertItemsEqual(remote_import_ids, ['bitbucket.org/u/b', 'github.com/u/c'])

  def test_resolve_and_inject_explicit(self):
    r1 = self.make_target(spec='3rdparty/go/r1', target_type=GoRemoteLibrary)
    r2 = self.make_target(spec='3rdparty/go/r2', target_type=GoRemoteLibrary)

    go_fetch = self.create_task(self.context())
    resolved = go_fetch._resolve(r1, self.address('3rdparty/go/r2'), 'r2', implict_ok=False)
    self.assertEqual(r2, resolved)

  def test_resolve_and_inject_explicit_failure(self):
    r1 = self.make_target(spec='3rdparty/go/r1', target_type=GoRemoteLibrary)
    go_fetch = self.create_task(self.context())
    with self.assertRaises(go_fetch.UndeclaredRemoteLibError) as cm:
      go_fetch._resolve(r1, self.address('3rdparty/go/r2'), 'r2', implict_ok=False)
    self.assertEqual(cm.exception.address, self.address('3rdparty/go/r2'))

  def test_resolve_and_inject_implicit(self):
    r1 = self.make_target(spec='3rdparty/go/r1', target_type=GoRemoteLibrary)
    go_fetch = self.create_task(self.context())
    r2 = go_fetch._resolve(r1, self.address('3rdparty/go/r2'), 'r2', implict_ok=True)
    self.assertEqual(self.address('3rdparty/go/r2'), r2.address)
    self.assertIsInstance(r2, GoRemoteLibrary)

  def _create_package(self, dirpath, name, deps):
    """Creates a Go package inside dirpath named 'name' importing deps."""
    imports = ['import "localzip/{}"'.format(d) for d in deps]
    f = os.path.join(dirpath, '{name}/{name}.go'.format(name=name))
    self.create_file(f, contents=
      """package {name}
        {imports}
      """.format(name=name, imports='\n'.join(imports)))

  def _create_zip(self, src, dest, name):
    """Zips the Go package in src named 'name' into dest."""
    shutil.make_archive(os.path.join(dest, name), 'zip', root_dir=src)

  def _create_remote_lib(self, name):
    self.make_target(spec='3rdparty/go/localzip/{name}'.format(name=name),
                     target_type=GoRemoteLibrary,
                     pkg=name)

  def _init_dep_graph_files(self, src, zipdir, dep_graph):
    """Given a dependency graph, initializes the corresponding BUILD/packages/zip files.

    Packages are placed in src, and their zipped contents are placed in zipdir.
    """
    for t, deps in dep_graph.items():
      self._create_package(src, t, deps)
      self._create_zip(src, zipdir, t)
      self._create_remote_lib(t)

  def _create_fetch_context(self, zipdir):
    """Given a directory of zipfiles, creates a context for GoFetch."""
    self.set_options_for_scope('fetchers', mapping={r'.*': Fetchers.alias(ArchiveFetcher)})
    matcher = ArchiveFetcher.UrlInfo(url_format=os.path.join(zipdir, '\g<zip>.zip'),
                                     default_rev='HEAD',
                                     strip_level=0)
    self.set_options_for_scope('archive-fetcher', matchers={r'localzip/(?P<zip>[^/]+)': matcher})
    context = self.context()
    context.products.safe_create_data('go_remote_lib_src', lambda: defaultdict(str))
    return context

  def _assert_dependency_graph(self, root_target, dep_map):
    """Recursively assert that the dependency graph starting at root_target matches dep_map."""
    if root_target.name not in dep_map:
      return

    expected_spec_paths = set('3rdparty/go/localzip/{}'.format(name)
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

        dep_graph = {
          'r1': ['r2'],
          'r2': ['r3'],
          'r3': []
        }
        self._init_dep_graph_files(src, zipdir, dep_graph)

        r1 = self.target('3rdparty/go/localzip/r1')
        context = self._create_fetch_context(zipdir)
        go_fetch = self.create_task(context)
        undeclared_deps = go_fetch._transitive_download_remote_libs({r1})
        self.assertEqual(undeclared_deps, {})

        self._assert_dependency_graph(r1, dep_graph)

  def test_transitive_download_remote_libs_complex(self):
    with temporary_dir() as src:
      with temporary_dir() as zipdir:

        dep_graph = {
          'r1': ['r3', 'r4'],
          'r2': ['r3'],
          'r3': ['r4'],
          'r4': []
        }
        self._init_dep_graph_files(src, zipdir, dep_graph)

        r1 = self.target('3rdparty/go/localzip/r1')
        r2 = self.target('3rdparty/go/localzip/r2')

        context = self._create_fetch_context(zipdir)
        go_fetch = self.create_task(context)
        undeclared_deps = go_fetch._transitive_download_remote_libs({r1, r2})
        self.assertEqual(undeclared_deps, {})

        self._assert_dependency_graph(r1, dep_graph)
        self._assert_dependency_graph(r2, dep_graph)

  def test_transitive_download_remote_libs_undeclared_deps(self):
    with temporary_dir() as src:
      with temporary_dir() as zipdir:

        dep_graph = {
          'r1': ['r2', 'r3'],
          'r2': ['r4']
        }
        self._init_dep_graph_files(src, zipdir, dep_graph)

        r1 = self.target('3rdparty/go/localzip/r1')
        r2 = self.target('3rdparty/go/localzip/r2')

        context = self._create_fetch_context(zipdir)
        go_fetch = self.create_task(context)
        undeclared_deps = go_fetch._transitive_download_remote_libs({r1})
        expected = defaultdict(set)
        expected[r1] = {('localzip/r3', self.address('3rdparty/go/localzip/r3'))}
        expected[r2] = {('localzip/r4', self.address('3rdparty/go/localzip/r4'))}
        self.assertEqual(undeclared_deps, expected)

  def test_issues_2616(self):
    go_fetch = self.create_task(self.context())
    self.create_file('src/github.com/u/a/a.go', contents="""
      package a

      import (
        "fmt"
        "math"
        "sync"

        "bitbucket.org/u/b"
      )
    """)
    self.create_file('src/github.com/u/a/b.go', contents="""
      package a

      /*
       #include <stdlib.h>
       */
      import "C" // C was erroneously categorized as a remote lib in issue 2616.

      import (
        "fmt"

        "github.com/u/c"
      )
    """)
    remote_import_ids = go_fetch._get_remote_import_paths('github.com/u/a',
                                                          gopath=self.build_root)
    self.assertItemsEqual(remote_import_ids, ['bitbucket.org/u/b', 'github.com/u/c'])
