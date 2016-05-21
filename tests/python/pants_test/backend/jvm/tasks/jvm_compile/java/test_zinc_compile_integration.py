# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


class ZincCompileIntegrationTest(BaseCompileIT):

  def test_java_src_zinc_compile(self):
    # TODO: Remove the --exclude-target-regexp once we're on Java 8 everywhere.
    with self.do_test_compile('examples/src/java/::',
                              extra_args=['--exclude-target-regexp=examples/src/java/org/pantsbuild/example/plugin']):
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
        self.assertIn('[warn] import sun.security.x509.X500Name;', pants_run.stdout_data)
        self.assertIn('[error]     System2.out.println("Hello World!");', pants_run.stdout_data)

  def test_unicode_source_symbol(self):
    with self.temporary_workdir() as workdir:
      with self.temporary_cachedir() as cachedir:
        target = 'testprojects/src/scala/org/pantsbuild/testproject/unicode/unicodedep/consumer'
        pants_run = self.run_test_compile(
          workdir, cachedir, target,
          extra_args=[
            '--compile-zinc-name-hashing',
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
      with open(processor_service_file) as fp:
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
      with open(self.get_only(found, 'deprecation_report.txt')) as fp:
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
    def test_combination(target, default_fatal_warnings, expect_success):
      with self.temporary_workdir() as workdir:
        with self.temporary_cachedir() as cachedir:
          if default_fatal_warnings:
            arg = '--java-fatal-warnings'
          else:
            arg = '--no-java-fatal-warnings'
          pants_run = self.run_test_compile(
              workdir,
              cachedir,
              'testprojects/src/java/org/pantsbuild/testproject/compilation_warnings:{}'.format(target),
              extra_args=[arg, '--compile-zinc-warning-args=-C-Xlint:all'])

          if expect_success:
            self.assert_success(pants_run)
          else:
            self.assert_failure(pants_run)
    test_combination('defaultfatal', default_fatal_warnings=True, expect_success=False)
    test_combination('defaultfatal', default_fatal_warnings=False, expect_success=True)
    test_combination('fatal', default_fatal_warnings=True, expect_success=False)
    test_combination('fatal', default_fatal_warnings=False, expect_success=False)
    test_combination('nonfatal', default_fatal_warnings=True, expect_success=True)
    test_combination('nonfatal', default_fatal_warnings=False, expect_success=True)

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
