# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.metadata
import os
import shutil
import sys
import textwrap
from collections.abc import Generator, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePath
from textwrap import dedent

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.core.util_rules import external_tool
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests, Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import ProcessResult
from pants.init.options_initializer import create_bootstrap_scheduler
from pants.init.plugin_resolver import PluginResolver
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.python_interpreter_selection import (
    PY_38,
    PY_39,
    skip_unless_python38_and_python39_present,
)
from pants.testutil.rule_runner import EXECUTOR, QueryRule, RuleRunner
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_rmtree, touch
from pants.util.strutil import softwrap

DEFAULT_VERSION = "0.0.0"


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *pex.rules(),
            *external_tool.rules(),
            QueryRule(Pex, [PexRequest]),
            QueryRule(ProcessResult, [PexProcess]),
        ]
    )
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.python",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


def _create_pex(
    rule_runner: RuleRunner,
    interpreter_constraints: InterpreterConstraints,
) -> Pex:
    request = PexRequest(
        output_filename="setup-py-runner.pex",
        internal_only=True,
        requirements=PexRequirements(["setuptools==66.1.0", "wheel==0.37.0"]),
        interpreter_constraints=interpreter_constraints,
    )
    return rule_runner.request(Pex, [request])


def _run_setup_py(
    rule_runner: RuleRunner,
    plugin: str,
    interpreter_constraints: InterpreterConstraints,
    version: str | None,
    install_requires: Sequence[str] | None,
    setup_py_args: Sequence[str],
    install_dir: str,
) -> None:
    pex_obj = _create_pex(rule_runner, interpreter_constraints)
    install_requires_str = f", install_requires={install_requires!r}" if install_requires else ""
    setup_py_file = FileContent(
        "setup.py",
        dedent(
            f"""
                from setuptools import setup

                setup(name="{plugin}", version="{version or DEFAULT_VERSION}"{install_requires_str})
            """
        ).encode(),
    )
    source_digest = rule_runner.request(
        Digest,
        [CreateDigest([setup_py_file])],
    )
    merged_digest = rule_runner.request(Digest, [MergeDigests([pex_obj.digest, source_digest])])

    process = PexProcess(
        pex=pex_obj,
        argv=("setup.py", *setup_py_args),
        input_digest=merged_digest,
        description="Run setup.py",
        output_directories=("dist/",),
    )
    result = rule_runner.request(ProcessResult, [process])
    result_snapshot = rule_runner.request(Snapshot, [result.output_digest])
    rule_runner.scheduler.write_digest(result.output_digest, path_prefix="output")
    safe_mkdir(install_dir)
    for path in result_snapshot.files:
        shutil.copy(PurePath(rule_runner.build_root, "output", path), install_dir)


@dataclass
class Plugin:
    name: str
    version: str | None = None
    install_requires: list[str] | None = None


@dataclass
class MockDistribution:
    name: str
    version: Version

    def create(self, site_packages_path: Path) -> None:
        # Create package directory
        pkg_dir = site_packages_path / self.name
        pkg_dir.mkdir(parents=True, exist_ok=True)

        # Create __init__.py
        (pkg_dir / "__init__.py").write_text(
            textwrap.dedent('''\
            f"""Mock package for testing."""
            __version__ = "{self.version}"

            def mock_function():
                return "Mock function called"
            ''')
        )

        # Create a module
        (pkg_dir / "module1.py").write_text(
            textwrap.dedent("""\
            def test_function():
            return "Test function from module1"
        """)
        )

        # Create dist-info directory (for installed package simulation)
        dist_info = site_packages_path / f"{self.name}-{self.version}.dist-info"
        dist_info.mkdir(exist_ok=True)

        # Create METADATA file
        (dist_info / "METADATA").write_text(
            textwrap.dedent(f"""\
            Metadata-Version: 2.1
            Name: {self.name}
            Version: {self.version}
            Summary: A mock package for testing
            Author: Test Author
            """)
        )

        # Create top_level.txt
        (dist_info / "top_level.txt").write_text(f"{self.name}\n")


@contextmanager
def plugin_resolution(
    rule_runner: RuleRunner,
    *,
    python_version: str | None = None,
    chroot: str | None = None,
    plugins: Sequence[Plugin] = (),
    requirements: Iterable[str] = (),
    sdist: bool = True,
    existing_distributions: Sequence[MockDistribution] = (),
    use_pypi: bool = False,
):
    @contextmanager
    def provide_chroot(existing: str | None) -> Generator[tuple[str, bool]]:
        if existing:
            yield existing, False
        else:
            with temporary_dir(cleanup=False) as new_chroot:
                yield new_chroot, True

    @contextmanager
    def save_sys_path() -> Generator[list[str]]:
        """Restores the previous `sys.path` once context ends."""
        orig_sys_path = sys.path
        sys.path = sys.path[:]
        try:
            yield orig_sys_path
        finally:
            sys.path = orig_sys_path

    # Default to resolving with whatever we're currently running with.
    interpreter_constraints = (
        InterpreterConstraints([f"=={python_version}.*"]) if python_version else None
    )
    artifact_interpreter_constraints = interpreter_constraints or InterpreterConstraints(
        [f"=={'.'.join(map(str, sys.version_info[:3]))}"]
    )

    with provide_chroot(chroot) as (root_dir, create_artifacts), save_sys_path() as saved_sys_path:
        env: dict[str, str] = {}
        repo_dir = os.path.join(root_dir, "repo")

        def _create_artifact(
            name: str, version: str | None, install_requires: Sequence[str] | None
        ) -> None:
            if create_artifacts:
                setup_py_args = ["sdist" if sdist else "bdist_wheel", "--dist-dir", "dist/"]
                _run_setup_py(
                    rule_runner,
                    name,
                    artifact_interpreter_constraints,
                    version,
                    install_requires,
                    setup_py_args,
                    repo_dir,
                )

        env.update(
            PANTS_PYTHON_REPOS_FIND_LINKS=f"['file://{repo_dir}/']",
            PANTS_PYTHON_RESOLVER_CACHE_TTL="1",
        )
        if not use_pypi:
            env.update(PANTS_PYTHON_REPOS_INDEXES="[]")

        if plugins:
            plugin_list = []
            for plugin in plugins:
                version = plugin.version
                plugin_list.append(f"{plugin.name}=={version}" if version else plugin.name)
                _create_artifact(plugin.name, version, plugin.install_requires)
            env["PANTS_PLUGINS"] = f"[{','.join(map(repr, plugin_list))}]"

            for requirement in tuple(requirements):
                r = Requirement(requirement)
                assert len(r.specifier) == 1, (
                    f"Expected requirement {requirement} to only have one comparison."
                )
                specs = next(iter(r.specifier))
                _create_artifact(canonicalize_name(r.name), specs.version, [])

        configpath = os.path.join(root_dir, "pants.toml")
        if create_artifacts:
            touch(configpath)

        args = [
            "pants",
            f"--pants-config-files=['{configpath}']",
        ]

        options_bootstrapper = OptionsBootstrapper.create(env=env, args=args, allow_pantsrc=False)
        complete_env = CompleteEnvironmentVars(
            {**{k: os.environ[k] for k in ["PATH", "HOME", "PYENV_ROOT"] if k in os.environ}, **env}
        )
        bootstrap_scheduler = create_bootstrap_scheduler(options_bootstrapper, EXECUTOR)
        cache_dir = options_bootstrapper.bootstrap_options.for_global_scope().named_caches_dir

        site_packages_path = Path(root_dir, "site-packages")
        expected_distribution_names: set[str] = set()
        for dist in existing_distributions:
            dist.create(site_packages_path)
            expected_distribution_names.add(dist.name)

        plugin_resolver = PluginResolver(
            bootstrap_scheduler, interpreter_constraints, inherit_existing_constraints=False
        )
        plugin_paths = plugin_resolver.resolve(options_bootstrapper, complete_env, requirements)

        for found_dist in importlib.metadata.distributions():
            if found_dist.name in expected_distribution_names:
                assert (
                    Path(os.path.realpath(cache_dir))
                    in Path(os.path.realpath(str(found_dist.locate_file("")))).parents
                )

        yield plugin_paths, root_dir, repo_dir, saved_sys_path


def test_no_plugins(rule_runner: RuleRunner) -> None:
    with plugin_resolution(rule_runner) as (plugin_paths, _, _, saved_sys_path):
        assert len(plugin_paths) == 0
        assert saved_sys_path == sys.path


@pytest.mark.parametrize("sdist", (False, True), ids=("bdist", "sdist"))
def test_plugins(rule_runner: RuleRunner, sdist: bool) -> None:
    with plugin_resolution(
        rule_runner,
        plugins=[Plugin("jake", "1.2.3"), Plugin("jane")],
        sdist=sdist,
        requirements=["lib==4.5.6"],
    ) as (
        _,
        _,
        _,
        _,
    ):

        def assert_dist_version(name: str, expected_version: str) -> None:
            dist = importlib.metadata.distribution(name)
            assert dist.version == expected_version, (
                f"Expected distribution {name} to have version {expected_version}, got {dist.version}"
            )

        assert_dist_version(name="jake", expected_version="1.2.3")
        assert_dist_version(name="jane", expected_version=DEFAULT_VERSION)


@pytest.mark.parametrize("sdist", (False, True), ids=("bdist", "sdist"))
def test_exact_requirements(rule_runner: RuleRunner, sdist: bool) -> None:
    with plugin_resolution(
        rule_runner, plugins=[Plugin("jake", "1.2.3"), Plugin("jane", "3.4.5")], sdist=sdist
    ) as results:
        plugin_paths1, chroot, repo_dir, saved_sys_path = results
        assert len(plugin_paths1) > 0

        # Kill the repo source dir and re-resolve. If the PluginResolver truly detects exact
        # requirements it should skip any resolves and load directly from the still intact
        # cache.
        safe_rmtree(repo_dir)

        with plugin_resolution(
            rule_runner, chroot=chroot, plugins=[Plugin("jake", "1.2.3"), Plugin("jane", "3.4.5")]
        ) as results2:
            plugin_paths2, _, _, _ = results2
            assert plugin_paths1 == plugin_paths2


def test_range_deps(rule_runner: RuleRunner) -> None:
    # Test that when a plugin has a range dependency, specifying a working set constrains
    # to a particular version, where otherwise we would get the highest released (2.27.1 in
    # this case).
    with plugin_resolution(
        rule_runner,
        plugins=[Plugin("jane", "3.4.5", ["requests>=2.25.1,<2.28.0"])],
        existing_distributions=[MockDistribution(name="requests", version=Version("2.26.0"))],
        # Because we're resolving real distributions, we enable access to pypi.
        use_pypi=True,
    ) as (
        _,
        _,
        _,
        _,
    ):
        dist = importlib.metadata.distribution("requests")
        assert "2.27.1" == dist.version


@skip_unless_python38_and_python39_present
@pytest.mark.parametrize("sdist", (False, True), ids=("bdist", "sdist"))
def test_exact_requirements_interpreter_change(rule_runner: RuleRunner, sdist: bool) -> None:
    with plugin_resolution(
        rule_runner,
        python_version=PY_38,
        plugins=[Plugin("jake", "1.2.3"), Plugin("jane", "3.4.5")],
        sdist=sdist,
    ) as results:
        plugin_paths_1, chroot, repo_dir, saved_sys_path = results

        safe_rmtree(repo_dir)
        with pytest.raises(ExecutionError):
            with plugin_resolution(
                rule_runner,
                python_version=PY_39,
                chroot=chroot,
                plugins=[Plugin("jake", "1.2.3"), Plugin("jane", "3.4.5")],
            ):
                pytest.fail(
                    softwrap(
                        """
                            Plugin re-resolution is expected for an incompatible interpreter and it
                            is expected to fail since we removed the dist `repo_dir` above.
                        """
                    )
                )

        # But for a compatible interpreter the exact resolve results should be re-used and load
        # directly from the still in-tact cache.
        with plugin_resolution(
            rule_runner,
            python_version=PY_38,
            chroot=chroot,
            plugins=[Plugin("jake", "1.2.3"), Plugin("jane", "3.4.5")],
        ) as results2:
            plugin_paths_2, _, _, _ = results2
            assert plugin_paths_1 == plugin_paths_2
