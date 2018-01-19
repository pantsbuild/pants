# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ConfigParser
import glob
import os
import shutil
import unittest
from collections import namedtuple
from contextlib import contextmanager
from operator import eq, ne
from threading import Lock

from colors import strip_color

from pants.base.build_environment import get_buildroot
from pants.base.build_file import BuildFile
from pants.fs.archive import ZIP
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import environment_as, pushd, temporary_dir
from pants.util.dirutil import safe_mkdir, safe_mkdir_for, safe_open
from pants.util.process_handler import SubprocessProcessHandler, subprocess
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


# TODO: Remove this in 1.5.0dev0, when `--enable-v2-engine` is removed.
def ensure_engine(f):
  """A decorator for running an integration test with and without the v2 engine enabled."""
  def wrapper(self, *args, **kwargs):
    for env_var_value in ('false', 'true'):
      with environment_as(HERMETIC_ENV='PANTS_ENABLE_V2_ENGINE', PANTS_ENABLE_V2_ENGINE=env_var_value):
        f(self, *args, **kwargs)
  return wrapper


def ensure_resolver(f):
  """A decorator for running an integration test with ivy and coursier as the resolver."""
  def wrapper(self, *args, **kwargs):
    for env_var_value in ('ivy', 'coursier'):
      with environment_as(HERMETIC_ENV='PANTS_RESOLVER_RESOLVER', PANTS_RESOLVER_RESOLVER=env_var_value):
        f(self, *args, **kwargs)

  return wrapper


def ensure_daemon(f):
  """A decorator for running an integration test with and without the daemon enabled."""
  def wrapper(self, *args, **kwargs):
    for enable_daemon in ('false', 'true',):
      with temporary_dir() as subprocess_dir:
        env = {
            'HERMETIC_ENV': 'PANTS_ENABLE_PANTSD,PANTS_ENABLE_V2_ENGINE,PANTS_SUBPROCESSDIR',
            'PANTS_ENABLE_PANTSD': enable_daemon,
            'PANTS_ENABLE_V2_ENGINE': enable_daemon,
            'PANTS_SUBPROCESSDIR': subprocess_dir,
          }
        with environment_as(**env):
          try:
            f(self, *args, **kwargs)
          finally:
            if enable_daemon:
              self.assert_success(self.run_pants(['kill-pantsd']))
  return wrapper


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
  def hermetic_env_whitelist(cls):
    """A whitelist of environment variables to propagate to tests when hermetic=True."""
    return [
        # Used in the wrapper script to locate a rust install.
        'HOME',
        'PANTS_PROFILE',
      ]

  @classmethod
  def has_python_version(cls, version):
    """Returns true if the current system has the specified version of python.

    :param version: A python version string, such as 2.7, 3.
    """
    return cls.python_interpreter_path(version) is not None

  @classmethod
  def python_interpreter_path(cls, version):
    """Returns the interpreter path if the current system has the specified version of python.

    :param version: A python version string, such as 2.7, 3.
    """
    try:
      py_path = subprocess.check_output(['python%s' % version,
                                         '-c',
                                         'import sys; print(sys.executable)']).strip()
      return os.path.realpath(py_path)
    except OSError:
      return None

  def setUp(self):
    super(PantsRunIntegrationTest, self).setUp()
    # Some integration tests rely on clean subsystem state (e.g., to set up a DistributionLocator).
    Subsystem.reset()

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

  # Incremented each time we spawn a pants subprocess.
  # Appended to PANTS_PROFILE in the called pants process, so that each subprocess
  # writes to its own profile file, instead of all stomping on the parent process's profile.
  _profile_disambiguator = 0
  _profile_disambiguator_lock = Lock()

  @classmethod
  def _get_profile_disambiguator(cls):
    with cls._profile_disambiguator_lock:
      ret = cls._profile_disambiguator
      cls._profile_disambiguator += 1
      return ret

  def get_cache_subdir(self, cache_dir, subdir_glob='*/', other_dirs=[]):
    """Check that there is only one entry of `cache_dir` which matches the glob
    specified by `subdir_glob`, excluding `other_dirs`, and
    return it.

    :param str cache_dir: absolute path to some directory.
    :param str subdir_glob: string specifying a glob for (one level down)
                            subdirectories of `cache_dir`.
    :param list other_dirs: absolute paths to subdirectories of `cache_dir`
                            which must exist and match `subdir_glob`.
    :return: Assert that there is a single remaining directory entry matching
             `subdir_glob` after removing `other_dirs`, and return it.

             This method oes not check if its arguments or return values are
             files or directories. If `subdir_glob` has a trailing slash, so
             will the return value of this method.
    """
    subdirs = set(glob.glob(os.path.join(cache_dir, subdir_glob)))
    other_dirs = set(other_dirs)
    self.assertTrue(other_dirs.issubset(subdirs))
    remaining_dirs = subdirs - other_dirs
    self.assertEqual(len(remaining_dirs), 1)
    return list(remaining_dirs)[0]

  def run_pants_with_workdir(self, command, workdir, config=None, stdin_data=None, extra_env=None,
                             build_root=None, tee_output=False, print_exception_stacktrace=True,
                             **kwargs):

    args = [
      '--no-pantsrc',
      '--pants-workdir={}'.format(workdir),
      '--kill-nailguns',
      '--print-exception-stacktrace={}'.format(print_exception_stacktrace),
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
      args.append('--pants-config-files=' + ini_file_name)

    pants_script = os.path.join(build_root or get_buildroot(), self.PANTS_SCRIPT_NAME)

    # Permit usage of shell=True and string-based commands to allow e.g. `./pants | head`.
    if kwargs.get('shell') is True:
      assert not isinstance(command, list), 'must pass command as a string when using shell=True'
      pants_command = ' '.join([pants_script, ' '.join(args), command])
    else:
      pants_command = [pants_script] + args + command

    # Only whitelisted entries will be included in the environment if hermetic=True.
    if self.hermetic():
      env = dict()
      for h in self.hermetic_env_whitelist():
        env[h] = os.getenv(h) or ''
      hermetic_env = os.getenv('HERMETIC_ENV')
      if hermetic_env:
        for h in hermetic_env.strip(',').split(','):
          env[h] = os.getenv(h)
    else:
      env = os.environ.copy()
    if extra_env:
      env.update(extra_env)

    # Don't overwrite the profile of this process in the called process.
    # Instead, write the profile into a sibling file.
    if env.get('PANTS_PROFILE'):
      prof = '{}.{}'.format(env['PANTS_PROFILE'], self._get_profile_disambiguator())
      env['PANTS_PROFILE'] = prof
      # Make a note the subprocess command, so the user can correctly interpret the profile files.
      with open('{}.cmd'.format(prof), 'w') as fp:
        fp.write(b' '.join(pants_command))

    proc = subprocess.Popen(pants_command, env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    communicate_fn = proc.communicate
    if tee_output:
      communicate_fn = SubprocessProcessHandler(proc).communicate_teeing_stdout_and_stderr
    (stdout_data, stderr_data) = communicate_fn(stdin_data)

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
    with self.pants_results(bundle_options) as pants_run:
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

  @contextmanager
  def temporary_file_content(self, path, content):
    """Temporarily write content to a file for the purpose of an integration test."""
    path = os.path.realpath(path)
    assert path.startswith(
      os.path.realpath(get_buildroot())), 'cannot write paths outside of the buildroot!'
    assert not os.path.exists(path), 'refusing to overwrite an existing path!'
    with open(path, 'wb') as fh:
      fh.write(content)
    try:
      yield
    finally:
      os.unlink(path)

  @contextmanager
  def mock_buildroot(self):
    """Construct a mock buildroot and return a helper object for interacting with it."""
    Manager = namedtuple('Manager', 'write_file pushd dir')
    # N.B. BUILD.tools, contrib, 3rdparty needs to be copied vs symlinked to avoid
    # symlink prefix check error in v1 and v2 engine.
    files_to_copy = ('BUILD.tools',)
    files_to_link = ('pants', 'pants.ini', 'pants.travis-ci.ini', '.pants.d',
                     'build-support', 'pants-plugins', 'src')
    dirs_to_copy = ('contrib', '3rdparty')

    with self.temporary_workdir() as tmp_dir:
      for filename in files_to_copy:
        shutil.copy(os.path.join(get_buildroot(), filename), os.path.join(tmp_dir, filename))

      for dirname in dirs_to_copy:
        shutil.copytree(os.path.join(get_buildroot(), dirname), os.path.join(tmp_dir, dirname))

      for filename in files_to_link:
        os.symlink(os.path.join(get_buildroot(), filename), os.path.join(tmp_dir, filename))

      def write_file(file_path, contents):
        full_file_path = os.path.join(tmp_dir, *file_path.split(os.pathsep))
        safe_mkdir_for(full_file_path)
        with open(full_file_path, 'wb') as fh:
          fh.write(contents)

      @contextmanager
      def dir_context():
        with pushd(tmp_dir):
          yield

      yield Manager(write_file, dir_context, tmp_dir)

  def do_command(self, *args, **kwargs):
    """Wrapper around run_pants method.

    :param args: command line arguments used to run pants
    :param kwargs: handles 2 keys
      success - indicate whether to expect pants run to succeed or fail.
      enable_v2_engine - indicate whether to use v2 engine or not.
    :return: a PantsResult object
    """
    success = kwargs.get('success', True)
    enable_v2_engine = kwargs.get('enable_v2_engine', False)
    cmd = ['--enable-v2-engine'] if enable_v2_engine else []
    cmd.extend(list(args))
    pants_run = self.run_pants(cmd)
    if success:
      self.assert_success(pants_run)
    else:
      self.assert_failure(pants_run)
    return pants_run
