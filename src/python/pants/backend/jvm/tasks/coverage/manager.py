# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.backend.jvm.tasks.coverage.cobertura import Cobertura
from pants.backend.jvm.tasks.coverage.engine import NoCoverage
from pants.backend.jvm.tasks.coverage.jacoco import Jacoco
from pants.subsystem.subsystem import Subsystem
from pants.subsystem.subsystem_client_mixin import SubsystemClientMixin
from pants.util.dirutil import safe_mkdir
from pants.util.strutil import safe_shlex_split


class CodeCoverageSettings(object):
  """A class containing settings for code coverage tasks."""

  def __init__(self, options, context, workdir, tool_classpath, confs, log,
               copy2=shutil.copy2, copytree=shutil.copytree, is_file=os.path.isfile,
               safe_md=safe_mkdir):
    self.options = options
    self.context = context
    self.workdir = workdir
    self.tool_classpath = tool_classpath
    self.confs = confs
    self.log = log

    self.coverage_dir = os.path.join(self.workdir, 'coverage')

    self.coverage_jvm_options = []
    for jvm_option in options.coverage_jvm_options:
      self.coverage_jvm_options.extend(safe_shlex_split(jvm_option))

    self.coverage_open = options.coverage_open
    self.coverage_force = options.coverage_force

    # Injecting these methods to make unit testing cleaner.
    self.copy2 = copy2
    self.copytree = copytree
    self.is_file = is_file
    self.safe_makedir = safe_md

  @classmethod
  def from_task(cls, task, workdir=None):
    return cls(options=task.get_options(),
               context=task.context,
               workdir=workdir or task.workdir,
               tool_classpath=task.tool_classpath,
               confs=task.confs,
               log=task.context.log)


class CodeCoverage(Subsystem, SubsystemClientMixin):
  """Manages setup and construction of JVM code coverage engines.
  """
  options_scope = 'coverage'

  @classmethod
  def subsystem_dependencies(cls):
    return super(CodeCoverage, cls).subsystem_dependencies() + (Cobertura.Factory, Jacoco.Factory)

  # TODO(jtrobec): move these to subsystem scope after deprecating
  @staticmethod
  def register_junit_options(register, register_jvm_tool):
    register('--coverage', type=bool, fingerprint=True, help='Collect code coverage data.')
    register('--coverage-processor', advanced=True, fingerprint=True,
             choices=['cobertura', 'jacoco'], default=None,
             help="Which coverage processor to use if --coverage is enabled. If this option is "
                  "unset but coverage is enabled implicitly or explicitly, defaults to 'cobertura'."
                  "If this option is explicitly set, implies --coverage.")
    # We need to fingerprint this even though it nominally UI-only affecting option since the
    # presence of this option alone can implicitly flag on `--coverage`.
    register('--coverage-open', type=bool, fingerprint=True,
             help='Open the generated HTML coverage report in a browser. Implies --coverage.')

    register('--coverage-jvm-options', advanced=True, type=list, fingerprint=True,
             help='JVM flags to be added when running the coverage processor. For example: '
                  '{flag}=-Xmx4g {flag}=-Xms2g'.format(flag='--coverage-jvm-options'))
    register('--coverage-force', advanced=True, type=bool,
             help='Attempt to run the reporting phase of coverage even if tests failed '
                  '(defaults to False, as otherwise the coverage results would be unreliable).')

    # register options for coverage engines
    # TODO(jtrobec): get rid of this calls when engines are dependent subsystems
    Cobertura.register_junit_options(register, register_jvm_tool)

  class InvalidCoverageEngine(Exception):
    """Indicates an invalid coverage engine type was selected."""

  def get_coverage_engine(self, task, output_dir, all_targets, execute_java):
    options = task.get_options()
    if options.coverage or options.coverage_processor or options.is_flagged('coverage_open'):
      settings = CodeCoverageSettings.from_task(task, workdir=output_dir)
      if options.coverage_processor in ('cobertura', None):
        return Cobertura.Factory.global_instance().create(settings, all_targets, execute_java)
      elif options.coverage_processor == 'jacoco':
        return Jacoco.Factory.global_instance().create(settings, all_targets, execute_java)
      else:
        # NB: We should never get here since the `--coverage-processor` is restricted by `choices`,
        # but for clarity.
        raise self.InvalidCoverageEngine('Unknown and unexpected coverage processor {!r}!'
                                         .format(options.coverage_processor))
    else:
      return NoCoverage()
