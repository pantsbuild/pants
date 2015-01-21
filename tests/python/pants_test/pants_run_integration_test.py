# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import namedtuple
from operator import eq, ne
import os
import subprocess
import unittest2 as unittest

from pants.fs.archive import ZIP
from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_open, safe_mkdir


PantsResult = namedtuple('PantsResult', ['command', 'returncode', 'stdout_data', 'stderr_data'])


class PantsRunIntegrationTest(unittest.TestCase):
  """A base class useful for integration tests for targets in the same repo."""

  PANTS_SUCCESS_CODE = 0
  PANTS_SCRIPT_NAME = 'pants'

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

  def workdir_root(self):
    # We can hard-code '.pants.d' here because we know that will always be its value
    # in the pantsbuild/pants repo (e.g., that's what we .gitignore in that repo).
    # Grabbing the pants_workdir config would require this pants's config object,
    # which we don't have a reference to here.
    root = os.path.join(get_buildroot(), '.pants.d', 'tmp')
    safe_mkdir(root)
    return root

  def run_pants_with_workdir(self, command, workdir, config=None, stdin_data=None, extra_env=None,
                             **kwargs):
    config = config.copy() if config else {}

    # We add workdir to the DEFAULT section, and also ensure that it's emitted first.
    default_section = config.pop('DEFAULT', {})
    default_section['pants_workdir'] = '%s' % workdir

    ini = ''
    for section, section_config in [('DEFAULT', default_section)] + config.items():
      ini += '\n[%s]\n' % section
      for key, val in section_config.items():
        ini += '%s: %s\n' % (key, val)

    ini_file_name = os.path.join(workdir, 'pants.ini')
    with safe_open(ini_file_name, mode='w') as fp:
      fp.write(ini)
    env = os.environ.copy()
    env.update(extra_env or {})

    pants_script = os.path.join(get_buildroot(), self.PANTS_SCRIPT_NAME)
    pants_command = [pants_script,
                     '--no-lock',
                     '--kill-nailguns',
                     '--no-pantsrc',
                     '--config-override={0}'.format(ini_file_name),
                     '--print-exception-stacktrace'] + command

    proc = subprocess.Popen(pants_command, env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    (stdout_data, stderr_data) = proc.communicate(stdin_data)
    return PantsResult(pants_command, proc.returncode, stdout_data, stderr_data)

  def run_pants(self, command, config=None, stdin_data=None, extra_env=None, **kwargs):
    """Runs pants in a subprocess.

    :param list command: A list of command line arguments coming after `./pants`.
    :param config: Optional data for a generated ini file. A map of <section-name> ->
    map of key -> value. If order in the ini file matters, this should be an OrderedDict.
    :param kwargs: Extra keyword args to pass to `subprocess.Popen`.
    :returns a tuple (returncode, stdout_data, stderr_data).

    IMPORTANT NOTE: The subprocess will be run with --no-lock, so that it doesn't deadlock waiting
    for this process to release the workspace lock. It's the caller's responsibility to ensure
    that the invoked pants doesn't interact badly with this one.
    """

    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      return self.run_pants_with_workdir(command, workdir, config, stdin_data, extra_env, **kwargs)

  def bundle_and_run(self, target, bundle_name, args=None):
    """Creates the bundle with pants, then does java -jar {bundle_name}.jar to execute the bundle.

    :param target: target name to compile
    :param bundle_name: resulting bundle filename (minus .jar extension)
    :param args: optional arguments to pass to executable
    :return: stdout as a string on success, raises an Exception on error
    """
    pants_run = self.run_pants(['bundle', '--archive=zip', target])
    self.assert_success(pants_run)

    # TODO(John Sirois): We need a zip here to suck in external library classpath elements
    # pointed to by symlinks in the run_pants ephemeral tmpdir.  Switch run_pants to be a
    # contextmanager that yields its results while the tmpdir workdir is still active and change
    # this test back to using an un-archived bundle.
    with temporary_dir() as workdir:
      ZIP.extract('dist/{bundle_name}.zip'.format(bundle_name=bundle_name), workdir)
      optional_args = []
      if args:
        optional_args = args
      java_run = subprocess.Popen(['java',
                                   '-jar',
                                   '{bundle_name}.jar'.format(bundle_name=bundle_name)]
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
