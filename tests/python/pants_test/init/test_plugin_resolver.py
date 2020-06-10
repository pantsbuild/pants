# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
from abc import ABCMeta, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent

import pytest
from pex.interpreter import PythonInterpreter
from pex.resolver import Unsatisfiable
from pkg_resources import Requirement, WorkingSet

from pants.init.plugin_resolver import PluginResolver
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.python.setup_py_runner import SetupPyRunner
from pants.testutil.interpreter_selection_utils import (
    PY_36,
    PY_37,
    python_interpreter_path,
    skip_unless_python36_and_python37_present,
)
from pants.testutil.subsystem.util import init_subsystem
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_rmtree, touch

req = Requirement.parse


class Installer(metaclass=ABCMeta):
    def __init__(self, source_dir: Path, install_dir: Path) -> None:
        self._source_dir = source_dir
        self._install_dir = install_dir

    def run(self) -> None:
        init_subsystem(SetupPyRunner.Factory)
        dist = self._create_dist(SetupPyRunner.Factory.create())
        shutil.copy(str(dist), str(self._install_dir))

    @abstractmethod
    def _create_dist(self, runner: SetupPyRunner) -> Path:
        ...


class SdistInstaller(Installer):
    def _create_dist(self, runner: SetupPyRunner) -> Path:
        return runner.sdist(source_dir=self._source_dir)


class WheelInstaller(Installer):
    def _create_dist(self, runner: SetupPyRunner):
        return runner.bdist(source_dir=self._source_dir)


INSTALLERS = [("sdist", SdistInstaller), ("whl", WheelInstaller)]

DEFAULT_VERSION = "0.0.0"


def create_plugin(distribution_repo_dir, plugin, version=None, packager_cls=None):
    distribution_repo_dir = Path(distribution_repo_dir)
    source_dir = distribution_repo_dir.joinpath(plugin)
    source_dir.mkdir(parents=True)
    source_dir.joinpath("setup.py").write_text(
        dedent(
            f"""
            from setuptools import setup


            setup(name="{plugin}", version="{version or DEFAULT_VERSION}")
            """
        )
    )
    packager_cls = packager_cls or SdistInstaller
    packager = packager_cls(source_dir=source_dir, install_dir=distribution_repo_dir)
    packager.run()


@contextmanager
def plugin_resolution(*, interpreter=None, chroot=None, plugins=None, packager_cls=None):
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
                    create_plugin(repo_dir, plugin, version, packager_cls=packager_cls)
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
            assert Path(cache_dir) in Path(dist.location).parents

        yield working_set, root_dir, repo_dir, cache_dir


def test_no_plugins():
    with plugin_resolution() as (working_set, _, _, _):
        assert [] == list(working_set)


@pytest.mark.parametrize("unused_test_name,packager_cls", INSTALLERS)
def test_plugins(unused_test_name, packager_cls):
    with plugin_resolution(plugins=[("jake", "1.2.3"), "jane"], packager_cls=packager_cls) as (
        working_set,
        _,
        _,
        cache_dir,
    ):

        def assert_dist_version(name, expected_version):
            dist = working_set.find(req(name))
            assert expected_version == dist.version

        assert 2 == len(working_set.entries)

        assert_dist_version(name="jake", expected_version="1.2.3")
        assert_dist_version(name="jane", expected_version=DEFAULT_VERSION)


@pytest.mark.parametrize("unused_test_name,packager_cls", INSTALLERS)
def test_exact_requirements(unused_test_name, packager_cls):
    with plugin_resolution(
        plugins=[("jake", "1.2.3"), ("jane", "3.4.5")], packager_cls=packager_cls
    ) as results:
        working_set, chroot, repo_dir, cache_dir = results

        # Kill the repo source dir and re-resolve.  If the PluginResolver truly detects exact
        # requirements it should skip any resolves and load directly from the still in-tact cache.
        safe_rmtree(repo_dir)

        with plugin_resolution(
            chroot=chroot, plugins=[("jake", "1.2.3"), ("jane", "3.4.5")]
        ) as results2:

            working_set2, _, _, _ = results2

            assert list(working_set) == list(working_set2)


@pytest.mark.parametrize("unused_test_name,packager_cls", INSTALLERS)
@skip_unless_python36_and_python37_present
def test_exact_requirements_interpreter_change(unused_test_name, packager_cls):
    python36 = PythonInterpreter.from_binary(python_interpreter_path(PY_36))
    python37 = PythonInterpreter.from_binary(python_interpreter_path(PY_37))

    with plugin_resolution(
        interpreter=python36,
        plugins=[("jake", "1.2.3"), ("jane", "3.4.5")],
        packager_cls=packager_cls,
    ) as results:

        working_set, chroot, repo_dir, cache_dir = results

        safe_rmtree(repo_dir)
        with pytest.raises(Unsatisfiable):
            with plugin_resolution(
                interpreter=python37, chroot=chroot, plugins=[("jake", "1.2.3"), ("jane", "3.4.5")],
            ):
                pytest.fail(
                    "Plugin re-resolution is expected for an incompatible interpreter and it is "
                    "expected to fail since we removed the dist `repo_dir` above."
                )

        # But for a compatible interpreter the exact resolve results should be re-used and load
        # directly from the still in-tact cache.
        with plugin_resolution(
            interpreter=python36, chroot=chroot, plugins=[("jake", "1.2.3"), ("jane", "3.4.5")]
        ) as results2:

            working_set2, _, _, _ = results2
            assert list(working_set) == list(working_set2)


@pytest.mark.parametrize("unused_test_name,packager_cls", INSTALLERS)
def test_inexact_requirements(unused_test_name, packager_cls):
    with plugin_resolution(
        plugins=[("jake", "1.2.3"), "jane"], packager_cls=packager_cls
    ) as results:

        working_set, chroot, repo_dir, cache_dir = results

        # Kill the cache and the repo source dir and wait past our 1s test TTL, if the PluginResolver
        # truly detects inexact plugin requirements it should skip perma-caching and fall through to
        # a pex resolve and then fail.
        safe_rmtree(repo_dir)
        safe_rmtree(cache_dir)

        with pytest.raises(Unsatisfiable):
            with plugin_resolution(chroot=chroot, plugins=[("jake", "1.2.3"), "jane"]):
                pytest.fail("Should not reach here, should raise first.")
