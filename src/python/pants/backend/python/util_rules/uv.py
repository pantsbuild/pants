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
    ResolveConfigRequest,
    determine_resolve_config,
    generate_uv_index_config,
)
from pants.base.build_root import BuildRoot
from pants.core.util_rules import system_binaries
from pants.core.util_rules.env_vars import environment_vars_subset
from pants.core.util_rules.subprocess_environment import SubprocessEnvironmentVars
from pants.core.util_rules.system_binaries import (
    LnBinary,
    MaybeFlockBinary,
    RealpathBinary,
    RmBinary,
)
from pants.engine.composite_process import Subprocess
from pants.engine.env_vars import EnvironmentVarsRequest
from pants.engine.fs import (
    CreateDigest,
    FileContent,
    MergeDigests,
    PathGlobs,
)
from pants.engine.intrinsics import (
    create_digest,
    get_digest_contents,
    merge_digests,
    path_globs_to_digest,
)
from pants.engine.pants_lock import pants_lock_bin
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VenvFromUvLockfileRequest:
    """Request to install all packages from a uv lockfile into a virtualenv."""

    lockfile: LoadedLockfile
    python: PythonExecutable
    # If set, install packages for this uv --python-platform value (e.g. "x86_64-unknown-linux-gnu")
    # instead of the local platform. python is still the local interpreter used to create the venv.
    uv_platform: str | None = None


@dataclass(frozen=True)
class VenvRepository:
    """A virtualenv directory that Pex can use as a --venv-repository."""

    cache_name: ClassVar[str] = "venv_cache"
    cache_dir: ClassVar[str] = f".cache/{cache_name}"

    venv_path_suffix: str
    creation_subprocess: Subprocess

    def relpath(self) -> str:
        # The path to the venv in any sandbox that has the venv_cache append-only cache.
        return os.path.join(self.cache_dir, self.venv_path_suffix)

    @classmethod
    def append_only_caches(cls) -> FrozenDict[str, str]:
        return FrozenDict({cls.cache_name: cls.cache_dir})


def relativize_local_find_links(
    find_links: Iterable[str], buildroot: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Rewrite find-links dirs under the buildroot to buildroot-relative paths.

    uv records find-links paths verbatim in uv.lock, so absolute paths would tie the lockfile (and
    every process that consumes it) to one checkout location. Returns the rewritten find-links and
    the relative dirs, whose contents must be in the uv process sandbox.
    """
    rewritten: list[str] = []
    local_dirs: list[str] = []
    for find_link in find_links:
        path = find_link.removeprefix("file://")
        if os.path.isabs(path) and os.path.commonpath((path, buildroot)) == buildroot:
            relative_dir = os.path.relpath(path, buildroot)
            rewritten.append(relative_dir)
            local_dirs.append(relative_dir)
        else:
            rewritten.append(find_link)
    return tuple(rewritten), tuple(local_dirs)


def local_find_links_globs(local_dirs: Iterable[str]) -> PathGlobs:
    return PathGlobs(os.path.join(local_dir, "*") for local_dir in local_dirs)


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
def generate_pyproject_toml(
    resolve: str,
    ics: InterpreterConstraints,
    reqs: Iterable[str],
    indexes: Iterable[str] | None = None,
    find_links: Iterable[str] | None = None,
    sources: Iterable[str] = tuple(),
) -> str:
    def escape_double_quotes(s: str) -> str:
        return s.replace('"', '\\"')

    requires_python = ",".join(str(constraint.specifier) for constraint in ics)
    deps_lines = "\n".join(f'    "{escape_double_quotes(r)}",' for r in sorted(reqs))

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
    extra_lines = list(generate_uv_index_config(indexes, find_links, "tool.uv.index"))
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

    return content


@rule
async def create_venv_repository_from_uv_lockfile(
    request: VenvFromUvLockfileRequest,
    downloaded_uv: DownloadedUv,
    uv_env: UvEnvironment,
    ln_binary: LnBinary,
    realpath_binary: RealpathBinary,
    rm_binary: RmBinary,
    maybe_flock_binary: MaybeFlockBinary,
    buildroot: BuildRoot,
    level: LogLevel,
) -> VenvRepository:
    """Install all packages from a uv lockfile into a virtualenv."""
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
    resolve_config = await determine_resolve_config(
        ResolveConfigRequest(metadata.resolve), **implicitly()
    )

    find_links, local_find_links_dirs = relativize_local_find_links(
        resolve_config.find_links, buildroot.path
    )
    pyproject_content = generate_pyproject_toml(
        metadata.resolve,
        metadata.valid_for_interpreter_constraints,
        tuple(str(req) for req in metadata.requirements),
        indexes=resolve_config.indexes,
        # NB: At lockfile generation time we pass in extra find_links from the target.
        #  That information is not easily available to us here, so we omit it.
        #  This is OK in practice because those extra find_links are only used to inject
        #  https://wheels.pantsbuild.org/simple for pants_requirements() targets.
        #  We know that those are not referenced by name in any `sources`, and that
        # they don't involve auth, so they are not strictly needed after lockfile generation.
        # TODO: Get rid of "extra find_links" entirely, and simply hard-code an explicit
        #  source for pants_requirements.
        find_links=find_links,
        sources=resolve_config.sources,
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
    uv_lock_digest, find_links_digest = await concurrently(
        create_digest(CreateDigest([FileContent("uv.lock", uv_lock_contents[0].content)])),
        path_globs_to_digest(local_find_links_globs(local_find_links_dirs)),
    )

    input_digest = await merge_digests(
        MergeDigests(
            (
                downloaded_uv.digest,
                uv_config_digest,
                uv_lock_digest,
                find_links_digest,
            )
        )
    )

    extra_uv_args = ["--python", request.python.path]
    if request.uv_platform is not None:
        extra_uv_args.extend(["--python-platform", request.uv_platform])

    sync_env = {"UV_NO_INSTALLER_METADATA": "1"}

    # NB: If adding to extra_uv_args, add to the entropy if necessary.
    # Note that uv_env.env is not in the entropy to avoid churn due to, e.g., PATH changes.
    # TODO: Selectively add relevant env vars to the entropy?
    entropy = hashlib.sha256()
    entropy.update(request.python.fingerprint.encode())
    entropy.update(b"\0")
    entropy.update((request.uv_platform or "").encode())
    entropy.update(b"\0")
    entropy.update(input_digest.fingerprint.encode())
    for name, value in sorted(sync_env.items()):
        entropy.update(f"\0{name}={value}".encode())
    venv_path_suffix = entropy.hexdigest()

    uv_cmd = shlex.join(
        (
            *downloaded_uv.args(),
            "sync",
            "--frozen",
            *(["--verbose"] if level >= LogLevel.DEBUG else []),  # type: ignore[operator]
            "--no-install-project",
            # TODO: extras can conflict, so we might need to be more selective.
            "--all-extras",
            "--no-progress",
            *extra_uv_args,
        )
    )
    # We use `realpath` to resolve the named cache symlink to an absolute path in whatever
    # environment this process runs in. This gives uv a stable absolute path for the venv
    # so that any entry point scripts it creates exec a valid path that doesn't reference
    # the sandbox.
    #
    # We lock around the `uv sync` call for performance: the initial sync is expected to be
    # expensive, whereas subsequent syncs with the same args and lockfile are very fast no-ops,
    # so serializing them is possibly preferable to multiple concurrent syncs that may redo a lot
    # of work (in the optimistic scenario they may use each others' cached work items, but in the
    # pessimistic scenario they might race on doing the same work items in near lockstep...).
    #
    # The local platform will always have pants_lock, since we bundle it with Pants.
    # A Linux platform should normally have flock. So the cases where neither binary is available
    # are a remote platform that isn't Linux (unlikely) or a very constrained Linux, that doesn't
    # have flock. We error in these cases. If a user encounters this error they must ensure that
    # flock is available on their remote executors.
    flock = (
        maybe_flock_binary.flock_binary.path
        if maybe_flock_binary.flock_binary
        else "/flock/not/found"
    )
    pants_lock = pants_lock_bin()
    command = dedent(
        f"""\
        cache_root="$({realpath_binary.path} {shlex.quote(VenvRepository.cache_dir)})"
        [ -n "${{cache_root}}" ] || exit 1
        project_env_link="${{cache_root}}/{venv_path_suffix}"
        project_env="${{project_env_link}}.venv"

        # Check if the symlink doesn't exist, or exists but is dangling.
        if [ ! -L "${{project_env_link}}" ] || [ ! -e "${{project_env_link}}" ]; then
            lock_path="${{project_env}}.lock"
            (
            if [ -x "{flock}" ]; then
                {flock} 200 || exit 1
            elif [ -x "{pants_lock}" ]; then
                {pants_lock} 200 || exit 1
            else
                echo "ERROR: No flock or pants_lock binary found on system executing a uv process. " \
                    "Please ensure flock is installed on this host and available on " \
                    "[system-binaries].system_binary_paths." >&2
                exit 1
            fi
            # Now that we hold the lock, create the venv and symlink if it doesn't already exist
            # (or exists and is dangling).
            if [ ! -L "${{project_env_link}}" ] || [ ! -e "${{project_env_link}}" ]; then
                {rm_binary.path} -rf "${{project_env_link}}"
                {rm_binary.path} -rf "${{project_env}}"
                # We symlink instead of renaming since absolute paths have been baked into the venv
                # (see realpath comment above) and we want those to be unbroken.
                # Note that we know that project_env_link doesn't exist, so `ln -s` is atomic.
                UV_PROJECT_ENVIRONMENT="${{project_env}}" {uv_cmd} && {ln_binary.path} -s "${{project_env}}" "${{project_env_link}}"
            fi
            ) 200>"${{lock_path}}" || exit $?
        fi
        """
    )

    return VenvRepository(
        venv_path_suffix=venv_path_suffix,
        creation_subprocess=Subprocess(
            command=command,
            input_digest=input_digest,
            env=FrozenDict({**uv_env.env, **sync_env}),
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
