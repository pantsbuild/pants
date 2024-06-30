# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import shutil
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePath
from textwrap import dedent
from typing import Dict, Iterable, Sequence

import pytest
from pex.interpreter import PythonInterpreter
from pkg_resources import Distribution, Requirement, WorkingSet

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
    python_interpreter_path,
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
        ["--backend-packages=pants.backend.python"],
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
        requirements=PexRequirements(["setuptools==44.0.0", "wheel==0.34.2"]),
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


@contextmanager
def plugin_resolution(
    rule_runner: RuleRunner,
    *,
    interpreter: PythonInterpreter | None = None,
    chroot: str | None = None,
    plugins: Sequence[Plugin] = (),
    requirements: Iterable[str] = (),
    sdist: bool = True,
    working_set_entries: Sequence[Distribution] = (),
    use_pypi: bool = False,
):
    @contextmanager
    def provide_chroot(existing):
        if existing:
            yield existing, False
        else:
            with temporary_dir() as new_chroot:
                yield new_chroot, True

    # Default to resolving with whatever we're currently running with.
    interpreter_constraints = (
        InterpreterConstraints([f"=={interpreter.identity.version_str}"]) if interpreter else None
    )
    artifact_interpreter_constraints = interpreter_constraints or InterpreterConstraints(
        [f"=={'.'.join(map(str, sys.version_info[:3]))}"]
    )

    with provide_chroot(chroot) as (root_dir, create_artifacts):
        env: Dict[str, str] = {}
        repo_dir = os.path.join(root_dir, "repo")

        def _create_artifact(name, version, install_requires):
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
            PANTS_PYTHON_REPOS_REPOS=f"['file://{repo_dir}']",
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
                r = Requirement.parse(requirement)
                _create_artifact(r.key, r.specs[0][1], [])

        configpath = os.path.join(root_dir, "pants.toml")
        if create_artifacts:
            touch(configpath)
        args = ["pants", f"--pants-config-files=['{configpath}']"]

        options_bootstrapper = OptionsBootstrapper.create(env=env, args=args, allow_pantsrc=False)
        complete_env = CompleteEnvironmentVars(
            {**{k: os.environ[k] for k in ["PATH", "HOME", "PYENV_ROOT"] if k in os.environ}, **env}
        )
        bootstrap_scheduler = create_bootstrap_scheduler(options_bootstrapper, EXECUTOR)
        cache_dir = options_bootstrapper.bootstrap_options.for_global_scope().named_caches_dir

        input_working_set = WorkingSet(entries=[])
        for dist in working_set_entries:
            input_working_set.add(dist)
        plugin_resolver = PluginResolver(
            bootstrap_scheduler, interpreter_constraints, input_working_set
        )
        working_set = plugin_resolver.resolve(options_bootstrapper, complete_env, requirements)
        for dist in working_set:
            assert (
                Path(os.path.realpath(cache_dir)) in Path(os.path.realpath(dist.location)).parents
            )

        yield working_set, root_dir, repo_dir


def test_no_plugins(rule_runner: RuleRunner) -> None:
    with plugin_resolution(rule_runner) as (working_set, _, _):
        assert [] == list(working_set)


def test_plugins_sdist(rule_runner: RuleRunner) -> None:
    _do_test_plugins(rule_runner, True)


def test_plugins_bdist(rule_runner: RuleRunner) -> None:
    _do_test_plugins(rule_runner, False)


def _do_test_plugins(rule_runner: RuleRunner, sdist: bool) -> None:
    with plugin_resolution(
        rule_runner,
        plugins=[Plugin("jake", "1.2.3"), Plugin("jane")],
        sdist=sdist,
        requirements=["lib==4.5.6"],
    ) as (
        working_set,
        _,
        _,
    ):

        def assert_dist_version(name, expected_version):
            dist = working_set.find(Requirement.parse(name))
            assert expected_version == dist.version

        assert_dist_version(name="jake", expected_version="1.2.3")
        assert_dist_version(name="jane", expected_version=DEFAULT_VERSION)


def test_exact_requirements_sdist(rule_runner: RuleRunner) -> None:
    _do_test_exact_requirements(rule_runner, True)


def test_exact_requirements_bdist(rule_runner: RuleRunner) -> None:
    _do_test_exact_requirements(rule_runner, False)


def _do_test_exact_requirements(rule_runner: RuleRunner, sdist: bool) -> None:
    with plugin_resolution(
        rule_runner, plugins=[Plugin("jake", "1.2.3"), Plugin("jane", "3.4.5")], sdist=sdist
    ) as results:
        working_set, chroot, repo_dir = results

        # Kill the repo source dir and re-resolve. If the PluginResolver truly detects exact
        # requirements it should skip any resolves and load directly from the still intact
        # cache.
        safe_rmtree(repo_dir)

        with plugin_resolution(
            rule_runner, chroot=chroot, plugins=[Plugin("jake", "1.2.3"), Plugin("jane", "3.4.5")]
        ) as results2:
            working_set2, _, _ = results2

            assert list(working_set) == list(working_set2)


def test_range_deps(rule_runner: RuleRunner) -> None:
    # Test that when a plugin has a range dependency, specifying a working set constrains
    # to a particular version, where otherwise we would get the highest released (2.27.0 in
    # this case).
    with plugin_resolution(
        rule_runner,
        plugins=[Plugin("jane", "3.4.5", ["requests>=2.25.1,<2.28.0"])],
        working_set_entries=[Distribution(project_name="requests", version="2.26.0")],
        # Because we're resolving real distributions, we enable access to pypi.
        use_pypi=True,
    ) as (
        working_set,
        _,
        _,
    ):
        assert "2.26.0" == working_set.find(Requirement.parse("requests")).version


@skip_unless_python38_and_python39_present
def test_exact_requirements_interpreter_change_sdist(rule_runner: RuleRunner) -> None:
    _do_test_exact_requirements_interpreter_change(rule_runner, True)


@skip_unless_python38_and_python39_present
def test_exact_requirements_interpreter_change_bdist(rule_runner: RuleRunner) -> None:
    _do_test_exact_requirements_interpreter_change(rule_runner, False)


def _do_test_exact_requirements_interpreter_change(rule_runner: RuleRunner, sdist: bool) -> None:
    python38 = PythonInterpreter.from_binary(python_interpreter_path(PY_38))
    python39 = PythonInterpreter.from_binary(python_interpreter_path(PY_39))

    with plugin_resolution(
        rule_runner,
        interpreter=python38,
        plugins=[Plugin("jake", "1.2.3"), Plugin("jane", "3.4.5")],
        sdist=sdist,
    ) as results:
        working_set, chroot, repo_dir = results

        safe_rmtree(repo_dir)
        with pytest.raises(ExecutionError):
            with plugin_resolution(
                rule_runner,
                interpreter=python39,
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
            interpreter=python38,
            chroot=chroot,
            plugins=[Plugin("jake", "1.2.3"), Plugin("jane", "3.4.5")],
        ) as results2:
            working_set2, _, _ = results2
            assert list(working_set) == list(working_set2)
