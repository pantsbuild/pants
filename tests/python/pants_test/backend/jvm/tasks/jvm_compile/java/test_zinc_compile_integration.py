# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
from textwrap import dedent
from unittest import skipIf

from pants.base.build_environment import get_buildroot
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_open
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT
from pants_test.backend.jvm.tasks.missing_jvm_check import is_missing_jvm


class ZincCompileIntegrationTest(BaseCompileIT):
  def test_in_process(self):
    with self.temporary_workdir() as workdir:
      with self.temporary_cachedir() as cachedir:
        pants_run = self.run_test_compile(
          workdir, cachedir, 'examples/src/java/org/pantsbuild/example/hello/main',
          extra_args=['-ldebug'], clean_all=True
        )
        self.assertIn('Attempting to call com.sun.tools.javac.api.JavacTool', pants_run.stdout_data)
        self.assertNotIn('Forking javac', pants_run.stdout_data)

  def test_log_level(self):
    with self.temporary_workdir() as workdir:
      with self.temporary_cachedir() as cachedir:
        target = 'testprojects/src/java/org/pantsbuild/testproject/dummies:compilation_failure_target'
        pants_run = self.run_test_compile(
          workdir, cachedir, target,
          extra_args=['--no-colors'], clean_all=True
        )
        self.assert_failure(pants_run)
        self.assertIn('[warn] import sun.security.x509.X500Name;', pants_run.stdout_data)
        self.assertIn('[error]     System2.out.println("Hello World!");', pants_run.stdout_data)

  def test_unicode_source_symbol(self):
    with self.temporary_workdir() as workdir:
      with self.temporary_cachedir() as cachedir:
        target = 'testprojects/src/scala/org/pantsbuild/testproject/unicode/unicodedep/consumer'
        pants_run = self.run_test_compile(
          workdir, cachedir, target,
          extra_args=[
            f'--cache-compile-rsc-write-to=["{cachedir}/dummy_artifact_cache_dir"]',
          ],
          clean_all=True,
        )
        self.assert_success(pants_run)

  def test_fatal_warning(self):
    def test_combination(target, expect_success):
      with self.temporary_workdir() as workdir:
        with self.temporary_cachedir() as cachedir:
          pants_run = self.run_test_compile(
              workdir,
              cachedir,
              f'testprojects/src/java/org/pantsbuild/testproject/compilation_warnings:{target}',
              extra_args=['--compile-rsc-warning-args=-C-Xlint:all'])

          if expect_success:
            self.assert_success(pants_run)
          else:
            self.assert_failure(pants_run)
    test_combination('fatal', expect_success=False)
    test_combination('nonfatal', expect_success=True)

  def test_classpath_does_not_include_extra_classes_dirs(self):
    target_rel_spec = 'testprojects/src/java/org/pantsbuild/testproject/phrases:'
    classpath_file_by_target_id = {}
    for target_name in ['there-was-a-duck',
      'lesser-of-two',
      'once-upon-a-time',
      'ten-thousand']:
      target_id = Target.compute_target_id(Address.parse('{}{}'
        .format(target_rel_spec, target_name)))
      classpath_file_by_target_id[target_id] = f'{target_id}.txt'

    with self.do_test_compile(target_rel_spec,
      expected_files = list(classpath_file_by_target_id.values()),
      extra_args=['--compile-rsc-capture-classpath']) as found:
      for target_id, filename in classpath_file_by_target_id.items():
        found_classpath_file = self.get_only(found, filename)
        with open(found_classpath_file, 'r') as f:
          contents = f.read()

          self.assertIn(target_id, contents)

          other_target_ids = set(classpath_file_by_target_id.keys()) - {target_id}
          for other_id in other_target_ids:
            self.assertNotIn(other_id, contents)

  def test_record_classpath(self):
    target_spec = 'testprojects/src/java/org/pantsbuild/testproject/printversion:printversion'
    target_id = Target.compute_target_id(Address.parse(target_spec))
    classpath_filename = f'{target_id}.txt'
    with self.do_test_compile(target_spec,
                              expected_files=[classpath_filename, 'PrintVersion.class'],
                              extra_args=['--compile-rsc-capture-classpath']) as found:
      found_classpath_file = self.get_only(found, classpath_filename)
      self.assertTrue(found_classpath_file
                      .endswith(os.path.join('compile_classpath', classpath_filename)))
      with open(found_classpath_file, 'r') as f:
        self.assertIn(target_id, f.read())

  def test_no_record_classpath(self):
    target_spec = 'testprojects/src/java/org/pantsbuild/testproject/printversion:printversion'
    target_id = Target.compute_target_id(Address.parse(target_spec))
    classpath_filename = f'{target_id}.txt'
    with self.do_test_compile(target_spec,
                              expected_files=['PrintVersion.class'],
                              extra_args=['--no-compile-rsc-capture-classpath']) as found:
      self.assertFalse(classpath_filename in found)

  @skipIf(is_missing_jvm('1.8'), 'no java 1.8 installation on testing machine')
  def test_custom_javac(self):
    with self.temporary_workdir() as workdir:
      with self.temporary_cachedir() as cachedir:
        pants_run = self.run_test_compile(
            workdir, cachedir, 'examples/src/java/org/pantsbuild/example/hello/main',
            extra_args=['--java-javac=testprojects/3rdparty/javactool:custom_javactool_for_testing'],
            clean_all=True
        )
        self.assertNotEqual(0, pants_run.returncode)  # Our custom javactool always fails.
        self.assertIn('Pants caused Zinc to load a custom JavacTool', pants_run.stdout_data)

  def test_no_zinc_file_manager(self):
    target_spec = 'testprojects/src/java/org/pantsbuild/testproject/bench:jmh'
    with self.temporary_workdir() as workdir:
      with self.temporary_cachedir() as cachedir:
        pants_run = self.run_test_compile(workdir, cachedir, target_spec, clean_all=True)
        self.assertEqual(0, pants_run.returncode)

  def test_hermetic_incremental_compile(self):
    """1) create a target containing two scala files 2) compile the target, which would be a full
    compile 3) modify a scala file slightly 4) recompile, and make sure the compile is incremental
    by checking the zinc outputs."""
    with self.temporary_workdir(cleanup=False) as tmp_build_root:
      # Make sure the tmp build root is recognized by Pants as a build root
      # by touching BUILDROOT.
      with open(os.path.join(tmp_build_root, 'BUILDROOT'), 'w') as f:
        f.write('')

      def _create_file(relpath, contents='', mode='w'):
        """Writes to a file under the buildroot.

        :API: public

        relpath:  The relative path to the file from the build root.
        contents: A string containing the contents of the file - '' by default..
        mode:     The mode to write to the file in - over-write by default.
        """
        path = os.path.join(tmp_build_root, relpath)
        with safe_open(path, mode=mode) as fp:
          fp.write(contents)
        return path

      def _create_a_target_containing_two_sources():
        _srcfile_a = 'org/pantsbuild/incr/A.scala'
        _srcfile_b = 'org/pantsbuild/incr/B.scala'
        _build_file = 'org/pantsbuild/incr/BUILD'
        _lib_spec = 'org/pantsbuild/incr/'
        _create_file(_build_file, 'scala_library()')
        _srcfile_content = dedent("""
                                package org.pantsbuild.cachetest
                                object A {
                                  def x(y: Option[Int] = None) = {
                                    println("hello");
                                  }
                                }
                                """)
        _create_file(_srcfile_a, _srcfile_content)
        _create_file(_srcfile_b, dedent("""
                                      package org.pantsbuild.cachetest
                                      object B extends App {
                                        A.x();
                                        System.exit(0);
                                      }
                                      """))
        return _lib_spec, _srcfile_a, _srcfile_content

      with temporary_dir() as cache_dir, \
        temporary_dir(root_dir=tmp_build_root, suffix='.pants.d') as workdir:
        config = {
          'cache.compile.rsc': {'write_to': [cache_dir]},
          'compile.rsc': {
            'execution_strategy': 'hermetic',
            'use_classpath_jars': True,
            'incremental': True,
          }
        }

        lib_spec, src_file_a, srcfile_content = _create_a_target_containing_two_sources()

        pants_run = self.run_pants_with_workdir(['-ldebug', 'compile', lib_spec],
          workdir=workdir,
          config=config,
          cwd=tmp_build_root
        )
        self.assert_success(pants_run)
        self.assertIn('Full compilation, no sources in previous analysis', pants_run.stdout_data)
        self.assertIn('Compiling 2 Scala sources', pants_run.stdout_data)

        # Modify the source file slightly
        _create_file(src_file_a, srcfile_content.replace('hello', 'bye'))

        pants_run = self.run_pants_with_workdir(['-ldebug', 'compile', lib_spec],
          workdir=workdir,
          config=config,
          cwd=tmp_build_root
        )
        self.assert_success(pants_run)
        self.assertIn('Compiling 1 Scala source', pants_run.stdout_data)

  def test_failed_compile_with_hermetic(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.rsc': {'write_to': [cache_dir]},
        'compile.rsc': {
          'execution_strategy': 'hermetic',
          'use_classpath_jars': False,
          'incremental': False,
        }
      }

      with self.temporary_workdir() as workdir:
        pants_run = self.run_pants_with_workdir(
          [
            '-q',
            'compile',
            'testprojects/src/java/org/pantsbuild/testproject/dummies:compilation_failure_target',
          ],
          workdir,
          config,
        )
        self.assert_failure(pants_run)
        self.assertIn('package System2 does not exist', pants_run.stderr_data)
        self.assertTrue(
          re.search(
            'Compilation failure.*testprojects/src/java/org/pantsbuild/testproject/dummies:compilation_failure_target',
            pants_run.stdout_data
          )
        )

  def test_failed_compile_with_subprocess(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.rsc': {'write_to': [cache_dir]},
        'compile.rsc': {
          'execution_strategy': 'subprocess',
          'use_classpath_jars': False,
          'incremental': False,
        }
      }

      with self.temporary_workdir() as workdir:
        pants_run = self.run_pants_with_workdir(
          [
            # NB: We don't use -q here because subprocess squashes the error output
            # See https://github.com/pantsbuild/pants/issues/5646
            'compile',
            'testprojects/src/java/org/pantsbuild/testproject/dummies:compilation_failure_target',
          ],
          workdir,
          config,
        )
        self.assert_failure(pants_run)
        self.assertIn('package System2 does not exist', pants_run.stdout_data)
        self.assertTrue(
          re.search(
          'Compilation failure.*testprojects/src/java/org/pantsbuild/testproject/dummies:compilation_failure_target',
          pants_run.stdout_data
          )
        )

  def test_hermetic_binary_with_dependencies(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.rsc': {'write_to': [cache_dir]},
        'compile.rsc': {
          'execution_strategy': 'hermetic',
          'use_classpath_jars': False,
          'incremental': False,
        }
      }

      with self.temporary_workdir() as workdir:
        pants_run = self.run_pants_with_workdir(
          [
            '-q',
            'run',
            'examples/src/scala/org/pantsbuild/example/hello/exe',
          ],
          workdir,
          config,
        )
        self.assert_success(pants_run)
        self.assertIn(
          'Num args passed: 0. Stand by for welcome...\nHello, Resource World!',
          pants_run.stdout_data,
        )

        compile_dir = os.path.join(workdir, 'compile', 'rsc', 'current')

        for path_suffix in [
          'examples.src.scala.org.pantsbuild.example.hello.exe.exe/current/zinc/classes/org/pantsbuild/example/hello/exe/Exe.class',
          'examples.src.scala.org.pantsbuild.example.hello.welcome.welcome/current/zinc/classes/org/pantsbuild/example/hello/welcome/WelcomeEverybody.class',
        ]:
          path = os.path.join(compile_dir, path_suffix)
          self.assertTrue(os.path.exists(path), f"Want path {path} to exist")

  def test_hermetic_binary_cache_with_dependencies(self):
    file_abs_path = os.path.join(get_buildroot(),
      'examples/src/scala/org/pantsbuild/example/hello/exe/Exe.scala')

    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.rsc': {'write_to': [cache_dir], 'read_from': [cache_dir]},
        'compile.rsc': {
          'execution_strategy': 'hermetic',
          'use_classpath_jars': False,
          'incremental': False,
        }
      }

      with self.temporary_workdir() as workdir:
        pants_run = self.run_pants_with_workdir(
          [
            '-q',
            'run',
            'examples/src/scala/org/pantsbuild/example/hello/exe',
          ],
          workdir,
          config,
        )
        self.assert_success(pants_run)
        self.assertIn(
          'Num args passed: 0. Stand by for welcome...\nHello, Resource World!',
          pants_run.stdout_data,
        )

        compile_dir = os.path.join(workdir, 'compile', 'rsc', 'current')

        for path_suffix in [
          'examples.src.scala.org.pantsbuild.example.hello.exe.exe/current/zinc/classes/org/pantsbuild/example/hello/exe/Exe.class',
          'examples.src.scala.org.pantsbuild.example.hello.welcome.welcome/current/zinc/classes/org/pantsbuild/example/hello/welcome/WelcomeEverybody.class',
        ]:
          path = os.path.join(compile_dir, path_suffix)
          self.assertTrue(os.path.exists(path), f"Want path {path} to exist")
        with self.with_overwritten_file_content(file_abs_path):

          new_temp_test = '''package org.pantsbuild.example.hello.exe
                              
                              import java.io.{BufferedReader, InputStreamReader}
                              import org.pantsbuild.example.hello
                              import org.pantsbuild.example.hello.welcome
                              
                              // A simple jvm binary to illustrate Scala BUILD targets
                              
                              object Exe {
                                /** Test that resources are properly namespaced. */
                                def getWorld: String = {
                                  val is =
                                    this.getClass.getClassLoader.getResourceAsStream(
                                      "org/pantsbuild/example/hello/world.txt"
                                    )
                                  try {
                                    new BufferedReader(new InputStreamReader(is)).readLine()
                                  } finally {
                                    is.close()
                                  }
                                }
                              
                                def main(args: Array[String]) {
                                  println("Num args passed: " + args.size + ". Stand by for welcome...")
                                  if (args.size <= 0) {
                                    println("Hello, and welcome to " + getWorld + "!")
                                  } else {
                                    val w = welcome.WelcomeEverybody(args)
                                    w.foreach(s => println(s))
                                  }
                                }
                              }'''

          with open(file_abs_path, 'w') as f:
            f.write(new_temp_test)

          pants_run = self.run_pants_with_workdir(
            [
              '-q',
              'run',
              'examples/src/scala/org/pantsbuild/example/hello/exe',
            ],
            workdir,
            config,
          )
          self.assert_success(pants_run)
          self.assertIn(
            'Num args passed: 0. Stand by for welcome...\nHello, and welcome to Resource World!',
            pants_run.stdout_data,
          )

          compile_dir = os.path.join(workdir, 'compile', 'rsc', 'current')

          for path_suffix in [
            'examples.src.scala.org.pantsbuild.example.hello.exe.exe/current/zinc/classes/org/pantsbuild/example/hello/exe/Exe.class',
            'examples.src.scala.org.pantsbuild.example.hello.welcome.welcome/current/zinc/classes/org/pantsbuild/example/hello/welcome/WelcomeEverybody.class',
          ]:
            path = os.path.join(compile_dir, path_suffix)
            self.assertTrue(os.path.exists(path), f"Want path {path} to exist")
