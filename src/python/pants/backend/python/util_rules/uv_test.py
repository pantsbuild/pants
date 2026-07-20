# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys

from pants.backend.python.goals.lockfile import GenerateUvLockfile
from pants.backend.python.goals.lockfile import rules as lockfile_rules
from pants.backend.python.util_rules import uv
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import (
    LockfileFormat,
    PythonLockfileMetadataV8,
)
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.backend.python.util_rules.pex_requirements import LoadedLockfile, Lockfile
from pants.backend.python.util_rules.uv import (
    VenvFromUvLockfileRequest,
    VenvRepository,
    generate_pyproject_toml,
)
from pants.core.environments.target_types import DockerEnvironmentTarget, LocalEnvironmentTarget
from pants.core.goals.generate_lockfiles import GenerateLockfileResult
from pants.core.util_rules import external_tool, subprocess_environment
from pants.core.util_rules.env_vars import rules as env_vars_rules
from pants.engine import composite_process
from pants.engine.composite_process import CompositeProcess
from pants.engine.environment import EnvironmentName
from pants.engine.fs import Digest, DigestContents
from pants.engine.internals.native_engine import FrozenOrderedSet
from pants.engine.process import FallibleProcessResult, Process
from pants.testutil.rule_runner import QueryRule, RuleRunner

RESOLVE_NAME = "test-resolve"


def _make_rule_runner(docker_image: str | None) -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *uv.rules(),
            *pex_rules(),
            *lockfile_rules(),
            *composite_process.rules(),
            *external_tool.rules(),
            *subprocess_environment.rules(),
            *env_vars_rules(),
            QueryRule(VenvRepository, [VenvFromUvLockfileRequest]),
            QueryRule(GenerateLockfileResult, [GenerateUvLockfile]),
            QueryRule(DigestContents, [Digest]),
            QueryRule(Process, [CompositeProcess]),
            QueryRule(FallibleProcessResult, [Process]),
        ],
        target_types=[LocalEnvironmentTarget, DockerEnvironmentTarget],
        inherent_environment=EnvironmentName("test-env") if docker_image else EnvironmentName(None),
    )
    args = [f"--python-resolves={{'{RESOLVE_NAME}': 'uv.lock'}}"]
    if docker_image:
        rule_runner.write_files(
            {"BUILD": f"docker_environment(name='test-env', image='{docker_image}')"}
        )
        rule_runner.set_options(
            [*args, "--environments-preview-names={'test-env': '//:test-env'}"],
            env_inherit={"PATH"},
        )
    else:
        rule_runner.set_options(args, env_inherit={"PATH"})
    return rule_runner


def _create_venv_repository(rule_runner: RuleRunner, python_path: str) -> FallibleProcessResult:
    metadata = PythonLockfileMetadataV8(
        valid_for_interpreter_constraints=InterpreterConstraints(["CPython==3.14.*"]),
        requirements=set(),
        manylinux=None,
        requirement_constraints=set(),
        only_binary=set(),
        no_binary=set(),
        excludes=set(),
        overrides=set(),
        sources=set(),
        lock_style=None,
        complete_platforms=(),
        uploaded_prior_to=None,
        lockfile_format=LockfileFormat.UV,
        resolve=RESOLVE_NAME,
    )

    pyproject = generate_pyproject_toml(
        RESOLVE_NAME, metadata.valid_for_interpreter_constraints, ()
    )
    rule_runner.write_files({"pyproject.toml": pyproject, "uv.toml": ""})
    lock_result = rule_runner.request(
        GenerateLockfileResult,
        [
            GenerateUvLockfile(
                resolve_name=RESOLVE_NAME,
                lockfile_dest="test.lock",
                diff=False,
                requirements=FrozenOrderedSet(),
                find_links=FrozenOrderedSet(),
                interpreter_constraints=InterpreterConstraints.for_fixed_python_version("3.14.*"),
            )
        ],
    )
    uv_lock_content = rule_runner.request(DigestContents, [lock_result.digest])[0].content
    lockfile_digest = rule_runner.make_snapshot({"test.lock": uv_lock_content.decode()}).digest
    loaded_lockfile = LoadedLockfile(
        lockfile_digest,
        "test.lock",
        metadata=metadata,
        requirement_estimate=0,
        lockfile_format=LockfileFormat.UV,
        as_constraints_strings=None,
        original_lockfile=Lockfile(
            "test.lock", url_description_of_origin="test", resolve_name=RESOLVE_NAME
        ),
    )

    venv_repo = rule_runner.request(
        VenvRepository,
        [
            VenvFromUvLockfileRequest(
                lockfile=loaded_lockfile,
                python=PythonExecutable(python_path, fingerprint="00" * 32),
            )
        ],
    )
    process = rule_runner.request(
        Process,
        [
            CompositeProcess(
                [venv_repo.creation_subprocess],
                description="Create venv from uv lockfile",
            )
        ],
    )
    return rule_runner.request(FallibleProcessResult, [process])


def test_local_environment() -> None:
    # Locally, flock is used if present (typically Linux), and pants_lock otherwise
    # (typically macOS, which has no flock binary).
    rule_runner = _make_rule_runner(docker_image=None)
    result = _create_venv_repository(rule_runner, sys.executable)
    assert result.exit_code == 0, result.stderr.decode()


def test_docker_environment_with_flock() -> None:
    # In a docker environment the pants_lock binary is not available in the container, so success
    # proves that the container's flock binary was used.
    rule_runner = _make_rule_runner(docker_image="python:3.14-slim")
    result = _create_venv_repository(rule_runner, "/usr/local/bin/python3")
    assert result.exit_code == 0, result.stderr.decode()
