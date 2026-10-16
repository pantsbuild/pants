# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

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
    relativize_local_find_links,
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
from pants.engine.process import FallibleProcessResult, Process, ProcessCacheScope
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.pip_requirement import PipRequirement

RESOLVE_NAME = "test-resolve"


def _make_rule_runner(
    docker_image: str | None,
    named_caches_dir: Path | None = None,
    local_find_links: tuple[str, ...] = (),
) -> RuleRunner:
    rule_runner = RuleRunner(
        bootstrap_args=[f"--named-caches-dir={named_caches_dir}"] if named_caches_dir else [],
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
    if local_find_links:
        find_links = [f"file://{rule_runner.build_root}/{path}" for path in local_find_links]
        args.append(f"--python-repos-find-links={find_links}")
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


def _generate_uv_lockfile(rule_runner: RuleRunner, requirements: tuple[str, ...] = ()) -> bytes:
    lock_result = rule_runner.request(
        GenerateLockfileResult,
        [
            GenerateUvLockfile(
                resolve_name=RESOLVE_NAME,
                lockfile_dest="test.lock",
                diff=False,
                requirements=FrozenOrderedSet(requirements),
                find_links=FrozenOrderedSet(),
                interpreter_constraints=InterpreterConstraints.for_fixed_python_version("3.14.*"),
            )
        ],
    )
    return rule_runner.request(DigestContents, [lock_result.digest])[0].content


def _create_venv_repository(
    rule_runner: RuleRunner,
    python_path: str,
    cache_scope: ProcessCacheScope = ProcessCacheScope.SUCCESSFUL,
    requirements: tuple[str, ...] = (),
) -> tuple[VenvRepository, FallibleProcessResult]:
    metadata = PythonLockfileMetadataV8(
        valid_for_interpreter_constraints=InterpreterConstraints(["CPython==3.14.*"]),
        requirements={PipRequirement.parse(requirement) for requirement in requirements},
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
        RESOLVE_NAME, metadata.valid_for_interpreter_constraints, requirements
    )
    rule_runner.write_files({"pyproject.toml": pyproject, "uv.toml": ""})
    uv_lock_content = _generate_uv_lockfile(rule_runner, requirements)
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
                cache_scope=cache_scope,
            )
        ],
    )
    return venv_repo, rule_runner.request(FallibleProcessResult, [process])


def test_local_environment() -> None:
    # Locally, flock is used if present (typically Linux), and pants_lock otherwise
    # (typically macOS, which has no flock binary).
    rule_runner = _make_rule_runner(docker_image=None)
    _, result = _create_venv_repository(rule_runner, sys.executable)
    assert result.exit_code == 0, result.stderr.decode()


def test_docker_environment_with_flock() -> None:
    # In a docker environment the pants_lock binary is not available in the container, so success
    # proves that the container's flock binary was used.
    rule_runner = _make_rule_runner(docker_image="python:3.14-slim")
    _, result = _create_venv_repository(rule_runner, "/usr/local/bin/python3")
    assert result.exit_code == 0, result.stderr.decode()


def test_existing_venv_is_reused(tmp_path: Path) -> None:
    named_caches_dir = tmp_path / "named_caches"
    rule_runner = _make_rule_runner(docker_image=None, named_caches_dir=named_caches_dir)

    venv_repo, result = _create_venv_repository(
        rule_runner, sys.executable, cache_scope=ProcessCacheScope.PER_SESSION
    )
    assert result.exit_code == 0, result.stderr.decode()

    # The venv lives at `<suffix>.venv`, published by a `<suffix>` symlink once it is complete.
    venv_link = named_caches_dir / VenvRepository.cache_name / venv_repo.venv_path_suffix
    assert venv_link.is_symlink()
    venv_dir = venv_link.resolve()
    assert venv_dir.is_dir()

    # Recreating the venv entails deleting the existing one, so this sentinel survives only if
    # the second request leaves the venv alone.
    sentinel = venv_dir / "pants_reuse_sentinel"
    sentinel.touch()

    # A new session, so that the process actually runs again instead of being memoized.
    rule_runner.set_session_values({})
    _, result = _create_venv_repository(
        rule_runner, sys.executable, cache_scope=ProcessCacheScope.PER_SESSION
    )
    assert result.exit_code == 0, result.stderr.decode()
    assert sentinel.exists(), "The venv was recreated instead of being reused."


def test_relativize_local_find_links() -> None:
    assert relativize_local_find_links(
        [
            "file:///repo/wheels",
            "/repo/vendored/wheels",
            "file:///repository/wheels",
            "/elsewhere/wheels",
            "https://example.com/wheels/",
        ],
        "/repo",
    ) == (
        (
            "wheels",
            "vendored/wheels",
            "file:///repository/wheels",
            "/elsewhere/wheels",
            "https://example.com/wheels/",
        ),
        ("wheels", "vendored/wheels"),
    )


def _write_local_wheel(rule_runner: RuleRunner, directory: str) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as wheel:
        wheel.writestr("my_wheel/__init__.py", "")
        wheel.writestr(
            "my_wheel-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: my-wheel\nVersion: 0.1.0\n",
        )
        wheel.writestr(
            "my_wheel-0.1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: pants-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        wheel.writestr("my_wheel-0.1.0.dist-info/RECORD", "")
    rule_runner.write_files({f"{directory}/my_wheel-0.1.0-py3-none-any.whl": buffer.getvalue()})


def test_local_find_links_are_portable(tmp_path: Path) -> None:
    named_caches_dir = tmp_path / "named_caches"
    rule_runner = _make_rule_runner(
        docker_image=None, named_caches_dir=named_caches_dir, local_find_links=("wheels",)
    )
    _write_local_wheel(rule_runner, "wheels")
    requirements = ("my-wheel==0.1.0",)

    uv_lock_content = _generate_uv_lockfile(rule_runner, requirements).decode()
    assert 'source = { registry = "wheels" }' in uv_lock_content
    assert rule_runner.build_root not in uv_lock_content

    venv_repo, result = _create_venv_repository(
        rule_runner,
        sys.executable,
        cache_scope=ProcessCacheScope.PER_SESSION,
        requirements=requirements,
    )
    assert result.exit_code == 0, result.stderr.decode()
    venv_dir = (named_caches_dir / VenvRepository.cache_name / venv_repo.venv_path_suffix).resolve()
    assert list(venv_dir.glob("lib/python*/site-packages/my_wheel-0.1.0.dist-info"))
