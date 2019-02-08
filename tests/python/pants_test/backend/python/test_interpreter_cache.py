# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import shutil
import sys
from builtins import str
from contextlib import contextmanager

import mock
from future.utils import PY3
from pex.package import EggPackage, Package, SourcePackage
from pex.resolver import Unsatisfiable, resolve

from pants.backend.python.interpreter_cache import PythonInterpreter, PythonInterpreterCache
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_mkdir
from pants_test.backend.python.interpreter_selection_utils import (PY_27, PY_36,
                                                                   python_interpreter_path,
                                                                   skip_unless_python27_and_python36)
from pants_test.test_base import TestBase
from pants_test.testutils.pexrc_util import setup_pexrc_with_pex_python_path
from pants_test.testutils.py2_compat import assertRegex


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

  def _create_interpreter_cache(self, setup_options=None, repos_options=None):
    Subsystem.reset(reset_options=True)
    self.context(for_subsystems=[PythonInterpreterCache], options={
      'python-setup': setup_options,
      'python-repos': repos_options
    })
    return PythonInterpreterCache.global_instance()

  @contextmanager
  def _setup_cache(self, constraints=None, search_paths=None):
    with temporary_dir() as path:
      cache = self._setup_cache_at(path, constraints=constraints, search_paths=search_paths)
      yield cache, path

  def _setup_cache_at(self, path, constraints=None, search_paths=None):
    setup_options = {'interpreter_cache_dir': path}
    if constraints is not None:
      setup_options.update(interpreter_constraints=constraints)
    if search_paths is not None:
      setup_options.update(interpreter_search_paths=search_paths)
    return self._create_interpreter_cache(setup_options=setup_options, repos_options={})

  def test_cache_setup_with_no_filters_uses_repo_default_excluded(self):
    bad_interpreter_requirement = self._make_bad_requirement(self._interpreter.identity.requirement)
    with self._setup_cache(constraints=[bad_interpreter_requirement]) as (cache, _):
      self.assertEqual([], cache.setup())

  def test_cache_setup_with_no_filters_uses_repo_default(self):
    with self._setup_cache(constraints=[]) as (cache, _):
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

      resolved_dists = resolve([requirement],
                              interpreter=self._interpreter,
                              precedence=(EggPackage, SourcePackage))
      self.assertEqual(1, len(resolved_dists))
      dist_location = resolved_dists[0].distribution.location

      assertRegex(self, dist_location, r'\.egg$')
      os.symlink(dist_location, os.path.join(repo_root, os.path.basename(dist_location)))

      return Package.from_href(dist_location).raw_version

    with temporary_dir() as root:
      egg_dir = os.path.join(root, 'eggs')
      os.makedirs(egg_dir)
      setuptools_version = link_egg(egg_dir, 'setuptools')
      wheel_version = link_egg(egg_dir, 'wheel')

      interpreter_requirement = self._interpreter.identity.requirement

      cache = self._create_interpreter_cache(
        setup_options={
          'interpreter_cache_dir': None,
          'pants_workdir': os.path.join(root, 'workdir'),
          'constraints': [interpreter_requirement],
          'setuptools_version': setuptools_version,
          'wheel_version': wheel_version,
          'interpreter_search_paths': [os.path.dirname(self._interpreter.binary)]
        },
        repos_options={
          'indexes': [],
          'repos': [egg_dir],
        }
      )
      interpereters = cache.setup(filters=[str(interpreter_requirement)])
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

  @skip_unless_python27_and_python36
  def test_interpereter_cache_setup_using_pex_python_paths(self):
    """Test cache setup using interpreters from a mocked PEX_PYTHON_PATH."""
    py27_path, py36_path = python_interpreter_path(PY_27), python_interpreter_path(PY_36)
    with setup_pexrc_with_pex_python_path([py27_path, py36_path]):
      with self._setup_cache(constraints=['CPython>=2.7,<3'],
                             search_paths=['<PEXRC>']) as (cache, _):
        self.assertIn(py27_path, {pi.binary for pi in cache.setup()})
      with self._setup_cache(constraints=['CPython>=3.6,<4'],
                             search_paths=['<PEXRC>']) as (cache, _):
        self.assertIn(py36_path, {pi.binary for pi in cache.setup()})

  def test_setup_cached_warm(self):
    with self._setup_cache() as (cache, path):
      interpreters = cache.setup()
      self.assertGreater(len(interpreters), 0)

      cache = self._setup_cache_at(path)
      self.assertEqual(sorted(interpreters), sorted(list(cache._setup_cached())))

  def test_setup_cached_cold(self):
    with self._setup_cache() as (cache, _):
      self.assertEqual([], list(cache._setup_cached()))

  def test_interpreter_from_relpath_purges_stale_interpreter(self):
    """
    Simulates a stale interpreter cache and tests that _interpreter_from_relpath
    properly detects it and removes the stale dist directory.

    See https://github.com/pantsbuild/pants/issues/3416 for more info.
    """
    with temporary_dir() as temp_dir:
      # Setup a interpreter distribution that we can safely mutate.
      test_interpreter_binary = os.path.join(temp_dir, 'python2.7')
      src = os.path.realpath(sys.executable)
      sys_exe_dist = os.path.dirname(os.path.dirname(src))
      shutil.copy2(src, test_interpreter_binary)
      with environment_as(
        PYTHONPATH='{}'.format(os.path.join(sys_exe_dist, 'lib/python2.7'))
      ):
        with self._setup_cache(constraints=[]) as (cache, path):
          # Setup cache for test interpreter distribution.
          identity_str = str(PythonInterpreter.from_binary(test_interpreter_binary).identity)
          cached_interpreter_dir = os.path.join(cache._cache_dir, identity_str)
          safe_mkdir(cached_interpreter_dir)
          cached_symlink = os.path.join(cached_interpreter_dir, 'python')
          os.symlink(test_interpreter_binary, cached_symlink)

          # Remove the test interpreter binary from filesystem and assert that the cache is purged.
          os.remove(test_interpreter_binary)
          self.assertEqual(os.path.exists(test_interpreter_binary), False)
          self.assertEqual(os.path.exists(cached_interpreter_dir), True)
          cache._interpreter_from_relpath(identity_str)
          self.assertEqual(os.path.exists(cached_interpreter_dir), False)
