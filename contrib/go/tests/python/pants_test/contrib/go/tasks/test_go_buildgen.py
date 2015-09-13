# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.base.source_root import SourceRoot
from pants.base.target import Target
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.go import register
from pants.contrib.go.subsystems.fetchers import Fetcher, Fetchers
from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.targets.go_library import GoLibrary
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.tasks.go_buildgen import GoBuildgen, GoTargetGenerator


class FakeFetcher(Fetcher):
  def root(self, import_path):
    return 'pantsbuild.org/fake'

  def fetch(self, import_path, dest, rev=None):
    raise AssertionError('No fetches should be executed during go.buildgen')


class GoBuildgenTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return GoBuildgen

  @property
  def alias_groups(self):
    # Needed for test_stitch_deps_remote_existing_rev_respected which re-loads a synthetic target
    # from a generated BUILD file on disk that needs access to Go target aliases
    return register.build_file_aliases()

  def test_noop_no_targets(self):
    context = self.context()
    task = self.create_task(context)
    task.execute()
    self.assertEqual([], context.targets())

  def test_noop_no_applicable_targets(self):
    context = self.context(target_roots=[self.make_target(':a', Target)])
    expected = context.targets()
    task = self.create_task(context)
    task.execute()
    self.assertEqual(expected, context.targets())

  def test_no_local_roots_failure(self):
    context = self.context(target_roots=[self.make_target('src/go/fred', GoBinary)])
    task = self.create_task(context)
    with self.assertRaises(task.NoLocalRootsError):
      task.execute()

  def test_multiple_local_roots_failure(self):
    SourceRoot.register('src/go', GoBinary)
    SourceRoot.register('src2/go', GoLibrary)
    context = self.context(target_roots=[self.make_target('src/go/fred', GoBinary)])
    task = self.create_task(context)
    with self.assertRaises(task.InvalidLocalRootsError):
      task.execute()

  def test_unrooted_failure(self):
    SourceRoot.register('src/go', GoBinary)
    context = self.context(target_roots=[self.make_target('src2/go/fred', GoBinary)])
    task = self.create_task(context)
    with self.assertRaises(task.UnrootedLocalSourceError):
      task.execute()

  def test_multiple_remote_roots_failure(self):
    SourceRoot.register('3rdparty/go', GoRemoteLibrary)
    SourceRoot.register('src/go', GoLibrary, GoRemoteLibrary)
    context = self.context(target_roots=[self.make_target('src/go/fred', GoLibrary)])
    task = self.create_task(context)
    with self.assertRaises(task.InvalidRemoteRootsError):
      task.execute()

  def test_existing_targets_wrong_type(self):
    SourceRoot.register('src/go', GoBinary, GoLibrary)
    self.create_file(relpath='src/go/fred/foo.go', contents=dedent("""
      package main

      import "fmt"

      func main() {
              fmt.Printf("Hello World!")
      }
    """))
    context = self.context(target_roots=[self.make_target('src/go/fred', GoLibrary)])
    task = self.create_task(context)
    with self.assertRaises(task.GenerationError) as exc:
      task.execute()
    self.assertEqual(GoTargetGenerator.WrongLocalSourceTargetTypeError, type(exc.exception.cause))

  def test_noop_applicable_targets_simple(self):
    SourceRoot.register('src/go', GoBinary)
    self.create_file(relpath='src/go/fred/foo.go', contents=dedent("""
      package main

      import "fmt"

      func main() {
              fmt.Printf("Hello World!")
      }
    """))
    context = self.context(target_roots=[self.make_target('src/go/fred', GoBinary)])
    expected = context.targets()
    task = self.create_task(context)
    task.execute()
    self.assertEqual(expected, context.targets())

  def test_noop_applicable_targets_complete_graph(self):
    SourceRoot.register('src/go', GoBinary, GoLibrary)
    self.create_file(relpath='src/go/jane/bar.go', contents=dedent("""
      package jane

      var PublicConstant = 42
    """))
    jane = self.make_target('src/go/jane', GoLibrary)
    self.create_file(relpath='src/go/fred/foo.go', contents=dedent("""
      package main

      import (
        "fmt"
        "jane"
      )

      func main() {
              fmt.Printf("Hello %s!", jane.PublicConstant)
      }
    """))
    fred = self.make_target('src/go/fred', GoBinary, dependencies=[jane])
    context = self.context(target_roots=[fred])
    expected = context.targets()
    task = self.create_task(context)
    task.execute()
    self.assertEqual(expected, context.targets())

  def stitch_deps_local(self):
    SourceRoot.register('src/go', GoBinary, GoLibrary)
    self.create_file(relpath='src/go/jane/bar.go', contents=dedent("""
        package jane

        var PublicConstant = 42
      """))
    self.create_file(relpath='src/go/fred/foo.go', contents=dedent("""
        package main

        import (
          "fmt"
          "jane"
        )

        func main() {
                fmt.Printf("Hello %s!", jane.PublicConstant)
        }
      """))
    fred = self.make_target('src/go/fred', GoBinary)
    context = self.context(target_roots=[fred])
    self.assertEqual([fred], context.target_roots)
    pre_execute_files = self.buildroot_files()
    task = self.create_task(context)
    task.execute()

    jane = self.target('src/go/jane')
    self.assertIsNotNone(jane)
    self.assertEqual([jane], fred.dependencies)
    self.assertEqual({jane, fred}, set(context.targets()))

    return pre_execute_files

  def test_stitch_deps(self):
    self.set_options(materialize=False)
    pre_execute_files = self.stitch_deps_local()
    self.assertEqual(pre_execute_files, self.buildroot_files())

  def test_stitch_deps_generate_builds(self):
    self.set_options(materialize=True)
    pre_execute_files = self.stitch_deps_local()
    self.assertEqual({'src/go/fred/BUILD', 'src/go/jane/BUILD'},
                     self.buildroot_files() - pre_execute_files)

  def test_stitch_deps_generate_builds_custom_extension(self):
    self.set_options(materialize=True, extension='.gen')
    pre_execute_files = self.stitch_deps_local()
    self.assertEqual({'src/go/fred/BUILD.gen', 'src/go/jane/BUILD.gen'},
                     self.buildroot_files() - pre_execute_files)

  def stitch_deps_remote(self):
    self.set_options_for_scope(Fetchers.options_scope,
                               mapping={r'pantsbuild.org/.*':
                                        '{}.{}'.format(FakeFetcher.__module__,
                                                       FakeFetcher.__name__)})

    SourceRoot.register('3rdparty/go', GoRemoteLibrary)
    SourceRoot.register('src/go', GoBinary, GoLibrary)
    self.create_file(relpath='src/go/jane/bar.go', contents=dedent("""
        package jane

        import "pantsbuild.org/fake/prod"

        var PublicConstant = prod.DoesNotExistButWeShouldNotCareWhenCheckingDepsAndNotInstalling
      """))
    self.create_file(relpath='src/go/fred/foo.go', contents=dedent("""
        package main

        import (
          "fmt"
          "jane"
        )

        func main() {
                fmt.Printf("Hello %s!", jane.PublicConstant)
        }
      """))
    fred = self.make_target('src/go/fred', GoBinary)
    context = self.context(target_roots=[fred])
    self.assertEqual([fred], context.target_roots)
    pre_execute_files = self.buildroot_files()
    task = self.create_task(context)
    task.execute()

    jane = self.target('src/go/jane')
    self.assertIsNotNone(jane)
    self.assertEqual([jane], fred.dependencies)

    prod = self.target('3rdparty/go/pantsbuild.org/fake:prod')
    self.assertIsNotNone(prod)
    self.assertEqual([prod], jane.dependencies)

    self.assertEqual({prod, jane, fred}, set(context.targets()))

    return pre_execute_files

  def test_stitch_deps_remote(self):
    self.set_options(remote=True, materialize=False)
    pre_execute_files = self.stitch_deps_remote()
    self.assertEqual(pre_execute_files, self.buildroot_files())

  def test_stitch_deps_remote_existing_rev_respected(self):
    self.set_options(remote=True, materialize=True)
    self.make_target('3rdparty/go/pantsbuild.org/fake:prod',
                     GoRemoteLibrary,
                     pkg='prod',
                     rev='v1.2.3')
    pre_execute_files = self.stitch_deps_remote()
    self.build_graph.reset()  # Force targets to be loaded off disk
    self.assertEqual('v1.2.3', self.target('3rdparty/go/pantsbuild.org/fake:prod').rev)
    self.assertEqual({'src/go/fred/BUILD',
                      'src/go/jane/BUILD',
                      '3rdparty/go/pantsbuild.org/fake/BUILD'},
                     self.buildroot_files() - pre_execute_files)

  def test_stitch_deps_remote_generate_builds(self):
    self.set_options(remote=True, materialize=True)
    pre_execute_files = self.stitch_deps_remote()
    self.assertEqual({'src/go/fred/BUILD',
                      'src/go/jane/BUILD',
                      '3rdparty/go/pantsbuild.org/fake/BUILD'},
                     self.buildroot_files() - pre_execute_files)

  def test_stitch_deps_remote_disabled_fails(self):
    with self.assertRaises(GoBuildgen.GenerationError) as exc:
      self.stitch_deps_remote()
    self.assertEqual(GoTargetGenerator.NewRemoteEncounteredButRemotesNotAllowedError,
                     type(exc.exception.cause))
