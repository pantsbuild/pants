# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from unittest import skipIf

from pants.util.process_handler import subprocess


PY_2 = '2'
PY_3 = '3'

PY_26 = '2.6'
PY_27 = '2.7'
PY_34 = '3.4'
PY_35 = '3.5'
PY_36 = '3.6'
PY_37 = '3.7'
PY_38 = '3.8'


def find_all_pythons_present():
  """Return set of all Python versions present on the system."""
  likely_versions_present = {PY_26, PY_27, PY_34, PY_35, PY_36, PY_37, PY_38}
  return {version for version in likely_versions_present if has_python_version(version)}


def has_python_version(version):
  """Returns `True` if the current system has the specified version of python.

  :param string version: A python version string, such as 2.7, 3.
  """
  # TODO: Tests that skip unless a python interpreter is present often need the path to that
  # interpreter, and so end up calling python_interpreter_path again. Find a way to streamline this.
  return python_interpreter_path(version) is not None


def python_interpreter_path(version):
  """Returns the interpreter path if the current system has the specified version of python.

  :param string version: A python version string, such as 2.7, 3.
  :returns: the normalized path to the interpreter binary if found; otherwise `None`
  :rtype: string
  """
  try:
    command = ['python{}'.format(version), '-c', 'import sys; print(sys.executable)']
    py_path = subprocess.check_output(command).decode('utf-8').strip()
    return os.path.realpath(py_path)
  except (subprocess.CalledProcessError, FileNotFoundError):
    return None


def skip_unless_any_pythons_present(*versions):
  """A decorator that only runs the decorated test method if any of the specified pythons are present.

  :param string *versions: Python version strings, such as 2.7, 3.
  """
  if any(v for v in versions if has_python_version(v)):
    return skipIf(False, 'At least one of the expected python versions found.')
  return skipIf(True, 'Could not find at least one of the required pythons from {} on the system. Skipping.'.format(versions))


def skip_unless_all_pythons_present(*versions):
  """A decorator that only runs the decorated test method if all of the specified pythons are present.

  :param string *versions: Python version strings, such as 2.7, 3.
  """
  missing_versions = [v for v in versions if not has_python_version(v)]
  if len(missing_versions) == 1:
    return skipIf(True, 'Could not find python {} on system. Skipping.'.format(missing_versions[0]))
  elif len(missing_versions) > 1:
    return skipIf(True,
                  'Skipping due to the following missing required pythons: {}'
                  .format(', '.join(missing_versions)))
  else:
    return skipIf(False, 'All required pythons present, continuing with test!')


def skip_unless_python27_present(func):
  """A test skip decorator that only runs a test method if python2.7 is present."""
  return skip_unless_all_pythons_present(PY_27)(func)


def skip_unless_python3_present(func):
  """A test skip decorator that only runs a test method if python3 is present."""
  return skip_unless_all_pythons_present(PY_3)(func)


def skip_unless_python36_present(func):
  """A test skip decorator that only runs a test method if python3.6 is present."""
  return skip_unless_all_pythons_present(PY_36)(func)


def skip_unless_python27_and_python3_present(func):
  """A test skip decorator that only runs a test method if python2.7 and python3 are present."""
  return skip_unless_all_pythons_present(PY_27, PY_3)(func)


def skip_unless_python27_and_python36_present(func):
  """A test skip decorator that only runs a test method if python2.7 and python3.6 are present."""
  return skip_unless_all_pythons_present(PY_27, PY_36)(func)
