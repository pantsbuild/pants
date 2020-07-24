# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent
from typing import Iterable

import pytest
from pex.interpreter import PythonInterpreter
from pex.resolver import Unsatisfiable
from pkg_resources import Requirement, WorkingSet

from pants.backend.python.rules import download_pex_bin, pex
from pants.backend.python.rules.pex import Pex, PexRequest, PexRequirements
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.core.util_rules import archive, external_tool
from pants.engine.fs import CreateDigest, Digest, DirectoryToMaterialize, FileContent, MergeDigests
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.init.plugin_resolver import PluginResolver
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.interpreter_selection_utils import (
    PY_36,
    PY_37,
    python_interpreter_path,
    skip_unless_python36_and_python37_present,
)
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_rmtree, touch

DEFAULT_VERSION = "0.0.0"


class PluginResolverTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *pex.rules(),
            *download_pex_bin.rules(),
            *python_native_code.rules(),
            *subprocess_environment.rules(),
            *external_tool.rules(),
            *archive.rules(),
            RootRule(PexRequest),
        )

    def _create_pex(self) -> Pex:
        return self.request_single_product(
            Pex,
            Params(
                PexRequest(
                    output_filename="setup-py-runner.pex",
                    requirements=PexRequirements(["setuptools==44.0.0", "wheel==0.34.2"]),
                ),
                create_options_bootstrapper(args=["--backend-packages=pants.backend.python"]),
                SubprocessEncodingEnvironment(None, None),
                PexBuildEnvironment(tuple(), tuple()),
            ),
        )

    def _run_setup_py(
        self, plugin: str, version: str, setup_py_args: Iterable[str], install_dir: str
    ) -> None:
        pex_obj = self._create_pex()
        source_digest = self.request_single_product(
            Digest,
            CreateDigest(
                [
                    FileContent(
                        "setup.py",
                        dedent(
                            f"""
                    from setuptools import setup

                    setup(name="{plugin}", version="{version or DEFAULT_VERSION}")
                """
                        ).encode(),
                    )
                ]
            ),
        )
        merged_digest = self.request_single_product(
            Digest, MergeDigests([pex_obj.digest, source_digest])
        )

        process = Process(
            argv=("python", "setup-py-runner.pex", "setup.py") + tuple(setup_py_args),
            # We reasonably expect there to be a python interpreter on the test-running
            # process's path.
            env={"PATH": os.getenv("PATH", "")},
            input_digest=merged_digest,
            description="Run setup.py",
            output_directories=("dist/",),
        )
        result = self.request_single_product(ProcessResult, process)
        output_paths = self.scheduler.materialize_directory(
            DirectoryToMaterialize(result.output_digest, path_prefix="output")
        ).output_paths
        safe_mkdir(install_dir)
        for path in output_paths:
            shutil.copy(path, install_dir)

    @contextmanager
    def plugin_resolution(self, *, interpreter=None, chroot=None, plugins=None, sdist=True):
        @contextmanager
        def provide_chroot(existing):
            if existing:
                yield existing, False
            else:
                with temporary_dir() as new_chroot:
                    yield new_chroot, True

        with provide_chroot(chroot) as (root_dir, create_artifacts):
            env = {}
            repo_dir = None
            if plugins:
                repo_dir = os.path.join(root_dir, "repo")
                env.update(
                    PANTS_PYTHON_REPOS_REPOS=f"[{repo_dir!r}]",
                    PANTS_PYTHON_REPOS_INDEXES="[]",
                    PANTS_PYTHON_SETUP_RESOLVER_CACHE_TTL="1",
                )
                plugin_list = []
                for plugin in plugins:
                    version = None
                    if isinstance(plugin, tuple):
                        plugin, version = plugin
                    plugin_list.append(f"{plugin}=={version}" if version else plugin)
                    if create_artifacts:
                        setup_py_args = ["sdist" if sdist else "bdist_wheel", "--dist-dir", "dist/"]
                        self._run_setup_py(plugin, version, setup_py_args, repo_dir)
                env["PANTS_PLUGINS"] = f"[{','.join(map(repr, plugin_list))}]"
                env["PANTS_PLUGIN_CACHE_DIR"] = os.path.join(root_dir, "plugin-cache")

            configpath = os.path.join(root_dir, "pants.toml")
            if create_artifacts:
                touch(configpath)
            args = [f"--pants-config-files=['{configpath}']"]

            options_bootstrapper = OptionsBootstrapper.create(env=env, args=args)
            plugin_resolver = PluginResolver(options_bootstrapper, interpreter=interpreter)
            cache_dir = plugin_resolver.plugin_cache_dir

            working_set = plugin_resolver.resolve(WorkingSet(entries=[]))
            for dist in working_set:
                assert (
                    Path(os.path.realpath(cache_dir))
                    in Path(os.path.realpath(dist.location)).parents
                )

            yield working_set, root_dir, repo_dir, cache_dir

    def test_no_plugins(self) -> None:
        with self.plugin_resolution() as (working_set, _, _, _):
            assert [] == list(working_set)

    def test_plugins_sdist(self) -> None:
        self._do_test_plugins(True)

    def test_plugins_bdist(self) -> None:
        self._do_test_plugins(False)

    def _do_test_plugins(self, sdist: bool) -> None:
        with self.plugin_resolution(plugins=[("jake", "1.2.3"), "jane"], sdist=sdist) as (
            working_set,
            _,
            _,
            cache_dir,
        ):

            def assert_dist_version(name, expected_version):
                dist = working_set.find(Requirement.parse(name))
                assert expected_version == dist.version

            assert 2 == len(working_set.entries)

            assert_dist_version(name="jake", expected_version="1.2.3")
            assert_dist_version(name="jane", expected_version=DEFAULT_VERSION)

    def test_exact_requirements_sdist(self) -> None:
        self._do_test_exact_requirements(True)

    def test_exact_requirements_bdist(self) -> None:
        self._do_test_exact_requirements(False)

    def _do_test_exact_requirements(self, sdist: bool) -> None:
        with self.plugin_resolution(
            plugins=[("jake", "1.2.3"), ("jane", "3.4.5")], sdist=sdist
        ) as results:
            working_set, chroot, repo_dir, cache_dir = results

            # Kill the repo source dir and re-resolve.  If the PluginResolver truly detects exact
            # requirements it should skip any resolves and load directly from the still in-tact cache.
            safe_rmtree(repo_dir)

            with self.plugin_resolution(
                chroot=chroot, plugins=[("jake", "1.2.3"), ("jane", "3.4.5")]
            ) as results2:

                working_set2, _, _, _ = results2

                assert list(working_set) == list(working_set2)

    @skip_unless_python36_and_python37_present
    def test_exact_requirements_interpreter_change_sdist(self) -> None:
        self._do_test_exact_requirements_interpreter_change(True)

    @skip_unless_python36_and_python37_present
    def test_exact_requirements_interpreter_change_bdist(self) -> None:
        self._do_test_exact_requirements_interpreter_change(False)

    def _do_test_exact_requirements_interpreter_change(self, sdist: bool) -> None:
        python36 = PythonInterpreter.from_binary(python_interpreter_path(PY_36))
        python37 = PythonInterpreter.from_binary(python_interpreter_path(PY_37))

        with self.plugin_resolution(
            interpreter=python36, plugins=[("jake", "1.2.3"), ("jane", "3.4.5")], sdist=sdist
        ) as results:

            working_set, chroot, repo_dir, cache_dir = results

            safe_rmtree(repo_dir)
            with pytest.raises(Unsatisfiable):
                with self.plugin_resolution(
                    interpreter=python37,
                    chroot=chroot,
                    plugins=[("jake", "1.2.3"), ("jane", "3.4.5")],
                ):
                    pytest.fail(
                        "Plugin re-resolution is expected for an incompatible interpreter and it is "
                        "expected to fail since we removed the dist `repo_dir` above."
                    )

            # But for a compatible interpreter the exact resolve results should be re-used and load
            # directly from the still in-tact cache.
            with self.plugin_resolution(
                interpreter=python36, chroot=chroot, plugins=[("jake", "1.2.3"), ("jane", "3.4.5")]
            ) as results2:

                working_set2, _, _, _ = results2
                assert list(working_set) == list(working_set2)

    def test_inexact_requirements_sdist(self) -> None:
        self._do_test_inexact_requirements(True)

    def test_inexact_requirements_bdist(self) -> None:
        self._do_test_inexact_requirements(False)

    def _do_test_inexact_requirements(self, sdist: bool) -> None:
        with self.plugin_resolution(plugins=[("jake", "1.2.3"), "jane"], sdist=sdist) as results:

            working_set, chroot, repo_dir, cache_dir = results

            # Kill the cache and the repo source dir and wait past our 1s test TTL, if the PluginResolver
            # truly detects inexact plugin requirements it should skip perma-caching and fall through to
            # a pex resolve and then fail.
            safe_rmtree(repo_dir)
            safe_rmtree(cache_dir)

            with pytest.raises(Unsatisfiable):
                with self.plugin_resolution(chroot=chroot, plugins=[("jake", "1.2.3"), "jane"]):
                    pytest.fail("Should not reach here, should raise first.")
