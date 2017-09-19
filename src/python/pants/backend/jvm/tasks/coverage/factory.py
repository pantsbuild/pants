# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.coverage.base import BaseCoverage, NoCoverage
from pants.backend.jvm.tasks.coverage.cobertura import Cobertura, CoberturaTaskSettings
from pants.backend.jvm.tasks.coverage.jacoco import Jacoco, JacocoTaskSettings


class CoverageFactory(object):
  """A factory for creating code coverage classes and registering their options."""

  @staticmethod
  def from_task(task, output_dir, all_targets, execute_java):
    coverage = NoCoverage()
    options = task.get_options()

    if options.coverage or options.coverage_processor or options.is_flagged('coverage_open'):
      if options.coverage_processor == 'cobertura':
        settings = CoberturaTaskSettings.from_task(task, workdir=output_dir)
        coverage = Cobertura(settings, all_targets, execute_java)
    elif options.coverage-processor == 'jacoco':
        settings = JacocoTaskSettings.from_task(task, workdir=output_dir)
        coverage = Jacoco(settings, all_targets, execute_java)

    return coverage

  @staticmethod
  def register_options(register, register_jvm_tool):
    BaseCoverage.register_generic_coverage_options(register, register_jvm_tool)
    Cobertura.register_options(register, register_jvm_tool)
    Jacoco.register_options(register, register_jvm_tool)
