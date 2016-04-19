# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ConfigParser
import os
import subprocess
import unittest
from collections import namedtuple
from contextlib import contextmanager
from operator import eq, ne

from colors import strip_color

from pants.base.build_environment import get_buildroot
from pants.base.build_file import BuildFile
from pants.fs.archive import ZIP
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_open
from pants_test.testutils.file_test_util import check_symlinks, contains_exact_files


PantsResult = namedtuple(
  'PantsResult',
  ['command', 'returncode', 'stdout_data', 'stderr_data', 'workdir'])


def ensure_cached(expected_num_artifacts=None):
  """Decorator for asserting cache writes in an integration test.

  :param expected_num_artifacts: Expected number of artifacts to be in the task's
                                 cache after running the test. If unspecified, will
                                 assert that the number of artifacts in the cache is
                                 non-zero.
  """
  def decorator(test_fn):
    def wrapper(self, *args, **kwargs):
      with temporary_dir() as artifact_cache:
        cache_args = '--cache-write-to=["{}"]'.format(artifact_cache)

        test_fn(self, *args + (cache_args,), **kwargs)

        num_artifacts = 0
        for (root, _, files) in os.walk(artifact_cache):
          print(root, files)
          num_artifacts += len(files)

        if expected_num_artifacts is None:
          self.assertNotEqual(num_artifacts, 0)
        else:
          self.assertEqual(num_artifacts, expected_num_artifacts)
    return wrapper
  return decorator


class PantsRunIntegrationTest(unittest.TestCase):
  """A base class useful for integration tests for targets in the same repo."""

  PANTS_SUCCESS_CODE = 0
  PANTS_SCRIPT_NAME = 'pants'

  @classmethod
  def hermetic(cls):
    """Subclasses may override to acknowledge that they are hermetic.

    That is, that they should run without reading the real pants.ini.
    """
    return False

  @classmethod
  def has_python_version(cls, version):
    """Returns true if the current system has the specified version of python.

    :param version: A python version string, such as 2.6, 3.
    """
    try:
      subprocess.call(['python%s' % version, '-V'])
      return True
    except OSError:
      return False

  def temporary_workdir(self, cleanup=True):
    # We can hard-code '.pants.d' here because we know that will always be its value
    # in the pantsbuild/pants repo (e.g., that's what we .gitignore in that repo).
    # Grabbing the pants_workdir config would require this pants's config object,
    # which we don't have a reference to here.
    root = os.path.join(get_buildroot(), '.pants.d', 'tmp')
    safe_mkdir(root)
    return temporary_dir(root_dir=root, cleanup=cleanup, suffix='.pants.d')

  def temporary_cachedir(self):
    return temporary_dir(suffix='__CACHEDIR')

  def temporary_sourcedir(self):
    return temporary_dir(root_dir=get_buildroot())

  @contextmanager
  def source_clone(self, source_dir):
    with self.temporary_sourcedir() as clone_dir:
      target_spec_dir = os.path.relpath(clone_dir)

      for dir_path, dir_names, file_names in os.walk(source_dir):
        clone_dir_path = os.path.join(clone_dir, os.path.relpath(dir_path, source_dir))
        for dir_name in dir_names:
          os.mkdir(os.path.join(clone_dir_path, dir_name))
        for file_name in file_names:
          with open(os.path.join(dir_path, file_name), 'r') as f:
            content = f.read()
          if BuildFile._is_buildfile_name(file_name):
            content = content.replace(source_dir, target_spec_dir)
          with open(os.path.join(clone_dir_path, file_name), 'w') as f:
            f.write(content)

      yield clone_dir

  def run_pants_with_workdir(self, command, workdir, config=None, stdin_data=None, extra_env=None,
                             **kwargs):

    args = [
      '--no-pantsrc',
      '--pants-workdir={}'.format(workdir),
      '--kill-nailguns',
      '--print-exception-stacktrace',
    ]

    if self.hermetic():
      args.extend(['--pants-config-files=[]',
                   # Turn off cache globally.  A hermetic integration test shouldn't rely on cache,
                   # or we have no idea if it's actually testing anything.
                   '--no-cache-read', '--no-cache-write',
                   # Turn cache on just for tool bootstrapping, for performance.
                   '--cache-bootstrap-read', '--cache-bootstrap-write'
                   ])

    if config:
      config_data = config.copy()
      ini = ConfigParser.ConfigParser(defaults=config_data.pop('DEFAULT', None))
      for section, section_config in config_data.items():
        ini.add_section(section)
        for key, value in section_config.items():
          ini.set(section, key, value)
      ini_file_name = os.path.join(workdir, 'pants.ini')
      with safe_open(ini_file_name, mode='w') as fp:
        ini.write(fp)
      args.append('--config-override=' + ini_file_name)

    pants_script = os.path.join(get_buildroot(), self.PANTS_SCRIPT_NAME)
    pants_command = [pants_script] + args + command

    if self.hermetic():
      env = {}
    else:
      env = os.environ.copy()
    if extra_env:
      env.update(extra_env)

    proc = subprocess.Popen(pants_command, env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    (stdout_data, stderr_data) = proc.communicate(stdin_data)

    return PantsResult(pants_command, proc.returncode, stdout_data.decode("utf-8"),
                       stderr_data.decode("utf-8"), workdir)

  def run_pants(self, command, config=None, stdin_data=None, extra_env=None, **kwargs):
    """Runs pants in a subprocess.

    :param list command: A list of command line arguments coming after `./pants`.
    :param config: Optional data for a generated ini file. A map of <section-name> ->
    map of key -> value. If order in the ini file matters, this should be an OrderedDict.
    :param kwargs: Extra keyword args to pass to `subprocess.Popen`.
    :returns a tuple (returncode, stdout_data, stderr_data).
    """
    with self.temporary_workdir() as workdir:
      return self.run_pants_with_workdir(command, workdir, config, stdin_data, extra_env, **kwargs)

  @contextmanager
  def pants_results(self, command, config=None, stdin_data=None, extra_env=None, **kwargs):
    """Similar to run_pants in that it runs pants in a subprocess, but yields in order to give
    callers a chance to do any necessary validations on the workdir.

    :param list command: A list of command line arguments coming after `./pants`.
    :param config: Optional data for a generated ini file. A map of <section-name> ->
    map of key -> value. If order in the ini file matters, this should be an OrderedDict.
    :param kwargs: Extra keyword args to pass to `subprocess.Popen`.
    :returns a tuple (returncode, stdout_data, stderr_data).
    """
    with self.temporary_workdir() as workdir:
      yield self.run_pants_with_workdir(command, workdir, config, stdin_data, extra_env, **kwargs)

  def bundle_and_run(self, target, bundle_name, bundle_jar_name=None, bundle_options=None,
                     args=None,
                     expected_bundle_jar_content=None,
                     expected_bundle_content=None,
                     library_jars_are_symlinks=True):
    """Creates the bundle with pants, then does java -jar {bundle_name}.jar to execute the bundle.

    :param target: target name to compile
    :param bundle_name: resulting bundle filename (minus .zip extension)
    :param bundle_jar_name: monolithic jar filename (minus .jar extension), if None will be the
      same as bundle_name
    :param bundle_options: additional options for bundle
    :param args: optional arguments to pass to executable
    :param expected_bundle_content: verify the bundle zip content
    :param expected_bundle_jar_content: verify the bundle jar content
    :param library_jars_are_symlinks: verify library jars are symlinks if True, and actual
      files if False. Default `True` because we always create symlinks for both external and internal
      dependencies, only exception is when shading is used.
    :return: stdout as a string on success, raises an Exception on error
    """
    bundle_jar_name = bundle_jar_name or bundle_name
    bundle_options = bundle_options or []
    bundle_options = ['bundle.jvm'] + bundle_options + ['--archive=zip', target]
    pants_run = self.run_pants(bundle_options)
    self.assert_success(pants_run)

    self.assertTrue(check_symlinks('dist/{bundle_name}-bundle/libs'.format(bundle_name=bundle_name),
                                   library_jars_are_symlinks))
    # TODO(John Sirois): We need a zip here to suck in external library classpath elements
    # pointed to by symlinks in the run_pants ephemeral tmpdir.  Switch run_pants to be a
    # contextmanager that yields its results while the tmpdir workdir is still active and change
    # this test back to using an un-archived bundle.
    with temporary_dir() as workdir:
      ZIP.extract('dist/{bundle_name}.zip'.format(bundle_name=bundle_name), workdir)
      if expected_bundle_content:
        self.assertTrue(contains_exact_files(workdir, expected_bundle_content))
      if expected_bundle_jar_content:
        with temporary_dir() as check_bundle_jar_dir:
          bundle_jar = os.path.join(workdir, '{bundle_jar_name}.jar'
                                    .format(bundle_jar_name=bundle_jar_name))
          ZIP.extract(bundle_jar, check_bundle_jar_dir)
          self.assertTrue(contains_exact_files(check_bundle_jar_dir, expected_bundle_jar_content))

      optional_args = []
      if args:
        optional_args = args
      java_run = subprocess.Popen(['java',
                                   '-jar',
                                   '{bundle_jar_name}.jar'.format(bundle_jar_name=bundle_jar_name)]
                                  + optional_args,
                                  stdout=subprocess.PIPE,
                                  cwd=workdir)

      stdout, _ = java_run.communicate()
    java_returncode = java_run.returncode
    self.assertEquals(java_returncode, 0)
    return stdout

  def assert_success(self, pants_run, msg=None):
    self.assert_result(pants_run, self.PANTS_SUCCESS_CODE, expected=True, msg=msg)

  def assert_failure(self, pants_run, msg=None):
    self.assert_result(pants_run, self.PANTS_SUCCESS_CODE, expected=False, msg=msg)

  def assert_result(self, pants_run, value, expected=True, msg=None):
    check, assertion = (eq, self.assertEqual) if expected else (ne, self.assertNotEqual)
    if check(pants_run.returncode, value):
      return

    details = [msg] if msg else []
    details.append(' '.join(pants_run.command))
    details.append('returncode: {returncode}'.format(returncode=pants_run.returncode))

    def indent(content):
      return '\n\t'.join(content.splitlines())

    if pants_run.stdout_data:
      details.append('stdout:\n\t{stdout}'.format(stdout=indent(pants_run.stdout_data)))
    if pants_run.stderr_data:
      details.append('stderr:\n\t{stderr}'.format(stderr=indent(pants_run.stderr_data)))
    error_msg = '\n'.join(details)

    assertion(value, pants_run.returncode, error_msg)

  def normalize(self, s):
    """Removes escape sequences (e.g. colored output) and all whitespace from string s."""
    return ''.join(strip_color(s).split())

  @contextmanager
  def file_renamed(self, prefix, test_name, real_name):
    real_path = os.path.join(prefix, real_name)
    test_path = os.path.join(prefix, test_name)
    try:
      os.rename(test_path, real_path)
      yield
    finally:
      os.rename(real_path, test_path)
