# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
from contextlib import contextmanager

from pants.backend.python.interpreter_cache import PythonInterpreter, PythonInterpreterCache
from pants.subsystem.subsystem import Subsystem
from pants.testutil.interpreter_selection_utils import (
    PY_27,
    PY_36,
    python_interpreter_path,
    skip_unless_python27_and_python36_present,
)
from pants.testutil.pexrc_util import setup_pexrc_with_pex_python_path
from pants.testutil.test_base import TestBase
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir


class TestInterpreterCache(TestBase):
    @staticmethod
    def _make_bad_requirement(requirement):
        """Turns a requirement that passes into one we know will fail.

        E.g. 'CPython==3.7.2' becomes 'CPython==99.7.2'
        """
        requirement_major_version = "3"
        return str(requirement).replace(f"=={requirement_major_version}", "==99")

    def setUp(self):
        super().setUp()
        self._interpreter = PythonInterpreter.get()

    def _create_interpreter_cache(self, setup_options=None):
        Subsystem.reset(reset_options=True)
        self.context(
            for_subsystems=[PythonInterpreterCache], options={"python-setup": setup_options}
        )
        return PythonInterpreterCache.global_instance()

    @contextmanager
    def _setup_cache(self, constraints=None, search_paths=None):
        with temporary_dir() as path:
            cache = self._setup_cache_at(path, constraints=constraints, search_paths=search_paths)
            yield cache, path

    def _setup_cache_at(self, path, constraints=None, search_paths=None):
        setup_options = {"interpreter_cache_dir": path}
        if constraints is not None:
            setup_options.update(interpreter_constraints=constraints)
        if search_paths is not None:
            setup_options.update(interpreter_search_paths=search_paths)
        return self._create_interpreter_cache(setup_options=setup_options)

    def test_cache_setup_with_no_filters_uses_repo_default_excluded(self):
        bad_interpreter_requirement = self._make_bad_requirement(
            self._interpreter.identity.requirement
        )
        with self._setup_cache(constraints=[bad_interpreter_requirement]) as (cache, _):
            self.assertEqual([], cache.setup())

    def test_cache_setup_with_no_filters_uses_repo_default(self):
        with self._setup_cache(constraints=[]) as (cache, _):
            self.assertIn(self._interpreter.identity, [interp.identity for interp in cache.setup()])

    def test_cache_setup_with_filter_overrides_repo_default(self):
        repo_default_requirement = str(self._interpreter.identity.requirement)
        bad_interpreter_requirement = self._make_bad_requirement(repo_default_requirement)
        with self._setup_cache(constraints=[bad_interpreter_requirement]) as (cache, _):
            self.assertIn(
                str(self._interpreter.identity.requirement),
                [
                    str(interp.identity.requirement)
                    for interp in cache.setup(filters=(repo_default_requirement,))
                ],
            )

    @skip_unless_python27_and_python36_present
    def test_interpreter_cache_setup_using_pex_python_paths(self):
        """Test cache setup using interpreters from a mocked PEX_PYTHON_PATH."""
        py27_path, py36_path = python_interpreter_path(PY_27), python_interpreter_path(PY_36)
        with setup_pexrc_with_pex_python_path([py27_path, py36_path]):
            with self._setup_cache(constraints=["CPython>=2.7,<3"], search_paths=["<PEXRC>"]) as (
                cache,
                _,
            ):
                self.assertIn(py27_path, {pi.binary for pi in cache.setup()})
            with self._setup_cache(constraints=["CPython>=3.6"], search_paths=["<PEXRC>"]) as (
                cache,
                _,
            ):
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
        """Simulates a stale interpreter cache and tests that _interpreter_from_relpath properly
        detects it and removes the stale dist directory.

        See https://github.com/pantsbuild/pants/issues/3416 for more info.
        """
        with temporary_dir() as temp_dir:
            # Setup a interpreter distribution that we can safely mutate.
            test_interpreter_binary = os.path.join(temp_dir, "python")
            os.symlink(sys.executable, test_interpreter_binary)
            with self._setup_cache(constraints=[]) as (cache, path):
                # Setup cache for test interpreter distribution.
                identity_str = str(PythonInterpreter.from_binary(test_interpreter_binary).identity)
                cached_interpreter_dir = os.path.join(cache._cache_dir, identity_str)
                safe_mkdir(cached_interpreter_dir)
                cached_symlink = os.path.join(cached_interpreter_dir, "python")
                os.symlink(test_interpreter_binary, cached_symlink)

                # Remove the test interpreter binary from filesystem and assert that the cache is purged.
                os.remove(test_interpreter_binary)
                self.assertEqual(os.path.exists(test_interpreter_binary), False)
                self.assertEqual(os.path.exists(cached_interpreter_dir), True)
                cache._interpreter_from_relpath(identity_str)
                self.assertEqual(os.path.exists(cached_interpreter_dir), False)
