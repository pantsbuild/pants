# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT
from pants_test.backend.jvm.tasks.jvm_compile.utils import provide_compile_strategies


class AptCompileIntegrationTest(BaseCompileIT):
  @provide_compile_strategies
  def test_apt_compile(self, strategy):
    with self.do_test_compile('testprojects/src/java/org/pantsbuild/testproject/annotation/processor',
                              strategy,
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

  @provide_compile_strategies
  def test_apt_compile_and_run(self, strategy):
    with self.do_test_compile('testprojects/src/java/org/pantsbuild/testproject/annotation/main',
                              strategy,
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
