# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from zipfile import ZIP_STORED

from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.java.executor import Executor, SubprocessExecutor
from pants.java.jar.manifest import Manifest
from pants.java.nailgun_executor import NailgunExecutor
from pants.util.contextutil import open_zip, temporary_file
from pants.util.dirutil import safe_mkdir, safe_mkdtemp


logger = logging.getLogger(__name__)


def execute_java(classpath, main, jvm_options=None, args=None, executor=None,
                 workunit_factory=None, workunit_name=None, workunit_labels=None,
                 cwd=None, workunit_log_config=None, distribution=None,
                 create_synthetic_jar=True, synthetic_jar_dir=None):
  """Executes the java program defined by the classpath and main.

  If `workunit_factory` is supplied, does so in the context of a workunit.

  :param list classpath: the classpath for the java program
  :param string main: the fully qualified class name of the java program's entry point
  :param list jvm_options: an optional sequence of options for the underlying jvm
  :param list args: an optional sequence of args to pass to the java program
  :param executor: an optional java executor to use to launch the program; defaults to a subprocess
    spawn of the default java distribution
  :param workunit_factory: an optional callable that can produce a workunit context
  :param string workunit_name: an optional name for the work unit; defaults to the main
  :param list workunit_labels: an optional sequence of labels for the work unit
  :param string cwd: optionally set the working directory
  :param WorkUnit.LogConfig workunit_log_config: an optional tuple of options affecting reporting
  :param bool create_synthetic_jar: whether to create a synthentic jar that includes the original
    classpath in its manifest.
  :param string synthetic_jar_dir: an optional directory to store the synthetic jar, if `None`
    a temporary directory will be provided and cleaned up upon process exit.

  Returns the exit code of the java program.
  Raises `pants.java.Executor.Error` if there was a problem launching java itself.
  """
  executor = executor or SubprocessExecutor(distribution)
  if not isinstance(executor, Executor):
    raise ValueError('The executor argument must be a java Executor instance, give {} of type {}'
                     .format(executor, type(executor)))

  workunit_name = workunit_name or main

  safe_cp = classpath
  if create_synthetic_jar:
    safe_cp = safe_classpath(classpath, synthetic_jar_dir)
    logger.debug('Bundling classpath {} into {}'.format(':'.join(classpath), safe_cp))

  runner = executor.runner(safe_cp, main, args=args, jvm_options=jvm_options, cwd=cwd)
  return execute_runner(runner,
                        workunit_factory=workunit_factory,
                        workunit_name=workunit_name,
                        workunit_labels=workunit_labels,
                        cwd=cwd,
                        workunit_log_config=workunit_log_config)


def execute_runner(runner, workunit_factory=None, workunit_name=None, workunit_labels=None,
                   cwd=None, workunit_log_config=None):
  """Executes the given java runner.

  If `workunit_factory` is supplied, does so in the context of a workunit.

  :param runner: the java runner to run
  :param workunit_factory: an optional callable that can produce a workunit context
  :param string workunit_name: an optional name for the work unit; defaults to the main
  :param list workunit_labels: an optional sequence of labels for the work unit
  :param string cwd: optionally set the working directory
  :param WorkUnit.LogConfig workunit_log_config: an optional tuple of task options affecting reporting

  Returns the exit code of the java runner.
  Raises `pants.java.Executor.Error` if there was a problem launching java itself.
  """
  if not isinstance(runner, Executor.Runner):
    raise ValueError('The runner argument must be a java Executor.Runner instance, '
                     'given {} of type {}'.format(runner, type(runner)))

  if workunit_factory is None:
    return runner.run()
  else:
    workunit_labels = [
        WorkUnitLabel.TOOL,
        WorkUnitLabel.NAILGUN if isinstance(runner.executor, NailgunExecutor) else WorkUnitLabel.JVM
    ] + (workunit_labels or [])

    with workunit_factory(name=workunit_name, labels=workunit_labels,
                          cmd=runner.cmd, log_config=workunit_log_config) as workunit:
      ret = runner.run(stdout=workunit.output('stdout'), stderr=workunit.output('stderr'), cwd=cwd)
      workunit.set_outcome(WorkUnit.FAILURE if ret else WorkUnit.SUCCESS)
      return ret


# VisibleForTesting
def safe_classpath(classpath, synthetic_jar_dir):
  """Bundles classpath into one synthetic jar that includes original classpath in its manifest.

  This is to ensure classpath length never exceeds platform ARG_MAX. Original classpath are
  converted to URLs relative to synthetic jar path and saved in its manifest as attribute
  `Class-Path`. See
  https://docs.oracle.com/javase/7/docs/technotes/guides/extensions/spec.html#bundled

  :param list classpath: Classpath to be bundled.
  :param string synthetic_jar_dir: directory to store the synthetic jar, if `None`
    a temp directory will be provided and cleaned up upon process exit. Otherwise synthetic
    jar will remain in the supplied directory, only for debugging purpose.

  :returns: A classpath (singleton list with just the synthetic jar).
  :rtype: list of strings
  """
  def prepare_url(url, root_dir):
    url_in_bundle = os.path.relpath(os.path.realpath(url), os.path.realpath(root_dir))
    # append '/' for directories, those not ending with '/' are assumed to be jars
    if os.path.isdir(url):
      url_in_bundle += '/'
    return url_in_bundle

  if synthetic_jar_dir:
    safe_mkdir(synthetic_jar_dir)
  else:
    synthetic_jar_dir = safe_mkdtemp()
  bundled_classpath = [prepare_url(url, synthetic_jar_dir) for url in classpath]

  manifest = Manifest()
  manifest.addentry(Manifest.CLASS_PATH, ' '.join(bundled_classpath))

  with temporary_file(root_dir=synthetic_jar_dir, cleanup=False, suffix='.jar') as jar_file:
    with open_zip(jar_file, mode='w', compression=ZIP_STORED) as jar:
      jar.writestr(Manifest.PATH, manifest.contents())
    return [jar_file.name]
