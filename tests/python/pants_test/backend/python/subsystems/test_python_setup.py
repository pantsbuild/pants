# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from contextlib import contextmanager

from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.util.contextutil import environment_as, temporary_dir
from pants_test.test_base import TestBase
from pants_test.testutils.pexrc_util import setup_pexrc_with_pex_python_path


@contextmanager
def fake_pyenv_root(fake_versions):
  with temporary_dir() as pyenv_root:
    fake_version_dirs = [os.path.join(pyenv_root, 'versions', v, 'bin') for v in fake_versions]
    for d in fake_version_dirs:
      os.makedirs(d)
    yield pyenv_root, fake_version_dirs


class TestPythonSetup(TestBase):
  def test_get_environment_paths(self):
    with environment_as(PATH='foo/bar:baz:/qux/quux'):
      paths = PythonSetup.get_environment_paths()
    self.assertListEqual(['foo/bar', 'baz', '/qux/quux'], paths)

  def test_get_pex_python_paths(self):
    with setup_pexrc_with_pex_python_path(['foo/bar', 'baz', '/qux/quux']):
      paths = PythonSetup.get_pex_python_paths()
    self.assertListEqual(['foo/bar', 'baz', '/qux/quux'], paths)

  def test_get_pyenv_paths(self):
    with fake_pyenv_root(['2.7.14', '3.5.5']) as (pyenv_root, expected_paths):
      paths = PythonSetup.get_pyenv_paths(pyenv_root_func=lambda: pyenv_root)
    self.assertListEqual(expected_paths, paths)

  def test_expand_interpreter_search_paths(self):
    with environment_as(PATH='/env/path1:/env/path2'):
      with setup_pexrc_with_pex_python_path(['/pexrc/path1:/pexrc/path2']):
        with fake_pyenv_root(['2.7.14', '3.5.5']) as (pyenv_root, expected_pyenv_paths):
          paths = ['/foo', '<PATH>', '/bar', '<PEXRC>', '/baz', '<PYENV>', '/qux']
          expanded_paths = PythonSetup.expand_interpreter_search_paths(
            paths, pyenv_root_func=lambda: pyenv_root)

    expected = ['/foo', '/env/path1', '/env/path2', '/bar', '/pexrc/path1', '/pexrc/path2',
                '/baz'] + expected_pyenv_paths + ['/qux']
    self.assertListEqual(expected, expanded_paths)
