# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

import mock
from pex.package import EggPackage, Package, SourcePackage
from pex.resolver import resolve

from pants.backend.python.interpreter_cache import PythonInterpreter, PythonInterpreterCache
from pants.backend.python.python_setup import PythonRepos, PythonSetup
from pants.util.contextutil import temporary_dir
from pants_test.subsystem.subsystem_util import create_subsystem


class TestInterpreterCache(unittest.TestCase):
  def _make_bad_requirement(self, requirement):
    """Turns a requirement that passes into one we know will fail.

    E.g. 'CPython==2.7.5' becomes 'CPython==99.7.5'
    """
    return str(requirement).replace('==2.', '==99.')

  def setUp(self):
    self._interpreter = PythonInterpreter.get()

  def _do_test(self, interpreter_requirement, filters, expected):
    mock_setup = mock.MagicMock().return_value

    # Explicitly set a repo-wide requirement that excludes our one interpreter.
    type(mock_setup).interpreter_requirement = mock.PropertyMock(
      return_value=interpreter_requirement)

    with temporary_dir() as path:
      mock_setup.interpreter_cache_dir = path
      cache = PythonInterpreterCache(mock_setup, mock.MagicMock())

      def set_interpreters(_):
        cache._interpreters.add(self._interpreter)

      cache._setup_cached = mock.Mock(side_effect=set_interpreters)
      cache._setup_paths = mock.Mock()

      self.assertEqual(cache.setup(filters=filters), expected)

  def test_cache_setup_with_no_filters_uses_repo_default_excluded(self):
    self._do_test(self._make_bad_requirement(self._interpreter.identity.requirement), [], [])

  def test_cache_setup_with_no_filters_uses_repo_default(self):
    self._do_test(None, [], [self._interpreter])

  def test_cache_setup_with_filter_overrides_repo_default(self):
    self._do_test(self._make_bad_requirement(self._interpreter.identity.requirement),
                  (str(self._interpreter.identity.requirement), ),
                  [self._interpreter])

  def test_setup_using_eggs(self):
    def link_egg(repo_root, requirement):
      existing_dist_location = self._interpreter.get_location(requirement)
      if existing_dist_location is not None:
        existing_dist = Package.from_href(existing_dist_location)
        requirement = '{}=={}'.format(existing_dist.name, existing_dist.raw_version)

      distributions = resolve([requirement],
                              interpreter=self._interpreter,
                              precedence=(EggPackage, SourcePackage))
      self.assertEqual(1, len(distributions))
      dist_location = distributions[0].location

      self.assertRegexpMatches(dist_location, r'\.egg$')
      os.symlink(dist_location, os.path.join(repo_root, os.path.basename(dist_location)))

      return Package.from_href(dist_location).raw_version

    with temporary_dir() as root:
      egg_dir = os.path.join(root, 'eggs')
      os.makedirs(egg_dir)
      setuptools_version = link_egg(egg_dir, 'setuptools')
      wheel_version = link_egg(egg_dir, 'wheel')

      interpreter_requirement = self._interpreter.identity.requirement
      python_setup = create_subsystem(PythonSetup,
                                      interpreter_cache_dir=None,
                                      pants_workdir=os.path.join(root, 'workdir'),
                                      interpreter_requirement=interpreter_requirement,
                                      setuptools_version=setuptools_version,
                                      wheel_version=wheel_version)
      python_repos = create_subsystem(PythonRepos, indexes=[], repos=[egg_dir])
      cache = PythonInterpreterCache(python_setup, python_repos)

      interpereters = cache.setup(paths=[os.path.dirname(self._interpreter.binary)],
                                  filters=[str(interpreter_requirement)])
      self.assertGreater(len(interpereters), 0)

      def assert_egg_extra(interpreter, name, version):
        location = interpreter.get_location('{}=={}'.format(name, version))
        self.assertIsNotNone(location)
        self.assertIsInstance(Package.from_href(location), EggPackage)

      for interpreter in interpereters:
        assert_egg_extra(interpreter, 'setuptools', setuptools_version)
        assert_egg_extra(interpreter, 'wheel', wheel_version)
