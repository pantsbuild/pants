# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
from contextlib import contextmanager
from pathlib import Path, PurePath
from textwrap import dedent
from typing import Dict, Iterable, Optional

import pytest
from pex.interpreter import PythonInterpreter
from pkg_resources import Requirement, WorkingSet

from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexProcess,
    PexRequest,
    PexRequirements,
)
from pants.core.util_rules import archive, external_tool
from pants.engine.environment import CompleteEnvironment
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests, Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import Process, ProcessResult
from pants.init.options_initializer import create_bootstrap_scheduler
from pants.init.plugin_resolver import PluginResolver
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.python_interpreter_selection import (
    PY_36,
    PY_37,
    python_interpreter_path,
    skip_unless_python36_and_python37_present,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_rmtree, touch

DEFAULT_VERSION = "0.0.0"


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *pex.rules(),
            *external_tool.rules(),
            *archive.rules(),
            QueryRule(Pex, [PexRequest]),
            QueryRule(Process, [PexProcess]),
            QueryRule(ProcessResult, [Process]),
        ]
    )
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


def _create_pex(
    rule_runner: RuleRunner,
    interpreter_constraints: PexInterpreterConstraints,
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
    interpreter_constraints: PexInterpreterConstraints,
    version: Optional[str],
    setup_py_args: Iterable[str],
    install_dir: str,
) -> None:
    pex_obj = _create_pex(rule_runner, interpreter_constraints)
    setup_py_file = FileContent(
        "setup.py",
        dedent(
            f"""
                from setuptools import setup

                setup(name="{plugin}", version="{version or DEFAULT_VERSION}")
            """
        ).encode(),
    )
    source_digest = rule_runner.request(
        Digest,
        [CreateDigest([setup_py_file])],
    )
    merged_digest = rule_runner.request(Digest, [MergeDigests([pex_obj.digest, source_digest])])

    # This should run the Pex using the same interpreter used to create it. We must set the `PATH` so that the shebang
    # works.
    process = Process(
        argv=("./setup-py-runner.pex", "setup.py", *setup_py_args),
        env={k: os.environ[k] for k in ["PATH", "HOME", "PYENV_ROOT"] if k in os.environ},
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


@contextmanager
def plugin_resolution(
    rule_runner: RuleRunner, *, interpreter=None, chroot=None, plugins=None, sdist=True
):
    @contextmanager
    def provide_chroot(existing):
        if existing:
            yield existing, False
        else:
            with temporary_dir() as new_chroot:
                yield new_chroot, True

    interpreter_constraints = (
        PexInterpreterConstraints([f"=={interpreter.identity.version_str}"])
        if interpreter
        else PexInterpreterConstraints([">=3.7"])
    )

    with provide_chroot(chroot) as (root_dir, create_artifacts):
        env: Dict[str, str] = {}
        repo_dir = None
        if plugins:
            repo_dir = os.path.join(root_dir, "repo")
            env.update(
                PANTS_PYTHON_REPOS_REPOS=f"['file://{repo_dir}']",
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
                    _run_setup_py(
                        rule_runner,
                        plugin,
                        interpreter_constraints,
                        version,
                        setup_py_args,
                        repo_dir,
                    )
            env["PANTS_PLUGINS"] = f"[{','.join(map(repr, plugin_list))}]"

        configpath = os.path.join(root_dir, "pants.toml")
        if create_artifacts:
            touch(configpath)
        args = [f"--pants-config-files=['{configpath}']"]

        options_bootstrapper = OptionsBootstrapper.create(env=env, args=args, allow_pantsrc=False)
        complete_env = CompleteEnvironment(
            {**{k: os.environ[k] for k in ["PATH", "HOME", "PYENV_ROOT"] if k in os.environ}, **env}
        )
        bootstrap_scheduler = create_bootstrap_scheduler(options_bootstrapper)
        plugin_resolver = PluginResolver(
            bootstrap_scheduler, interpreter_constraints=interpreter_constraints
        )
        cache_dir = options_bootstrapper.bootstrap_options.for_global_scope().named_caches_dir

        working_set = plugin_resolver.resolve(
            options_bootstrapper, complete_env, WorkingSet(entries=[])
        )
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
    with plugin_resolution(rule_runner, plugins=[("jake", "1.2.3"), "jane"], sdist=sdist) as (
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
        rule_runner, plugins=[("jake", "1.2.3"), ("jane", "3.4.5")], sdist=sdist
    ) as results:
        working_set, chroot, repo_dir = results

        # Kill the repo source dir and re-resolve.  If the PluginResolver truly detects exact
        # requirements it should skip any resolves and load directly from the still intact
        # cache.
        safe_rmtree(repo_dir)

        with plugin_resolution(
            rule_runner, chroot=chroot, plugins=[("jake", "1.2.3"), ("jane", "3.4.5")]
        ) as results2:

            working_set2, _, _ = results2

            assert list(working_set) == list(working_set2)


@skip_unless_python36_and_python37_present
def test_exact_requirements_interpreter_change_sdist(rule_runner: RuleRunner) -> None:
    _do_test_exact_requirements_interpreter_change(rule_runner, True)


@skip_unless_python36_and_python37_present
def test_exact_requirements_interpreter_change_bdist(rule_runner: RuleRunner) -> None:
    _do_test_exact_requirements_interpreter_change(rule_runner, False)


def _do_test_exact_requirements_interpreter_change(rule_runner: RuleRunner, sdist: bool) -> None:
    python36 = PythonInterpreter.from_binary(python_interpreter_path(PY_36))
    python37 = PythonInterpreter.from_binary(python_interpreter_path(PY_37))

    with plugin_resolution(
        rule_runner,
        interpreter=python36,
        plugins=[("jake", "1.2.3"), ("jane", "3.4.5")],
        sdist=sdist,
    ) as results:

        working_set, chroot, repo_dir = results

        safe_rmtree(repo_dir)
        with pytest.raises(ExecutionError):
            with plugin_resolution(
                rule_runner,
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
        with plugin_resolution(
            rule_runner,
            interpreter=python36,
            chroot=chroot,
            plugins=[("jake", "1.2.3"), ("jane", "3.4.5")],
        ) as results2:

            working_set2, _, _ = results2
            assert list(working_set) == list(working_set2)
