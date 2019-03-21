# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import open
from unittest import skipIf

from pants.base.build_environment import get_buildroot
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.util.contextutil import temporary_dir
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT
from pants_test.backend.jvm.tasks.missing_jvm_check import is_missing_jvm


class ZincCompileIntegrationTest(BaseCompileIT):

  def test_java_src_zinc_compile(self):
    with self.do_test_compile('examples/src/java/::'):
      # run succeeded as expected
      pass
    with self.do_test_compile('examples/tests/java/::'):
      # run succeeded as expected
      pass

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
            '--cache-compile-zinc-write-to=["{}/dummy_artifact_cache_dir"]'.format(cachedir),
          ],
          clean_all=True,
        )
        self.assert_success(pants_run)

  def test_apt_compile(self):
    with self.do_test_compile('testprojects/src/java/org/pantsbuild/testproject/annotation/processor',
                              expected_files=['ResourceMappingProcessor.class',
                                              'javax.annotation.processing.Processor']) as found:

      self.assertTrue(
          self.get_only(found, 'ResourceMappingProcessor.class').endswith(
              'org/pantsbuild/testproject/annotation/processor/ResourceMappingProcessor.class'))

      processor_service_files = found['javax.annotation.processing.Processor']
      # There should be only a per-target service info file.
      self.assertEqual(1, len(processor_service_files))
      processor_service_file = list(processor_service_files)[0]
      self.assertTrue(processor_service_file.endswith(
          'META-INF/services/javax.annotation.processing.Processor'))
      with open(processor_service_file, 'r') as fp:
        self.assertEqual('org.pantsbuild.testproject.annotation.processor.ResourceMappingProcessor',
                          fp.read().strip())

  def test_apt_compile_and_run(self):
    with self.do_test_compile('testprojects/src/java/org/pantsbuild/testproject/annotation/main',
                              expected_files=['Main.class',
                                              'deprecation_report.txt']) as found:

      self.assertTrue(
          self.get_only(found, 'Main.class').endswith(
              'org/pantsbuild/testproject/annotation/main/Main.class'))

      # This is the proof that the ResourceMappingProcessor annotation processor was compiled in a
      # round and then the Main was compiled in a later round with the annotation processor and its
      # service info file from on its compile classpath.
      with open(self.get_only(found, 'deprecation_report.txt'), 'r') as fp:
        self.assertIn('org.pantsbuild.testproject.annotation.main.Main', fp.read().splitlines())

  def test_stale_apt_with_deps(self):
    """An annotation processor with a dependency doesn't pollute other annotation processors.

    At one point, when you added an annotation processor, it stayed configured for all subsequent
    compiles.  Meaning that if that annotation processor had a dep that wasn't on the classpath,
    subsequent compiles would fail with missing symbols required by the stale annotation processor.
    """

    # Demonstrate that the annotation processor is working
    with self.do_test_compile(
        'testprojects/src/java/org/pantsbuild/testproject/annotation/processorwithdep/main',
        expected_files=['Main.class', 'Main_HelloWorld.class', 'Main_HelloWorld.java']) as found:
      gen_file = self.get_only(found, 'Main_HelloWorld.java')
      self.assertTrue(gen_file.endswith(
        'org/pantsbuild/testproject/annotation/processorwithdep/main/Main_HelloWorld.java'),
        msg='{} does not match'.format(gen_file))


    # Try to reproduce second compile that fails with missing symbol
    with self.temporary_workdir() as workdir:
      with self.temporary_cachedir() as cachedir:
        # This annotation processor has a unique external dependency
        self.assert_success(self.run_test_compile(
          workdir,
          cachedir,
          'testprojects/src/java/org/pantsbuild/testproject/annotation/processorwithdep::'))

        # When we run a second compile with annotation processors, make sure the previous annotation
        # processor doesn't stick around to spoil the compile
        self.assert_success(self.run_test_compile(
          workdir,
          cachedir,
          'testprojects/src/java/org/pantsbuild/testproject/annotation/processor::',
          clean_all=False))

  def test_fatal_warning(self):
    def test_combination(target, expect_success):
      with self.temporary_workdir() as workdir:
        with self.temporary_cachedir() as cachedir:
          pants_run = self.run_test_compile(
              workdir,
              cachedir,
              'testprojects/src/java/org/pantsbuild/testproject/compilation_warnings:{}'.format(target),
              extra_args=['--compile-zinc-warning-args=-C-Xlint:all'])

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
      classpath_file_by_target_id[target_id] = '{}.txt'.format(target_id)

    with self.do_test_compile(target_rel_spec,
      expected_files = list(classpath_file_by_target_id.values()),
      extra_args=['--compile-zinc-capture-classpath']) as found:
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
    classpath_filename = '{}.txt'.format(target_id)
    with self.do_test_compile(target_spec,
                              expected_files=[classpath_filename, 'PrintVersion.class'],
                              extra_args=['--compile-zinc-capture-classpath']) as found:
      found_classpath_file = self.get_only(found, classpath_filename)
      self.assertTrue(found_classpath_file
                      .endswith(os.path.join('compile_classpath', classpath_filename)))
      with open(found_classpath_file, 'r') as f:
        self.assertIn(target_id, f.read())

  def test_no_record_classpath(self):
    target_spec = 'testprojects/src/java/org/pantsbuild/testproject/printversion:printversion'
    target_id = Target.compute_target_id(Address.parse(target_spec))
    classpath_filename = '{}.txt'.format(target_id)
    with self.do_test_compile(target_spec,
                              expected_files=['PrintVersion.class'],
                              extra_args=['--no-compile-zinc-capture-classpath']) as found:
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

  def test_failed_hermetic_incremental_compile(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.zinc': {'write_to': [cache_dir]},
        'compile.zinc': {
          'execution_strategy': 'hermetic',
          'use_classpath_jars': False,
          'incremental': True,
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
        self.assert_failure(pants_run)
        self.assertIn('Please use --no-compile-zinc-incremental', pants_run.stdout_data)

  def test_failed_compile_with_hermetic(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.zinc': {'write_to': [cache_dir]},
        'compile.zinc': {
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
        self.assertIn(
          'Failed jobs: compile(testprojects/src/java/org/pantsbuild/testproject/dummies:'
          'compilation_failure_target)',
          pants_run.stdout_data)

  def test_failed_compile_with_subprocess(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.zinc': {'write_to': [cache_dir]},
        'compile.zinc': {
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
        self.assertIn(
          'Failed jobs: compile(testprojects/src/java/org/pantsbuild/testproject/dummies:'
          'compilation_failure_target)',
          pants_run.stdout_data)

  def test_hermetic_binary_with_dependencies(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.zinc': {'write_to': [cache_dir]},
        'compile.zinc': {
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

        compile_dir = os.path.join(workdir, 'compile', 'zinc', 'current')

        for path_suffix in [
          'examples.src.scala.org.pantsbuild.example.hello.exe.exe/current/classes/org/pantsbuild/example/hello/exe/Exe.class',
          'examples.src.scala.org.pantsbuild.example.hello.welcome.welcome/current/classes/org/pantsbuild/example/hello/welcome/WelcomeEverybody.class',
        ]:
          path = os.path.join(compile_dir, path_suffix)
          self.assertTrue(os.path.exists(path), "Want path {} to exist".format(path))

  def test_hermetic_binary_cache_with_dependencies(self):
    file_abs_path = os.path.join(get_buildroot(),
      'examples/src/scala/org/pantsbuild/example/hello/exe/Exe.scala')

    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.zinc': {'write_to': [cache_dir]},
        'compile.zinc': {
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

        compile_dir = os.path.join(workdir, 'compile', 'zinc', 'current')

        for path_suffix in [
          'examples.src.scala.org.pantsbuild.example.hello.exe.exe/current/classes/org/pantsbuild/example/hello/exe/Exe.class',
          'examples.src.scala.org.pantsbuild.example.hello.welcome.welcome/current/classes/org/pantsbuild/example/hello/welcome/WelcomeEverybody.class',
        ]:
          path = os.path.join(compile_dir, path_suffix)
          self.assertTrue(os.path.exists(path), "Want path {} to exist".format(path))

        with self.with_overwritten_file_content(file_abs_path):

          new_temp_test = '''package org.pantsbuild.example.hello.exe
                              
                              import java.io.{BufferedReader, InputStreamReader}
                              
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

          compile_dir = os.path.join(workdir, 'compile', 'zinc', 'current')

          for path_suffix in [
            'examples.src.scala.org.pantsbuild.example.hello.exe.exe/current/classes/org/pantsbuild/example/hello/exe/Exe.class',
            'examples.src.scala.org.pantsbuild.example.hello.welcome.welcome/current/classes/org/pantsbuild/example/hello/welcome/WelcomeEverybody.class',
          ]:
            path = os.path.join(compile_dir, path_suffix)
            self.assertTrue(os.path.exists(path), "Want path {} to exist".format(path))

  def test_hermetic_binary_with_capturing_off(self):
    capture_snapshots = False
    config = {
      'resolve.ivy': {'capture_snapshots': capture_snapshots},
      'resolve.coursier': {'capture_snapshots': capture_snapshots},
      'compile.zinc': {
        'execution_strategy': 'hermetic',
        'use_classpath_jars': False,
        'incremental': False,
      },
    }
    with self.temporary_workdir() as workdir:
      with self.temporary_file_content("readme.txt", b"yo"):
        pants_run = self.run_pants_with_workdir(
          [
            'run',
            'testprojects/src/java/org/pantsbuild/testproject/cwdexample',
          ],
          workdir,
          config,
        )
        self.assert_failure(pants_run)

  def test_hermetic_binary_with_3rdparty_dependencies_ivy(self):
    config = {
      'resolve.ivy': {'capture_snapshots': True},
      'compile.zinc': {
        'execution_strategy': 'hermetic',
        'use_classpath_jars': False,
        'incremental': False,
      },
      'resolver': {
        'resolver': 'ivy',
      }
    }

    with self.temporary_workdir() as workdir:
      with self.temporary_file_content("readme.txt", b"yo"):
        pants_run = self.run_pants_with_workdir(
          [
            'run',
            'testprojects/src/java/org/pantsbuild/testproject/cwdexample',
          ],
          workdir,
          config,
        )
        self.assert_success(pants_run)
        self.assertIn(
          'Found readme.txt',
          pants_run.stdout_data,
        )

  def test_hermetic_binary_with_3rdparty_dependencies_coursier(self):
    config = {
      'resolve.coursier': {'capture_snapshots': True},
      'compile.zinc': {
        'execution_strategy': 'hermetic',
        'use_classpath_jars': False,
        'incremental': False,
      },
      'resolver': {
        'resolver': 'coursier',
      }
    }

    with self.temporary_workdir() as workdir:
      with self.temporary_file_content("readme.txt", b"yo"):
        pants_run = self.run_pants_with_workdir(
          [
            'run',
            'testprojects/src/java/org/pantsbuild/testproject/cwdexample',
          ],
          workdir,
          config,
        )
        self.assert_success(pants_run)
        self.assertIn(
          'Found readme.txt',
          pants_run.stdout_data,
        )
