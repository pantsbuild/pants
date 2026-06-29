# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import hashlib
import logging
import os
import shlex
from collections.abc import Iterable
from dataclasses import dataclass
from textwrap import dedent  # noqa: PNT20
from typing import ClassVar, cast

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from pants.backend.python.subsystems import uv as uv_subsystem
from pants.backend.python.subsystems.python_native_code import PythonNativeCodeSubsystem
from pants.backend.python.subsystems.uv import (
    DownloadedUv,
    Uv,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import (
    LockfileFormat,
    PythonLockfileMetadataV8,
)
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.backend.python.util_rules.pex_requirements import (
    LoadedLockfile,
    generate_uv_index_config,
)
from pants.base.build_root import BuildRoot
from pants.core.util_rules import system_binaries
from pants.core.util_rules.env_vars import environment_vars_subset
from pants.core.util_rules.subprocess_environment import SubprocessEnvironmentVars
from pants.core.util_rules.system_binaries import RealpathBinary
from pants.engine.composite_process import Subprocess
from pants.engine.env_vars import EnvironmentVarsRequest
from pants.engine.fs import (
    CreateDigest,
    FileContent,
    MergeDigests,
)
from pants.engine.intrinsics import (
    create_digest,
    get_digest_contents,
    merge_digests,
)
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VenvFromUvLockfileRequest:
    """Request to install packages from a uv lockfile into a virtualenv.

    If subset_req_strings is set, only those requirements (and their transitive deps)
    will be installed via per-requirement dependency groups. If None, the entire lockfile
    is synced.
    """

    lockfile: LoadedLockfile
    python: PythonExecutable
    subset_req_strings: tuple[str, ...] | None = None


@dataclass(frozen=True)
class VenvRepository:
    """A virtualenv directory that Pex can use as a --venv-repository."""

    cache_name: ClassVar[str] = "venv_cache"
    cache_dir: ClassVar[str] = f".cache/{cache_name}/"

    venv_path_suffix: str
    creation_subprocess: Subprocess

    def relpath(self) -> str:
        # The path to the venv in any sandbox that has the venv_cache append-only cache.
        return os.path.join(self.cache_dir, self.venv_path_suffix)

    @classmethod
    def append_only_caches(cls) -> FrozenDict[str, str]:
        return FrozenDict({cls.cache_name: cls.cache_dir})


@dataclass(frozen=True)
class UvEnvironment:
    env: FrozenDict[str, str]


@rule
async def get_uv_environment(
    subprocess_env_vars: SubprocessEnvironmentVars,
    uv_env_aware: Uv.EnvironmentAware,
    python_native_code: PythonNativeCodeSubsystem.EnvironmentAware,
) -> UvEnvironment:
    path = os.pathsep.join(uv_env_aware.path)
    subprocess_env_dict = dict(subprocess_env_vars.vars)

    extra_env = await environment_vars_subset(
        EnvironmentVarsRequest(uv_env_aware.extra_env_vars), **implicitly()
    )

    if "PATH" in subprocess_env_dict:
        path = os.pathsep.join([path, subprocess_env_dict.pop("PATH")])
    return UvEnvironment(
        env=FrozenDict(
            {
                **extra_env,
                "PATH": path,
                **subprocess_env_dict,
                **python_native_code.subprocess_env_vars,
            }
        )
    )


# A utility function to generate a transient, minimal pyproject.toml for uv to interact with.
# The synthetic project name (pants-lockfile-for-*) must not collide with any real requirement.
# uv will include this project as a virtual package in the lockfile, and we set package = false,
# so it won't try to install it.
#
# Per-requirement dependency groups are generated so that `uv sync --only-group <name>` can
# install a subset of requirements during PEX builds, avoiding downloading the entire resolve.
def generate_pyproject_toml(
    resolve: str,
    ics: InterpreterConstraints,
    reqs: Iterable[str],
    indexes: Iterable[str] | None = None,
    sources: Iterable[str] = tuple(),
) -> str:
    def escape_double_quotes(s: str) -> str:
        return s.replace('"', '\\"')

    requires_python = ",".join(str(constraint.specifier) for constraint in ics)
    sorted_reqs = sorted(reqs)
    deps_lines = "\n".join(f'    "{escape_double_quotes(r)}",' for r in sorted_reqs)

    content = dedent(
        """
        [project]
        name = "pants-lockfile-for-{resolve}"
        version = "0.0.0"
        requires-python = "{requires_python}"
        dependencies = [
        {deps_lines}
        ]

        [tool.uv]
        package = false
        """
    ).format(resolve=resolve, requires_python=requires_python, deps_lines=deps_lines)

    # The indexes must be in pyproject.toml so uv can validate the index names in sources.
    # (Technically we only need those referenced in sources and not all of them, but it's fine
    # if the others are mentioned too).
    extra_lines = list(generate_uv_index_config(indexes, "tool.uv.index"))
    extra_lines.append("")

    sources = tuple(sources)
    if sources:
        extra_lines.append("[tool.uv.sources]")
        for source in sources:
            index_name, _, scope = source.partition("=")
            req = Requirement(scope)
            # Markers may contain double-quotes, so we use single quotes in the TOML.
            marker = f", marker = '{req.marker}'" if req.marker else ""
            extra_lines.append(f'{req.name} = {{ index = "{index_name}"{marker} }}')
        extra_lines.append("")

    content += "\n".join(extra_lines)

    # Build per-requirement dependency groups. Each top-level requirement gets its own
    # group named after the canonicalized package name (PEP 503). This allows selective
    # install via `uv sync --only-group <name>` during PEX builds.
    # Multiple specifiers for the same package (e.g. different extras) are accumulated
    # into a single group.
    groups: dict[str, list[str]] = {}
    for r in sorted_reqs:
        try:
            parsed = Requirement(r)
            group_name = canonicalize_name(parsed.name)
            groups.setdefault(group_name, []).append(f'"{escape_double_quotes(r)}"')
        except Exception:
            logger.debug(f"Could not parse requirement {r!r} for dependency group generation")

    if groups:
        group_lines = "\n".join(
            f"{name} = [{', '.join(deps)}]" for name, deps in sorted(groups.items())
        )
        content += f"\n[dependency-groups]\n{group_lines}\n"

    return content


@rule
async def create_venv_repository_from_uv_lockfile(
    request: VenvFromUvLockfileRequest,
    downloaded_uv: DownloadedUv,
    uv_env: UvEnvironment,
    realpath_binary: RealpathBinary,
    buildroot: BuildRoot,
) -> VenvRepository:
    """Install packages from a uv lockfile into a virtualenv.

    When subset_req_strings is provided, only those packages (and their transitive deps)
    are installed using per-requirement dependency groups and --only-group. The --inexact
    flag prevents removal of previously-installed packages, allowing the shared venv to
    accumulate packages across builds.
    """
    if request.lockfile.lockfile_format != LockfileFormat.UV:
        raise ValueError(f"Expected a uv lockfile, got {request.lockfile.lockfile_format}")
    if request.lockfile.metadata is None:
        raise ValueError(
            softwrap(
                f"""
                Cannot install from uv lockfile {request.lockfile.lockfile_path}: metadata is
                missing. uv lockfiles must have a separate metadata file. Please regenerate
                the lockfile by running `{bin_name()} generate-lockfiles`.
                """
            )
        )
    metadata: PythonLockfileMetadataV8 = cast(PythonLockfileMetadataV8, request.lockfile.metadata)

    pyproject_content = generate_pyproject_toml(
        metadata.resolve,
        metadata.valid_for_interpreter_constraints,
        tuple(str(req) for req in metadata.requirements),
    )

    uv_config_digest, uv_lock_contents = await concurrently(
        create_digest(
            CreateDigest(
                (
                    FileContent("pyproject.toml", pyproject_content.encode()),
                    # Nothing to put in config right now, but we need it to be present.
                    FileContent("uv.toml", b""),
                )
            )
        ),
        get_digest_contents(request.lockfile.lockfile_digest),
    )
    uv_lock_content = uv_lock_contents[0].content
    uv_lock_digest = await create_digest(CreateDigest([FileContent("uv.lock", uv_lock_content)]))

    input_digest = await merge_digests(
        MergeDigests(
            (
                downloaded_uv.digest,
                uv_config_digest,
                uv_lock_digest,
            )
        )
    )

    # Build the uv sync arguments depending on whether we're doing a full or subset sync.
    # Selective sync requires the lockfile to have been generated WITH dependency groups
    # baked in (i.e., generated by the new generate_pyproject_toml that emits groups).
    # Old lockfiles won't have [package.dev-dependencies] entries, so --only-group would
    # fail. Detect this by checking for the dev-dependencies section in the lockfile.
    lockfile_has_groups = b"[package.dev-dependencies]" in uv_lock_content

    # Also derive available group names from metadata to catch cases where a target
    # requirement isn't a top-level resolve entry.
    available_groups: set[str] = set()
    for req_str in (str(req) for req in metadata.requirements):
        try:
            available_groups.add(canonicalize_name(Requirement(req_str).name))
        except Exception:
            pass

    subset_group_args: list[str] = []
    if request.subset_req_strings:
        if not lockfile_has_groups:
            logger.warning(
                "Lockfile does not contain dependency group metadata; "
                "falling back to full sync. Regenerate the lockfile with "
                f"`{bin_name()} generate-lockfiles` to enable selective sync."
            )
        else:
            for req_str in request.subset_req_strings:
                try:
                    parsed = Requirement(req_str)
                    group_name = canonicalize_name(parsed.name)
                    if group_name not in available_groups:
                        logger.warning(
                            f"Requirement {req_str!r} (group {group_name!r}) not found "
                            "in lockfile dependency groups; falling back to full sync. "
                            "Consider regenerating the lockfile with "
                            f"`{bin_name()} generate-lockfiles`."
                        )
                        subset_group_args = []
                        break
                    subset_group_args.extend(["--only-group", group_name])
                except Exception:
                    logger.warning(
                        f"Could not parse requirement {req_str!r} for selective sync; "
                        "falling back to full sync."
                    )
                    subset_group_args = []
                    break

    if subset_group_args:
        # Selective sync: install only the requested packages and their transitive deps.
        # --inexact prevents removal of previously-installed packages, allowing the shared
        # venv to accumulate packages across different PEX builds.
        sync_mode_args = ("--inexact", *subset_group_args)
    else:
        # Full sync: install everything in the lockfile.
        # TODO: extras can conflict, so we might need to be more selective.
        sync_mode_args = ("--all-extras",)

    # When using --inexact, we include a lockfile content hash in the venv path so that
    # stale packages from old lockfile versions are not visible to Pex.
    buildroot_entropy = hashlib.sha256(buildroot.path.encode()).hexdigest()
    if subset_group_args:
        lock_hash = hashlib.sha256(uv_lock_content).hexdigest()[:12]
        venv_path_suffix = os.path.join(
            buildroot_entropy, metadata.resolve, request.python.fingerprint, lock_hash
        )
    else:
        # Full sync: uv manages the venv contents exactly, so no hash needed.
        venv_path_suffix = os.path.join(
            buildroot_entropy, metadata.resolve, request.python.fingerprint
        )

    uv_cmd = shlex.join(
        (
            *downloaded_uv.args(),
            "sync",
            "--frozen",
            "--no-install-project",
            *sync_mode_args,
            "--no-progress",
            "--python",
            request.python.path,
        )
    )
    # We use `realpath` to resolve the named cache symlink to an absolute path in whatever
    # environment this process runs in. This gives uv a stable absolute path for the venv
    # so that any entry point scripts it creates exec a valid path that doesn't reference
    # the sandbox.
    command = dedent(
        f"""\
        cache_root="$({realpath_binary.path} {shlex.quote(VenvRepository.cache_dir)})"
        UV_PROJECT_ENVIRONMENT="${{cache_root}}/{venv_path_suffix}" {uv_cmd}
        """
    )

    return VenvRepository(
        venv_path_suffix=venv_path_suffix,
        creation_subprocess=Subprocess(
            command=command,
            input_digest=input_digest,
            env=uv_env.env,
            append_only_caches={
                **downloaded_uv.append_only_caches(),
                **VenvRepository.append_only_caches(),
            },
        ),
    )


def rules():
    return [
        *collect_rules(),
        *uv_subsystem.rules(),
        *system_binaries.rules(),
    ]
