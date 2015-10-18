# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.contextutil import temporary_dir
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


class ZincCompileIntegrationTest(BaseCompileIT):

  def test_java_src_zinc_compile(self):
    with self.do_test_compile('examples/src/java/::'):
      # run succeeded as expected
      pass
    with self.do_test_compile('examples/tests/java/::'):
      # run succeeded as expected
      pass

  def test_in_process(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      with temporary_dir(root_dir=self.workdir_root()) as cachedir:
        pants_run = self.run_test_compile(
          workdir, cachedir, 'examples/src/java/org/pantsbuild/example/hello/main',
          extra_args=['-ldebug'], clean_all=True
        )
        self.assertIn('Attempting to call com.sun.tools.javac.api.JavacTool', pants_run.stdout_data)
        self.assertNotIn('Forking javac', pants_run.stdout_data)

  def test_log_level(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      with temporary_dir(root_dir=self.workdir_root()) as cachedir:
        target = 'testprojects/src/java/org/pantsbuild/testproject/dummies:compilation_failure_target'
        pants_run = self.run_test_compile(
          workdir, cachedir, target,
          extra_args=['--no-color'], clean_all=True
        )
        self.assertIn('[warn] import sun.security.x509.X500Name;', pants_run.stdout_data)
        self.assertIn('[error]     System2.out.println("Hello World!");', pants_run.stdout_data)

  def test_unicode_source_symbol(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      with temporary_dir(root_dir=self.workdir_root()) as cachedir:
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
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      with temporary_dir(root_dir=self.workdir_root()) as cachedir:
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
