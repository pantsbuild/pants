# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import sys
from zipfile import ZIP_STORED

from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.java.executor import Executor, SubprocessExecutor
from pants.java.jar.manifest import Manifest
from pants.java.nailgun_executor import NailgunExecutor
from pants.util.contextutil import open_zip, temporary_file
from pants.util.dirutil import safe_concurrent_rename, safe_mkdir, safe_mkdtemp
from pants.util.process_handler import ProcessHandler, SubprocessProcessHandler


logger = logging.getLogger(__name__)


def _get_runner(classpath, main, jvm_options, args, executor,
               cwd, distribution,
               create_synthetic_jar, synthetic_jar_dir):
  """Gets the java runner for execute_java and execute_java_async."""

  executor = executor or SubprocessExecutor(distribution)

  safe_cp = classpath
  if create_synthetic_jar:
    safe_cp = safe_classpath(classpath, synthetic_jar_dir)
    logger.debug('Bundling classpath {} into {}'.format(':'.join(classpath), safe_cp))

  return executor.runner(safe_cp, main, args=args, jvm_options=jvm_options, cwd=cwd)


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

  runner = _get_runner(classpath, main, jvm_options, args, executor, cwd, distribution,
                       create_synthetic_jar, synthetic_jar_dir)
  workunit_name = workunit_name or main

  return execute_runner(runner,
                        workunit_factory=workunit_factory,
                        workunit_name=workunit_name,
                        workunit_labels=workunit_labels,
                        workunit_log_config=workunit_log_config)


def execute_java_async(classpath, main, jvm_options=None, args=None, executor=None,
                       workunit_factory=None, workunit_name=None, workunit_labels=None,
                       cwd=None, workunit_log_config=None, distribution=None,
                       create_synthetic_jar=True, synthetic_jar_dir=None):
  """This is just like execute_java except that it returns a ProcessHandler rather than a return code.


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

  Returns a ProcessHandler to the java program.
  Raises `pants.java.Executor.Error` if there was a problem launching java itself.
  """

  runner = _get_runner(classpath, main, jvm_options, args, executor, cwd, distribution,
                       create_synthetic_jar, synthetic_jar_dir)
  workunit_name = workunit_name or main

  return execute_runner_async(runner,
                              workunit_factory=workunit_factory,
                              workunit_name=workunit_name,
                              workunit_labels=workunit_labels,
                              workunit_log_config=workunit_log_config)


def execute_runner(runner, workunit_factory=None, workunit_name=None, workunit_labels=None,
                   workunit_log_config=None):
  """Executes the given java runner.

  If `workunit_factory` is supplied, does so in the context of a workunit.

  :param runner: the java runner to run
  :param workunit_factory: an optional callable that can produce a workunit context
  :param string workunit_name: an optional name for the work unit; defaults to the main
  :param list workunit_labels: an optional sequence of labels for the work unit
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
      ret = runner.run(stdout=workunit.output('stdout'), stderr=workunit.output('stderr'))
      workunit.set_outcome(WorkUnit.FAILURE if ret else WorkUnit.SUCCESS)
      return ret


def execute_runner_async(runner, workunit_factory=None, workunit_name=None, workunit_labels=None,
                         workunit_log_config=None):
  """Executes the given java runner asynchronously.

  We can't use 'with' here because the workunit_generator's __exit__ function
  must be called after the process exits, in the return_code_handler.
  The wrapper around process.wait() needs to handle the same exceptions
  as the contextmanager does, so we have code duplication.

  We're basically faking the 'with' call to deal with asynchronous
  results.

  If `workunit_factory` is supplied, does so in the context of a workunit.

  :param runner: the java runner to run
  :param workunit_factory: an optional callable that can produce a workunit context
  :param string workunit_name: an optional name for the work unit; defaults to the main
  :param list workunit_labels: an optional sequence of labels for the work unit
  :param WorkUnit.LogConfig workunit_log_config: an optional tuple of task options affecting reporting

  Returns a ProcessHandler to the java process that is spawned.
  Raises `pants.java.Executor.Error` if there was a problem launching java itself.
  """

  if not isinstance(runner, Executor.Runner):
    raise ValueError('The runner argument must be a java Executor.Runner instance, '
                     'given {} of type {}'.format(runner, type(runner)))

  if workunit_factory is None:
    return SubprocessProcessHandler(runner.spawn())
  else:
    workunit_labels = [
                        WorkUnitLabel.TOOL,
                        WorkUnitLabel.NAILGUN if isinstance(runner.executor, NailgunExecutor) else WorkUnitLabel.JVM
                      ] + (workunit_labels or [])

    workunit_generator = workunit_factory(name=workunit_name, labels=workunit_labels,
                                cmd=runner.cmd, log_config=workunit_log_config)
    workunit = workunit_generator.__enter__()
    process = runner.spawn(stdout=workunit.output('stdout'), stderr=workunit.output('stderr'))

    class WorkUnitProcessHandler(ProcessHandler):
      def wait(_):
        try:
          ret = process.wait()
          workunit.set_outcome(WorkUnit.FAILURE if ret else WorkUnit.SUCCESS)
          workunit_generator.__exit__(None, None, None)
          return ret
        except BaseException:
          if not workunit_generator.__exit__(*sys.exc_info()):
            raise

      def kill(_):
        return process.kill()

      def terminate(_):
        return process.terminate()

      def poll(_):
        return process.poll()

    return WorkUnitProcessHandler()


def relativize_classpath(classpath, root_dir, followlinks=True):
  """Convert into classpath relative to a directory.

  This is eventually used by a jar file located in this directory as its manifest
  attribute Class-Path. See
  https://docs.oracle.com/javase/7/docs/technotes/guides/extensions/spec.html#bundled

  :param list classpath: Classpath to be relativized.
  :param string root_dir: directory to relativize urls in the classpath, does not
    have to exist yet.
  :param bool followlinks: whether to follow symlinks to calculate relative path.

  :returns: Converted classpath of the same size as input classpath.
  :rtype: list of strings
  """
  def relativize_url(url, root_dir):
    # When symlink is involed, root_dir concatenated with the returned relpath may not exist.
    # Consider on mac `/var` is a symlink of `/private/var`, the relative path of subdirectories
    # under /var to any other directories under `/` computed by os.path.relpath misses one level
    # of `..`. Use os.path.realpath to guarantee returned relpath can always be located.
    # This is not needed only when path are all relative.
    url = os.path.realpath(url) if followlinks else url
    root_dir = os.path.realpath(root_dir) if followlinks else root_dir
    url_in_bundle = os.path.relpath(url, root_dir)
    # Append '/' for directories, those not ending with '/' are assumed to be jars.
    # Note isdir does what we need here to follow symlinks.
    if os.path.isdir(url):
      url_in_bundle += '/'
    return url_in_bundle

  return [relativize_url(url, root_dir) for url in classpath]


# VisibleForTesting
def safe_classpath(classpath, synthetic_jar_dir, custom_name=None):
  """Bundles classpath into one synthetic jar that includes original classpath in its manifest.

  This is to ensure classpath length never exceeds platform ARG_MAX.

  :param list classpath: Classpath to be bundled.
  :param string synthetic_jar_dir: directory to store the synthetic jar, if `None`
    a temp directory will be provided and cleaned up upon process exit. Otherwise synthetic
    jar will remain in the supplied directory, only for debugging purpose.
  :param custom_name: filename of the synthetic jar to be created.

  :returns: A classpath (singleton list with just the synthetic jar).
  :rtype: list of strings
  """
  if synthetic_jar_dir:
    safe_mkdir(synthetic_jar_dir)
  else:
    synthetic_jar_dir = safe_mkdtemp()

  bundled_classpath = relativize_classpath(classpath, synthetic_jar_dir)

  manifest = Manifest()
  manifest.addentry(Manifest.CLASS_PATH, ' '.join(bundled_classpath))

  with temporary_file(root_dir=synthetic_jar_dir, cleanup=False, suffix='.jar') as jar_file:
    with open_zip(jar_file, mode='w', compression=ZIP_STORED) as jar:
      jar.writestr(Manifest.PATH, manifest.contents())

    if custom_name:
      custom_path = os.path.join(synthetic_jar_dir, custom_name)
      safe_concurrent_rename(jar_file.name, custom_path)
      return [custom_path]
    else:
      return [jar_file.name]
