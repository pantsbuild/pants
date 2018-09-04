# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import str
from contextlib import contextmanager
from unittest import skipIf

import mock
from future.utils import PY3
from pex.package import EggPackage, Package, SourcePackage
from pex.resolver import Unsatisfiable, resolve

from pants.backend.python.interpreter_cache import PythonInterpreter, PythonInterpreterCache
from pants.backend.python.subsystems.python_repos import PythonRepos
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.subsystem.subsystem_util import global_subsystem_instance
from pants_test.test_base import TestBase
from pants_test.testutils.pexrc_util import setup_pexrc_with_pex_python_path


class TestInterpreterCache(TestBase):
  @staticmethod
  def _make_bad_requirement(requirement):
    """Turns a requirement that passes into one we know will fail.

    E.g. 'CPython==2.7.5' becomes 'CPython==99.7.5'
    """
    if PY3:
      return str(requirement).replace('==3', '==99')
    else:
      return str(requirement).replace('==2.', '==99')

  def setUp(self):
    super(TestInterpreterCache, self).setUp()
    self._interpreter = PythonInterpreter.get()

  def create_python_subsystems(self, setup_options=None, repos_options=None):
    Subsystem.reset(reset_options=True)
    def create_subsystem(subsystem_type, options=None):
      return global_subsystem_instance(subsystem_type,
                                       options={subsystem_type.options_scope: options or {}})
    return (create_subsystem(PythonSetup, setup_options),
            create_subsystem(PythonRepos, repos_options))

  @contextmanager
  def _setup_cache(self, constraints=None):
    with temporary_dir() as path:
      setup_options = {'interpreter_cache_dir': path}
      if constraints:
        setup_options.update(interpreter_constraints=constraints)
      python_setup, python_repos = self.create_python_subsystems(setup_options=setup_options)
      cache = PythonInterpreterCache(python_setup=python_setup, python_repos=python_repos)
      yield cache, path

  def test_cache_setup_with_no_filters_uses_repo_default_excluded(self):
    bad_interpreter_requirement = self._make_bad_requirement(self._interpreter.identity.requirement)
    with self._setup_cache(constraints=[bad_interpreter_requirement]) as (cache, _):
      self.assertEqual([], cache.setup())

  def test_cache_setup_with_no_filters_uses_repo_default(self):
    with self._setup_cache() as (cache, _):
      self.assertIn(self._interpreter, cache.setup())

  def test_cache_setup_with_filter_overrides_repo_default(self):
    bad_interpreter_requirement = self._make_bad_requirement(self._interpreter.identity.requirement)
    with self._setup_cache(constraints=[bad_interpreter_requirement]) as (cache, _):
      self.assertIn(self._interpreter,
                    cache.setup(filters=(str(self._interpreter.identity.requirement),)))

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

      python_setup, python_repos = self.create_python_subsystems(
        setup_options={
          'interpreter_cache_dir': None,
          'pants_workdir': os.path.join(root, 'workdir'),
          'constraints': [interpreter_requirement],
          'setuptools_version': setuptools_version,
          'wheel_version': wheel_version,
        },
        repos_options={
          'indexes': [],
          'repos': [egg_dir],
        }
      )
      cache = PythonInterpreterCache(python_setup=python_setup, python_repos=python_repos)

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

  def test_setup_resolve_failure_cleanup(self):
    """Simulates a resolution failure during interpreter setup to avoid partial interpreter caching.

    See https://github.com/pantsbuild/pants/issues/2038 for more info.
    """
    with mock.patch.object(PythonInterpreterCache, '_resolve') as mock_resolve, \
         self._setup_cache() as (cache, cache_path):
      mock_resolve.side_effect = Unsatisfiable('nope')

      with self.assertRaises(Unsatisfiable):
        cache._setup_interpreter(self._interpreter, os.path.join(cache_path, 'CPython-2.7.11'))

      # Before the bugfix, the above call would leave behind paths in the tmpdir that looked like:
      #
      #     /tmp/tmpUrCSzk/CPython-2.7.11.tmp.a167fc50834a4f00aa280780c3e1ba21
      #
      self.assertFalse('.tmp.' in ' '.join(os.listdir(cache_path)),
                       'interpreter cache path contains tmp dirs!')

  py27 = '2.7'
  py36 = '3.6'

  @skipIf(not (PantsRunIntegrationTest.has_python_version(py27) and
               PantsRunIntegrationTest.has_python_version(py36)),
          'Could not find both python {} and python {} on system. Skipping.'.format(py27, py36))
  def test_pex_python_paths(self):
    """Test pex python path helper method of PythonInterpreterCache."""
    py27_path = PantsRunIntegrationTest.python_interpreter_path(self.py27)
    py3_path = PantsRunIntegrationTest.python_interpreter_path(self.py36)
    with setup_pexrc_with_pex_python_path([py27_path, py3_path]):
      with self._setup_cache() as (cache, _):
        pex_python_paths = cache.pex_python_paths()
        self.assertEqual(pex_python_paths, [py27_path, py3_path])

  @skipIf(not (PantsRunIntegrationTest.has_python_version(py27) and
               PantsRunIntegrationTest.has_python_version(py36)),
          'Skipping test, both python {} and {} arge needed.'.format(py27, py36))
  def test_interpereter_cache_setup_using_pex_python_paths(self):
    """Test cache setup using interpreters from a mocked PEX_PYTHON_PATH."""
    py27_path = PantsRunIntegrationTest.python_interpreter_path(self.py27)
    py36_path = PantsRunIntegrationTest.python_interpreter_path(self.py36)
    with setup_pexrc_with_pex_python_path([py27_path, py36_path]):
      with self._setup_cache(constraints=['CPython>=2.7,<3']) as (cache, _):
        self.assertIn(py27_path, {pi.binary for pi in cache.setup()})
      with self._setup_cache(constraints=['CPython>=3.6,<4']) as (cache, _):
        self.assertIn(py36_path, {pi.binary for pi in cache.setup()})

  def test_setup_cached_warm(self):
    with self._setup_test(mock_setup_cached=False) as (cache, path):
      safe_mkdir(os.path.join(path, 'python'))
      cache._interpreter_from_path = mock.Mock(return_value=self._interpreter)
      interpreters = list(cache._setup_cached(filters=[]))

      assert len(interpreters) == 1
      assert interpreters[0] == self._interpreter

  def test_setup_cached_cold(self):
    with self._setup_test(mock_setup_cached=False) as (cache, path):
      cache._interpreter_from_path = mock.Mock(return_value=[self._interpreter])
      interpreters = list(cache._setup_cached(filters=[]))

      assert len(interpreters) == 0
