# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.build_graph.target import Target
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
    self.create_dir('src/go')
    self.create_dir('src/main/go')
    context = self.context(target_roots=[self.make_target('src/go/fred', GoBinary)])
    task = self.create_task(context)
    with self.assertRaises(task.InvalidLocalRootsError):
      task.execute()

  def test_unrooted_failure(self):
    self.create_dir('src/go')
    context = self.context(target_roots=[self.make_target('src2/go/fred', GoBinary)])
    task = self.create_task(context)
    with self.assertRaises(task.UnrootedLocalSourceError):
      task.execute()

  def test_multiple_remote_roots_failure(self):
    self.create_dir('3rdparty/go')
    self.create_dir('src/go')
    self.create_dir('src/go_remote')
    context = self.context(target_roots=[self.make_target('src/go/fred', GoLibrary)])
    task = self.create_task(context)
    with self.assertRaises(task.InvalidRemoteRootsError):
      task.execute()

  def test_existing_targets_wrong_type(self):
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

  def stitch_deps_local(self, materialize):
    self.set_options(materialize=materialize)

    if materialize:
      # We need physical directories on disk for `--materialize` since it does scans.
      self.create_dir('src/go')

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
    if materialize:
      # We need physical BUILD files on disk for `--materialize` since it does scans.
      self.add_to_build_file('src/go/fred', 'go_binary()')
      fred = self.target('src/go/fred')
      target_roots = None
    else:
      fred = self.make_target('src/go/fred', GoBinary)
      target_roots = [fred]

    context = self.context(target_roots=target_roots)
    pre_execute_files = self.buildroot_files()
    task = self.create_task(context)
    task.execute()

    jane = self.target('src/go/jane')
    self.assertIsNotNone(jane)
    self.assertEqual([jane], fred.dependencies)
    self.assertEqual({jane, fred}, set(self.build_graph.targets()))

    return pre_execute_files

  def test_stitch_deps(self):
    pre_execute_files = self.stitch_deps_local(materialize=False)
    self.assertEqual(pre_execute_files, self.buildroot_files())

  def test_stitch_deps_generate_builds(self):
    pre_execute_files = self.stitch_deps_local(materialize=True)
    self.assertEqual({'src/go/jane/BUILD'}, self.buildroot_files() - pre_execute_files)

  def test_stitch_deps_generate_builds_custom_extension(self):
    self.set_options(extension='.gen')
    pre_execute_files = self.stitch_deps_local(materialize=True)
    # NB: The src/go/fred/BUILD file on disk was deleted and replaced with src/go/fred/BUILD.gen.
    self.assertEqual({'src/go/fred/BUILD.gen', 'src/go/jane/BUILD.gen'},
                     self.buildroot_files() - pre_execute_files)

  def stitch_deps_remote(self, remote=True, materialize=False, fail_floating=False):
    self.set_options(remote=remote, materialize=materialize, fail_floating=fail_floating)
    self.set_options_for_scope(Fetchers.options_scope,
                               mapping={r'pantsbuild.org/.*':
                                        '{}.{}'.format(FakeFetcher.__module__,
                                                       FakeFetcher.__name__)})

    if materialize:
      # We need physical directories on disk for `--materialize` since it does scans.
      self.create_dir('3rdparty/go')
      self.create_dir('src/go')

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
    if materialize:
      # We need physical BUILD files on disk for `--materialize` since it does a scan.
      self.add_to_build_file('src/go/fred', 'go_binary()')
      fred = self.target('src/go/fred')
      target_roots = None
    else:
      fred = self.make_target('src/go/fred', GoBinary)
      target_roots = [fred]

    context = self.context(target_roots=target_roots)
    pre_execute_files = self.buildroot_files()
    task = self.create_task(context)
    task.execute()

    jane = self.target('src/go/jane')
    self.assertIsNotNone(jane)
    self.assertEqual([jane], fred.dependencies)

    prod = self.target('3rdparty/go/pantsbuild.org/fake:prod')
    self.assertIsNotNone(prod)
    self.assertEqual([prod], jane.dependencies)

    self.assertEqual({prod, jane, fred}, set(self.build_graph.targets()))

    return pre_execute_files

  def test_stitch_deps_remote(self):
    self.create_dir('3rdparty/go')
    pre_execute_files = self.stitch_deps_remote(materialize=False)
    self.assertEqual(pre_execute_files, self.buildroot_files())

  def test_stitch_deps_remote_unused(self):
    # An unused remote lib
    self.add_to_build_file('3rdparty/go/github.com/user/repo', 'go_remote_library()')

    pre_execute_files = self.stitch_deps_remote(materialize=False)

    # Check the unused remote lib was not deleted since we can't know if it was actually unused or
    # a transitive dep of a used remote_lib.
    self.assertIn('3rdparty/go/github.com/user/repo/BUILD', self.buildroot_files())
    self.assertEqual(pre_execute_files, self.buildroot_files())

  def test_stitch_deps_remote_existing_rev_respected(self):
    self.make_target('3rdparty/go/pantsbuild.org/fake:prod',
                     GoRemoteLibrary,
                     pkg='prod',
                     rev='v1.2.3')
    pre_execute_files = self.stitch_deps_remote(materialize=True)
    self.build_graph.reset()  # Force targets to be loaded off disk
    self.assertEqual('v1.2.3', self.target('3rdparty/go/pantsbuild.org/fake:prod').rev)
    self.assertEqual({'src/go/jane/BUILD', '3rdparty/go/pantsbuild.org/fake/BUILD'},
                     self.buildroot_files() - pre_execute_files)

  def test_stitch_deps_remote_generate_builds(self):
    pre_execute_files = self.stitch_deps_remote(materialize=True)
    self.assertEqual({'src/go/jane/BUILD', '3rdparty/go/pantsbuild.org/fake/BUILD'},
                     self.buildroot_files() - pre_execute_files)

  def test_stitch_deps_remote_disabled_fails(self):
    self.create_dir('3rdparty/go')
    with self.assertRaises(GoBuildgen.GenerationError) as exc:
      self.stitch_deps_remote(remote=False)
    self.assertEqual(GoTargetGenerator.NewRemoteEncounteredButRemotesNotAllowedError,
                     type(exc.exception.cause))

  def test_fail_floating(self):
    with self.assertRaises(GoBuildgen.FloatingRemoteError):
      self.stitch_deps_remote(remote=True, materialize=True, fail_floating=True)

  def test_issues_2395(self):
    # Previously, when a remote was indirectly discovered via a scan of locals (no target roots
    # presented on the CLI), the remote would be queried for from the build graph under the
    # erroneous assumption it had been injected.  This would result in a graph miss (BUILD file was
    # there on disk, but never loaded via injection) and lead to creation of a new synthetic remote
    # target with no rev.  The end result was lossy go remote library rev values when using the
    # newer, encouraged, target-less invocation of GoBuildgen.

    self.set_options(remote=True, materialize=True, fail_floating=True)
    self.set_options_for_scope(Fetchers.options_scope,
                               mapping={r'pantsbuild.org/.*':
                                          '{}.{}'.format(FakeFetcher.__module__,
                                                         FakeFetcher.__name__)})

    self.add_to_build_file(relpath='3rdparty/go/pantsbuild.org/fake',
                           target='go_remote_library(rev="v4.5.6")')

    self.create_file(relpath='src/go/jane/bar.go', contents=dedent("""
        package jane

        import "pantsbuild.org/fake"

        var PublicConstant = fake.DoesNotExistButWeShouldNotCareWhenCheckingDepsAndNotInstalling
      """))
    self.add_to_build_file(relpath='src/go/jane', target='go_library()')

    context = self.context(target_roots=[])
    pre_execute_files = self.buildroot_files()
    task = self.create_task(context)
    task.execute()

    self.build_graph.reset()  # Force targets to be loaded off disk
    self.assertEqual('v4.5.6', self.target('3rdparty/go/pantsbuild.org/fake').rev)
    self.assertEqual(pre_execute_files, self.buildroot_files())

  def test_issues_2616(self):
    self.set_options(remote=False)

    self.create_file(relpath='src/go/jane/bar.go', contents=dedent("""
        package jane

        var PublicConstant = 42
      """))
    self.create_file(relpath='src/go/fred/foo.go', contents=dedent("""
        package main

        /*
        #include <stdlib.h>
        */
        import "C" // C was erroneously categorized as a remote lib in issue 2616.

        import (
          "fmt"
          "jane"
        )

        func main() {
          fmt.Printf("Hello %s!", jane.PublicConstant)
          fmt.Printf("Random from C: %d", int(C.random()))
        }
      """))
    fred = self.make_target('src/go/fred', GoBinary)
    context = self.context(target_roots=[fred])
    task = self.create_task(context)
    task.execute()

    jane = self.target('src/go/jane')
    self.assertIsNotNone(jane)
    self.assertEqual([jane], fred.dependencies)
    self.assertEqual({jane, fred}, set(self.build_graph.targets()))
