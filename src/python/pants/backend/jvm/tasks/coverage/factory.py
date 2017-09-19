# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.coverage.base import BaseCoverage, NoCoverage
from pants.backend.jvm.tasks.coverage.cobertura import Cobertura, CoberturaTaskSettings


class CoverageFactory(object):
  """A factory for creating code coverage classes and registering their options."""

  @staticmethod
  def from_task(task, output_dir, all_targets, execute_java):
    coverage = NoCoverage()

    if task.get_options().coverage or task.get_options().is_flagged('coverage_open'):
      # currently only cobertura is supported, and is ensured by parameter definition
      settings = CoberturaTaskSettings.from_task(task, workdir=output_dir)
      coverage = Cobertura(settings, all_targets, execute_java)

    return coverage

  @staticmethod
  def register_options(register, register_jvm_tool):
    BaseCoverage.register_options(register, register_jvm_tool)
    Cobertura.register_options(register, register_jvm_tool)
