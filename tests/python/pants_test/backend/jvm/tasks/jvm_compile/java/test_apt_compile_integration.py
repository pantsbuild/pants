# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


class AptCompileIntegrationTest(BaseCompileIT):
  def test_apt_compile(self):
    with self.do_test_compile('testprojects/src/java/com/pants/testproject/annotation/processor',
                              expected_files=['ResourceMappingProcessor.class',
                                              'javax.annotation.processing.Processor']) as found:

      self.assertTrue(
          self.get_only(found, 'ResourceMappingProcessor.class').endswith(
              'com/pants/testproject/annotation/processor/ResourceMappingProcessor.class'))

      processor_service_files = found['javax.annotation.processing.Processor']
      # There should be both a per-target service info file and a global file.
      self.assertEqual(2, len(processor_service_files))
      for processor_service_file in processor_service_files:
        self.assertTrue(processor_service_file.endswith(
            'META-INF/services/javax.annotation.processing.Processor'))
        with open(processor_service_file) as fp:
          self.assertEqual('com.pants.testproject.annotation.processor.ResourceMappingProcessor',
                           fp.read().strip())

  def test_apt_compile_and_run(self):
    with self.do_test_compile('testprojects/src/java/com/pants/testproject/annotation/main',
                              expected_files=['Main.class',
                                              'deprecation_report.txt']) as found:

      self.assertTrue(
          self.get_only(found, 'Main.class').endswith(
              'com/pants/testproject/annotation/main/Main.class'))

      # This is the proof that the ResourceMappingProcessor annotation processor was compiled in a
      # round and then the Main was compiled in a later round with the annotation processor and its
      # service info file from on its compile classpath.
      with open(self.get_only(found, 'deprecation_report.txt')) as fp:
        self.assertIn('com.pants.testproject.annotation.main.Main', fp.read().splitlines())
