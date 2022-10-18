# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import json
import logging
import os
import shlex
from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent
from typing import Iterable, Iterator, Mapping, TypeVar

import packaging.specifiers
import packaging.version
from pkg_resources import Requirement

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    MainSpecification,
    PexCompletePlatformsField,
    PexLayout,
)
from pants.backend.python.target_types import PexPlatformsField as PythonPlatformsField
from pants.backend.python.util_rules import pex_cli, pex_requirements
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex_cli import PexCliProcess, PexPEX
from pants.backend.python.util_rules.pex_environment import (
    CompletePexEnvironment,
    PexEnvironment,
    PexSubsystem,
    PythonExecutable,
)
from pants.backend.python.util_rules.pex_requirements import (
    EntireLockfile,
    LoadedLockfile,
    LoadedLockfileRequest,
    Lockfile,
)
from pants.backend.python.util_rules.pex_requirements import (
    PexRequirements as PexRequirements,  # Explicit re-export.
)
from pants.backend.python.util_rules.pex_requirements import (
    ResolvePexConfig,
    ResolvePexConfigRequest,
    validate_metadata,
)
from pants.core.target_types import FileSourceField
from pants.core.util_rules.environments import EnvironmentTarget
from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.collection import Collection, DeduplicatedCollection
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.native_engine import Snapshot
from pants.engine.internals.selectors import MultiGet
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, collect_rules, rule, rule_helper
from pants.engine.target import HydratedSources, HydrateSourcesRequest, SourcesField, Targets
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.strutil import pluralize, softwrap

logger = logging.getLogger(__name__)


class PexPlatforms(DeduplicatedCollection[str]):
    sort_input = True

    @classmethod
    def create_from_platforms_field(cls, field: PythonPlatformsField) -> PexPlatforms:
        return cls(field.value or ())

    def generate_pex_arg_list(self) -> list[str]:
        args = []
        for platform in self:
            args.extend(["--platform", platform])
        return args


class CompletePlatforms(DeduplicatedCollection[str]):
    sort_input = True

    def __init__(self, iterable: Iterable[str] = (), *, digest: Digest = EMPTY_DIGEST):
        super().__init__(iterable)
        self._digest = digest

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot) -> CompletePlatforms:
        return cls(snapshot.files, digest=snapshot.digest)

    @property
    def digest(self) -> Digest:
        return self._digest

    def generate_pex_arg_list(self) -> Iterator[str]:
        for path in self:
            yield "--complete-platform"
            yield path


@rule
async def digest_complete_platforms(
    complete_platforms: PexCompletePlatformsField,
) -> CompletePlatforms:
    original_file_targets = await Get(
        Targets,
        UnparsedAddressInputs,
        complete_platforms.to_unparsed_address_inputs(),
    )
    original_files_sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(tgt.get(SourcesField), for_sources_types=(FileSourceField,)),
        )
        for tgt in original_file_targets
    )
    snapshot = await Get(
        Snapshot, MergeDigests(sources.snapshot.digest for sources in original_files_sources)
    )
    return CompletePlatforms.from_snapshot(snapshot)


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexRequest(EngineAwareParameter):
    output_filename: str
    internal_only: bool
    layout: PexLayout
    python: PythonExecutable | None
    requirements: PexRequirements | EntireLockfile
    interpreter_constraints: InterpreterConstraints
    platforms: PexPlatforms
    complete_platforms: CompletePlatforms
    sources: Digest | None
    additional_inputs: Digest
    main: MainSpecification | None
    additional_args: tuple[str, ...]
    pex_path: tuple[Pex, ...]
    description: str | None = dataclasses.field(compare=False)

    def __init__(
        self,
        *,
        output_filename: str,
        internal_only: bool,
        layout: PexLayout | None = None,
        python: PythonExecutable | None = None,
        requirements: PexRequirements | EntireLockfile = PexRequirements(),
        interpreter_constraints=InterpreterConstraints(),
        platforms=PexPlatforms(),
        complete_platforms=CompletePlatforms(),
        sources: Digest | None = None,
        additional_inputs: Digest | None = None,
        main: MainSpecification | None = None,
        additional_args: Iterable[str] = (),
        pex_path: Iterable[Pex] = (),
        description: str | None = None,
    ) -> None:
        """A request to create a PEX from its inputs.

        :param output_filename: The name of the built Pex file, which typically should end in
            `.pex`.
        :param internal_only: Whether we ever materialize the Pex and distribute it directly
            to end users, such as with the `binary` goal. Typically, instead, the user never
            directly uses the Pex, e.g. with `lint` and `test`. If True, we will use a Pex setting
            that results in faster build time but compatibility with fewer interpreters at runtime.
        :param layout: The filesystem layout to create the PEX with.
        :param python: A particular PythonExecutable to use, which must match any relevant
            interpreter_constraints.
        :param requirements: The requirements that the PEX should contain.
        :param interpreter_constraints: Any constraints on which Python versions may be used.
        :param platforms: Which abbreviated platforms should be supported. Setting this value will
            cause interpreter constraints to not be used at PEX build time because platforms already
            constrain the valid Python versions, e.g. by including `cp36m` in the platform string.
            Unfortunately this also causes interpreter constraints to not be embedded in the built
            PEX for use at runtime which can lead to problems.
            See: https://github.com/pantsbuild/pants/issues/13904.
        :param complete_platforms: Which complete platforms should be supported. Setting this value
            will cause interpreter constraints to not be used at PEX build time because complete
            platforms completely constrain the valid Python versions. Unfortunately this also causes
            interpreter constraints to not be embedded in the built PEX for use at runtime which can
            lead to problems. See: https://github.com/pantsbuild/pants/issues/13904.
        :param sources: Any source files that should be included in the Pex.
        :param additional_inputs: Any inputs that are not source files and should not be included
            directly in the Pex, but should be present in the environment when building the Pex.
        :param main: The main for the built Pex, equivalent to Pex's `-e` or '-c' flag. If
            left off, the Pex will open up as a REPL.
        :param additional_args: Any additional Pex flags.
        :param pex_path: Pex files to add to the PEX_PATH.
        :param description: A human-readable description to render in the dynamic UI when building
            the Pex.
        """
        self.output_filename = output_filename
        self.internal_only = internal_only
        # Use any explicitly requested layout, or Packed for internal PEXes (which is a much
        # friendlier layout for the CAS than Zipapp.)
        self.layout = layout or (PexLayout.PACKED if internal_only else PexLayout.ZIPAPP)
        self.python = python
        self.requirements = requirements
        self.interpreter_constraints = interpreter_constraints
        self.platforms = platforms
        self.complete_platforms = complete_platforms
        self.sources = sources
        self.additional_inputs = additional_inputs or EMPTY_DIGEST
        self.main = main
        self.additional_args = tuple(additional_args)
        self.pex_path = tuple(pex_path)
        self.description = description

        self.__post_init__()

    def __post_init__(self):
        if self.internal_only and self.platforms:
            raise ValueError(
                softwrap(
                    f"""
                    Internal only PEXes can only constrain interpreters with interpreter_constraints.
                    Given platform constraints {self.platforms} for internal only pex request:
                    {self}.
                    """
                )
            )
        if self.internal_only and self.complete_platforms:
            raise ValueError(
                softwrap(
                    f"""
                    Internal only PEXes can only constrain interpreters with interpreter_constraints.
                    Given complete_platform constraints {self.complete_platforms} for internal only
                    pex request: {self}.
                    """
                )
            )
        if self.python and self.platforms:
            raise ValueError(
                softwrap(
                    f"""
                    Only one of platforms or a specific interpreter may be set. Got
                    both {self.platforms} and {self.python}.
                    """
                )
            )
        if self.python and self.complete_platforms:
            raise ValueError(
                softwrap(
                    f"""
                    Only one of complete_platforms or a specific interpreter may be set. Got
                    both {self.complete_platforms} and {self.python}.
                    """
                )
            )
        if self.python and self.interpreter_constraints:
            raise ValueError(
                softwrap(
                    f"""
                    Only one of interpreter_constraints or a specific interpreter may be set. Got
                    both {self.interpreter_constraints} and {self.python}.
                    """
                )
            )

    def debug_hint(self) -> str:
        return self.output_filename


@dataclass(frozen=True)
class OptionalPexRequest:
    maybe_pex_request: PexRequest | None


@dataclass(frozen=True)
class Pex:
    """Wrapper for a digest containing a pex file created with some filename."""

    digest: Digest
    name: str
    python: PythonExecutable | None


@dataclass(frozen=True)
class OptionalPex:
    maybe_pex: Pex | None


@rule(desc="Find Python interpreter for constraints", level=LogLevel.DEBUG)
async def find_interpreter(
    interpreter_constraints: InterpreterConstraints,
    pex_subsystem: PexSubsystem,
    env_target: EnvironmentTarget,
) -> PythonExecutable:
    formatted_constraints = " OR ".join(str(constraint) for constraint in interpreter_constraints)
    result = await Get(
        ProcessResult,
        PexCliProcess(
            description=f"Find interpreter for constraints: {formatted_constraints}",
            subcommand=(),
            # Here, we run the Pex CLI with no requirements, which just selects an interpreter.
            # Normally, this would start an isolated repl. By passing `--`, we force the repl to
            # instead act as an interpreter (the selected one) and tell us about itself. The upshot
            # is we run the Pex interpreter selection logic unperturbed but without resolving any
            # distributions.
            extra_args=(
                *interpreter_constraints.generate_pex_arg_list(),
                "--",
                "-c",
                # N.B.: The following code snippet must be compatible with Python 2.7 and
                # Python 3.5+.
                #
                # When hashing, we pick 8192 for efficiency of reads and fingerprint updates
                # (writes) since it's a common OS buffer size and an even multiple of the
                # hash block size.
                dedent(
                    """\
                    import hashlib, os, sys

                    python = os.path.realpath(sys.executable)
                    print(python)

                    hasher = hashlib.sha256()
                    with open(python, "rb") as fp:
                      for chunk in iter(lambda: fp.read(8192), b""):
                          hasher.update(chunk)
                    print(hasher.hexdigest())
                    """
                ),
            ),
            level=LogLevel.DEBUG,
            cache_scope=env_target.executable_search_path_cache_scope(),
        ),
    )
    path, fingerprint = result.stdout.decode().strip().splitlines()

    if pex_subsystem.verbosity > 0:
        log_output = result.stderr.decode()
        if log_output:
            logger.info("%s", log_output)

    return PythonExecutable(path=path, fingerprint=fingerprint)


@dataclass(frozen=True)
class BuildPexResult:
    result: ProcessResult
    pex_filename: str
    digest: Digest
    python: PythonExecutable | None

    def create_pex(self) -> Pex:
        return Pex(digest=self.digest, name=self.pex_filename, python=self.python)


@dataclass
class _BuildPexPythonSetup:
    python: PythonExecutable | None
    argv: list[str]


@rule_helper
async def _determine_pex_python_and_platforms(request: PexRequest) -> _BuildPexPythonSetup:
    # NB: If `--platform` is specified, this signals that the PEX should not be built locally.
    # `--interpreter-constraint` only makes sense in the context of building locally. These two
    # flags are mutually exclusive. See https://github.com/pantsbuild/pex/issues/957.
    if request.platforms or request.complete_platforms:
        # Note that this means that this is not an internal-only pex.
        # TODO(#9560): consider validating that these platforms are valid with the interpreter
        #  constraints.
        return _BuildPexPythonSetup(
            None,
            [
                *request.platforms.generate_pex_arg_list(),
                *request.complete_platforms.generate_pex_arg_list(),
            ],
        )

    if request.python:
        python = request.python
    elif request.internal_only:
        # NB: If it's an internal_only PEX, we do our own lookup of the interpreter based on the
        # interpreter constraints, and then will run the PEX with that specific interpreter. We
        # will have already validated that there were no platforms.
        python = await Get(
            PythonExecutable, InterpreterConstraints, request.interpreter_constraints
        )
    else:
        # `--interpreter-constraint` options are mutually exclusive with the `--python` option,
        # so we only specify them if we have not already located a concrete Python.
        return _BuildPexPythonSetup(None, request.interpreter_constraints.generate_pex_arg_list())

    return _BuildPexPythonSetup(python, ["--python", python.path])


@dataclass
class _BuildPexRequirementsSetup:
    digests: list[Digest]
    argv: list[str]
    concurrency_available: int


@rule_helper
async def _setup_pex_requirements(
    request: PexRequest, python_setup: PythonSetup
) -> _BuildPexRequirementsSetup:
    resolve_name: str | None
    if isinstance(request.requirements, EntireLockfile):
        resolve_name = request.requirements.lockfile.resolve_name
    elif isinstance(request.requirements.from_superset, LoadedLockfile):
        resolve_name = request.requirements.from_superset.original_lockfile.resolve_name
    else:
        # This implies that, currently, per-resolve options are only configurable for resolves.
        # However, if no resolve is specified, we will still load options that apply to every
        # resolve, like `[python-repos].indexes`.
        resolve_name = None
    resolve_config = await Get(ResolvePexConfig, ResolvePexConfigRequest(resolve_name))

    pex_lock_resolver_args = list(resolve_config.pex_args())
    pip_resolver_args = [*resolve_config.pex_args(), "--resolver-version", "pip-2020-resolver"]

    if isinstance(request.requirements, EntireLockfile):
        lockfile = await Get(LoadedLockfile, LoadedLockfileRequest(request.requirements.lockfile))
        argv = (
            ["--lock", lockfile.lockfile_path, *pex_lock_resolver_args]
            if lockfile.is_pex_native
            else
            # We use pip to resolve a requirements.txt pseudo-lockfile, possibly with hashes.
            ["--requirement", lockfile.lockfile_path, "--no-transitive", *pip_resolver_args]
        )
        if lockfile.metadata and request.requirements.complete_req_strings:
            validate_metadata(
                lockfile.metadata,
                request.interpreter_constraints,
                lockfile.original_lockfile,
                request.requirements.complete_req_strings,
                python_setup,
                resolve_config,
            )

        return _BuildPexRequirementsSetup(
            [lockfile.lockfile_digest], argv, lockfile.requirement_estimate
        )

    # TODO: This is not the best heuristic for available concurrency, since the
    # requirements almost certainly have transitive deps which also need building, but it
    # is better than using something hardcoded.
    concurrency_available = len(request.requirements.req_strings)

    if isinstance(request.requirements.from_superset, Pex):
        repository_pex = request.requirements.from_superset
        return _BuildPexRequirementsSetup(
            [repository_pex.digest],
            [*request.requirements.req_strings, "--pex-repository", repository_pex.name],
            concurrency_available,
        )

    if isinstance(request.requirements.from_superset, LoadedLockfile):
        loaded_lockfile = request.requirements.from_superset
        # NB: This is also validated in the constructor.
        assert loaded_lockfile.is_pex_native
        if not request.requirements.req_strings:
            return _BuildPexRequirementsSetup([], [], concurrency_available)

        if loaded_lockfile.metadata:
            validate_metadata(
                loaded_lockfile.metadata,
                request.interpreter_constraints,
                loaded_lockfile.original_lockfile,
                request.requirements.req_strings,
                python_setup,
                resolve_config,
            )

        return _BuildPexRequirementsSetup(
            [loaded_lockfile.lockfile_digest],
            [
                *request.requirements.req_strings,
                "--lock",
                loaded_lockfile.lockfile_path,
                *pex_lock_resolver_args,
            ],
            concurrency_available,
        )

    # We use pip to perform a normal resolve.
    assert request.requirements.from_superset is None
    digests = []
    argv = [*request.requirements.req_strings, *pip_resolver_args]
    if request.requirements.constraints_strings:
        constraints_file = "__constraints.txt"
        constraints_content = "\n".join(request.requirements.constraints_strings)
        digests.append(
            await Get(
                Digest,
                CreateDigest([FileContent(constraints_file, constraints_content.encode())]),
            )
        )
        argv.extend(["--constraints", constraints_file])
    return _BuildPexRequirementsSetup(digests, argv, concurrency_available=concurrency_available)


@rule(level=LogLevel.DEBUG)
async def build_pex(
    request: PexRequest, python_setup: PythonSetup, pex_subsystem: PexSubsystem
) -> BuildPexResult:
    """Returns a PEX with the given settings."""
    argv = [
        "--output-file",
        request.output_filename,
        "--no-emit-warnings",
        *request.additional_args,
    ]

    pex_python_setup = await _determine_pex_python_and_platforms(request)
    argv.extend(pex_python_setup.argv)

    if request.main is not None:
        argv.extend(request.main.iter_pex_args())

    # TODO(John Sirois): Right now any request requirements will shadow corresponding pex path
    #  requirements, which could lead to problems. Support shading python binaries.
    #  See: https://github.com/pantsbuild/pants/issues/9206
    if request.pex_path:
        argv.extend(["--pex-path", ":".join(pex.name for pex in request.pex_path)])

    source_dir_name = "source_files"
    argv.append(f"--sources-directory={source_dir_name}")
    sources_digest_as_subdir = await Get(
        Digest, AddPrefix(request.sources or EMPTY_DIGEST, source_dir_name)
    )

    # Include any additional arguments and input digests required by the requirements.
    requirements_setup = await _setup_pex_requirements(request, python_setup)
    argv.extend(requirements_setup.argv)

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                request.complete_platforms.digest,
                sources_digest_as_subdir,
                request.additional_inputs,
                *requirements_setup.digests,
                *(pex.digest for pex in request.pex_path),
            )
        ),
    )

    argv.extend(["--layout", request.layout.value])
    output_files: Iterable[str] | None = None
    output_directories: Iterable[str] | None = None
    if PexLayout.ZIPAPP == request.layout:
        output_files = [request.output_filename]
    else:
        output_directories = [request.output_filename]

    result = await Get(
        ProcessResult,
        PexCliProcess(
            python=pex_python_setup.python,
            subcommand=(),
            extra_args=argv,
            additional_input_digest=merged_digest,
            description=_build_pex_description(request),
            output_files=output_files,
            output_directories=output_directories,
            concurrency_available=requirements_setup.concurrency_available,
        ),
    )

    if pex_subsystem.verbosity > 0:
        log_output = result.stderr.decode()
        if log_output:
            logger.info("%s", log_output)

    digest = (
        await Get(
            Digest, MergeDigests((result.output_digest, *(pex.digest for pex in request.pex_path)))
        )
        if request.pex_path
        else result.output_digest
    )

    return BuildPexResult(
        result=result,
        pex_filename=request.output_filename,
        digest=digest,
        python=pex_python_setup.python,
    )


def _build_pex_description(request: PexRequest) -> str:
    if request.description:
        return request.description

    if isinstance(request.requirements, EntireLockfile):
        lockfile = request.requirements.lockfile
        if isinstance(lockfile, Lockfile):
            desc_suffix = f"from {lockfile.file_path}"
        else:
            desc_suffix = f"from {lockfile.file_content.path}"
    else:
        if not request.requirements.req_strings:
            return f"Building {request.output_filename}"
        elif isinstance(request.requirements.from_superset, Pex):
            repo_pex = request.requirements.from_superset.name
            return softwrap(
                f"""
                Extracting {pluralize(len(request.requirements.req_strings), 'requirement')}
                to build {request.output_filename} from {repo_pex}:
                {', '.join(request.requirements.req_strings)}
                """
            )
        elif isinstance(request.requirements.from_superset, LoadedLockfile):
            lockfile_path = request.requirements.from_superset.lockfile_path
            return softwrap(
                f"""
                Building {pluralize(len(request.requirements.req_strings), 'requirement')}
                for {request.output_filename} from the {lockfile_path} resolve:
                {', '.join(request.requirements.req_strings)}
                """
            )
        else:
            desc_suffix = softwrap(
                f"""
                with {pluralize(len(request.requirements.req_strings), 'requirement')}:
                {', '.join(request.requirements.req_strings)}
                """
            )
    return f"Building {request.output_filename} {desc_suffix}"


@rule
async def create_pex(request: PexRequest) -> Pex:
    result = await Get(BuildPexResult, PexRequest, request)
    return result.create_pex()


@rule
async def create_optional_pex(request: OptionalPexRequest) -> OptionalPex:
    if request.maybe_pex_request is None:
        return OptionalPex(None)
    result = await Get(Pex, PexRequest, request.maybe_pex_request)
    return OptionalPex(result)


@dataclass(frozen=True)
class Script:
    path: PurePath

    @property
    def argv0(self) -> str:
        return f"./{self.path}" if self.path.parent == PurePath() else str(self.path)


@dataclass(frozen=True)
class VenvScript:
    script: Script
    content: FileContent


@dataclass(frozen=True)
class VenvScriptWriter:
    complete_pex_env: CompletePexEnvironment
    pex: Pex
    venv_dir: PurePath

    @classmethod
    def create(
        cls, pex_environment: PexEnvironment, pex: Pex, venv_rel_dir: PurePath
    ) -> VenvScriptWriter:
        # N.B.: We don't know the working directory that will be used in any given
        # invocation of the venv scripts; so we deal with working_directory once in an
        # `adjust_relative_paths` function inside the script to save rule authors from having to do
        # CWD offset math in every rule for all the relative paths their process depends on.
        complete_pex_env = pex_environment.in_sandbox(working_directory=None)
        venv_dir = complete_pex_env.pex_root / venv_rel_dir
        return cls(complete_pex_env=complete_pex_env, pex=pex, venv_dir=venv_dir)

    def _create_venv_script(
        self,
        bash: BashBinary,
        *,
        script_path: PurePath,
        venv_executable: PurePath,
    ) -> VenvScript:
        env_vars = (
            f"{name}={shlex.quote(value)}"
            for name, value in self.complete_pex_env.environment_dict(
                python_configured=True
            ).items()
        )

        target_venv_executable = shlex.quote(str(venv_executable))
        venv_dir = shlex.quote(str(self.venv_dir))
        execute_pex_args = " ".join(
            f"$(adjust_relative_paths {shlex.quote(arg)})"
            for arg in self.complete_pex_env.create_argv(self.pex.name, python=self.pex.python)
        )

        script = dedent(
            f"""\
            #!{bash.path}
            set -euo pipefail

            # N.B.: This relies on BASH_SOURCE which has been available since bash-3.0, released in
            # 2004. It will either contain the absolute path of the venv script or it will contain
            # the relative path from the CWD to the venv script. Either way, we know the venv script
            # parent directory is the sandbox root directory.
            SANDBOX_ROOT="${{BASH_SOURCE%/*}}"

            function adjust_relative_paths() {{
                local value0="$1"
                shift
                if [ "${{value0:0:1}}" == "/" ]; then
                    # Don't relativize absolute paths.
                    echo "${{value0}}" "$@"
                else
                    # N.B.: We convert all relative paths to paths relative to the sandbox root so
                    # this script works when run with a PWD set somewhere else than the sandbox
                    # root.
                    #
                    # There are two cases to consider. For the purposes of example, assume PWD is
                    # `/tmp/sandboxes/abc123/foo/bar`; i.e.: the rule API sets working_directory to
                    # `foo/bar`. Also assume `config/tool.yml` is the relative path in question.
                    #
                    # 1. If our BASH_SOURCE is  `/tmp/sandboxes/abc123/pex_shim.sh`; so our
                    #    SANDBOX_ROOT is `/tmp/sandboxes/abc123`, we calculate
                    #    `/tmp/sandboxes/abc123/config/tool.yml`.
                    # 2. If our BASH_SOURCE is instead `../../pex_shim.sh`; so our SANDBOX_ROOT is
                    #    `../..`, we calculate `../../config/tool.yml`.
                    echo "${{SANDBOX_ROOT}}/${{value0}}" "$@"
                fi
            }}

            export {" ".join(env_vars)}
            export PEX_ROOT="$(adjust_relative_paths ${{PEX_ROOT}})"

            execute_pex_args="{execute_pex_args}"
            target_venv_executable="$(adjust_relative_paths {target_venv_executable})"
            venv_dir="$(adjust_relative_paths {venv_dir})"

            # Let PEX_TOOLS invocations pass through to the original PEX file since venvs don't come
            # with tools support.
            if [ -n "${{PEX_TOOLS:-}}" ]; then
              exec ${{execute_pex_args}} "$@"
            fi

            # If the seeded venv has been removed from the PEX_ROOT, we re-seed from the original
            # `--venv` mode PEX file.
            if [ ! -e "${{venv_dir}}" ]; then
                PEX_INTERPRETER=1 ${{execute_pex_args}} -c ''
            fi

            exec "${{target_venv_executable}}" "$@"
            """
        )
        return VenvScript(
            script=Script(script_path),
            content=FileContent(path=str(script_path), content=script.encode(), is_executable=True),
        )

    def exe(self, bash: BashBinary) -> VenvScript:
        """Writes a safe shim for the venv's executable `pex` script."""
        script_path = PurePath(f"{self.pex.name}_pex_shim.sh")
        return self._create_venv_script(
            bash, script_path=script_path, venv_executable=self.venv_dir / "pex"
        )

    def bin(self, bash: BashBinary, name: str) -> VenvScript:
        """Writes a safe shim for an executable or script in the venv's `bin` directory."""
        script_path = PurePath(f"{self.pex.name}_bin_{name}_shim.sh")
        return self._create_venv_script(
            bash,
            script_path=script_path,
            venv_executable=self.venv_dir / "bin" / name,
        )

    def python(self, bash: BashBinary) -> VenvScript:
        """Writes a safe shim for the venv's python binary."""
        return self.bin(bash, "python")


@dataclass(frozen=True)
class VenvPex:
    digest: Digest
    pex_filename: str
    pex: Script
    python: Script
    bin: FrozenDict[str, Script]
    venv_rel_dir: str


@frozen_after_init
@dataclass(unsafe_hash=True)
class VenvPexRequest:
    pex_request: PexRequest
    bin_names: tuple[str, ...] = ()
    site_packages_copies: bool = False

    def __init__(
        self,
        pex_request: PexRequest,
        bin_names: Iterable[str] = (),
        site_packages_copies: bool = False,
    ) -> None:
        """A request for a PEX that runs in a venv and optionally exposes select venv `bin` scripts.

        :param pex_request: The details of the desired PEX.
        :param bin_names: The names of venv `bin` scripts to expose for execution.
        :param site_packages_copies: `True` to use copies (hardlinks when possible) of PEX
            dependencies when installing them in the venv site-packages directory. By default this
            is `False` and symlinks are used instead which is a win in the time and space dimensions
            but results in a non-standard venv structure that does trip up some libraries.
        """
        self.pex_request = pex_request
        self.bin_names = tuple(bin_names)
        self.site_packages_copies = site_packages_copies


@rule
def wrap_venv_prex_request(pex_request: PexRequest) -> VenvPexRequest:
    # Allow creating a VenvPex from a plain PexRequest when no extra bin scripts need to be exposed.
    return VenvPexRequest(pex_request)


@rule
async def create_venv_pex(
    request: VenvPexRequest, bash: BashBinary, pex_environment: PexEnvironment
) -> VenvPex:
    # VenvPex is motivated by improving performance of Python tools by eliminating traditional PEX
    # file startup overhead.
    #
    # To achieve the minimal overhead (on the order of 1ms) we discard:
    # 1. Using Pex default mode:
    #    Although this does reduce initial tool execution overhead, it still leaves a minimum
    #    O(100ms) of overhead per subsequent tool invocation. Fundamentally, Pex still needs to
    #    execute its `sys.path` isolation bootstrap code in this case.
    # 2. Using the Pex `venv` tool:
    #    The idea here would be to create a tool venv as a Process output and then use the tool
    #    venv as an input digest for all tool invocations. This was tried and netted ~500ms of
    #    overhead over raw venv use.
    #
    # Instead we use Pex's `--venv` mode. In this mode you can run the Pex file and it will create a
    # venv on the fly in the PEX_ROOT as needed. Since the PEX_ROOT is a named_cache, we avoid the
    # digest materialization overhead present in 2 above. Since the venv is naturally isolated we
    # avoid the `sys.path` isolation overhead of Pex itself present in 1 above.
    #
    # This does leave O(50ms) of overhead though for the PEX bootstrap code to detect an already
    # created venv in the PEX_ROOT and re-exec into it. To eliminate this overhead we execute the
    # `pex` venv script in the PEX_ROOT directly. This is not robust on its own though, since the
    # named caches store might be pruned at any time. To guard against that case we introduce a shim
    # bash script that checks to see if the `pex` venv script exists in the PEX_ROOT and re-creates
    # the PEX_ROOT venv if not. Using the shim script to run Python tools gets us down to the ~1ms
    # of overhead we currently enjoy.

    pex_request = request.pex_request
    seeded_venv_request = dataclasses.replace(
        pex_request,
        additional_args=pex_request.additional_args
        + (
            "--venv",
            "--seed",
            "verbose",
            pex_environment.venv_site_packages_copies_option(
                use_copies=request.site_packages_copies
            ),
        ),
    )
    venv_pex_result = await Get(BuildPexResult, PexRequest, seeded_venv_request)
    # Pex verbose --seed mode outputs the absolute path of the PEX executable as well as the
    # absolute path of the PEX_ROOT.  In the --venv case this is the `pex` script in the venv root
    # directory.
    seed_info = json.loads(venv_pex_result.result.stdout.decode())
    abs_pex_root = PurePath(seed_info["pex_root"])
    abs_pex_path = PurePath(seed_info["pex"])
    venv_rel_dir = abs_pex_path.relative_to(abs_pex_root).parent

    venv_script_writer = VenvScriptWriter.create(
        pex_environment=pex_environment, pex=venv_pex_result.create_pex(), venv_rel_dir=venv_rel_dir
    )
    pex = venv_script_writer.exe(bash)
    python = venv_script_writer.python(bash)
    scripts = {bin_name: venv_script_writer.bin(bash, bin_name) for bin_name in request.bin_names}
    scripts_digest = await Get(
        Digest,
        CreateDigest(
            (
                pex.content,
                python.content,
                *(venv_script.content for venv_script in scripts.values()),
            )
        ),
    )
    input_digest = await Get(Digest, MergeDigests((venv_script_writer.pex.digest, scripts_digest)))

    return VenvPex(
        digest=input_digest,
        pex_filename=venv_pex_result.pex_filename,
        pex=pex.script,
        python=python.script,
        bin=FrozenDict((bin_name, venv_script.script) for bin_name, venv_script in scripts.items()),
        venv_rel_dir=venv_rel_dir.as_posix(),
    )


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexProcess:
    pex: Pex
    argv: tuple[str, ...]
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    input_digest: Digest | None
    working_directory: str | None
    extra_env: FrozenDict[str, str]
    output_files: tuple[str, ...] | None
    output_directories: tuple[str, ...] | None
    timeout_seconds: int | None
    execution_slot_variable: str | None
    concurrency_available: int
    cache_scope: ProcessCacheScope

    def __init__(
        self,
        pex: Pex,
        *,
        description: str,
        argv: Iterable[str] = (),
        level: LogLevel = LogLevel.INFO,
        input_digest: Digest | None = None,
        working_directory: str | None = None,
        extra_env: Mapping[str, str] | None = None,
        output_files: Iterable[str] | None = None,
        output_directories: Iterable[str] | None = None,
        timeout_seconds: int | None = None,
        execution_slot_variable: str | None = None,
        concurrency_available: int = 0,
        cache_scope: ProcessCacheScope = ProcessCacheScope.SUCCESSFUL,
    ) -> None:
        self.pex = pex
        self.argv = tuple(argv)
        self.description = description
        self.level = level
        self.input_digest = input_digest
        self.working_directory = working_directory
        self.extra_env = FrozenDict(extra_env or {})
        self.output_files = tuple(output_files) if output_files else None
        self.output_directories = tuple(output_directories) if output_directories else None
        self.timeout_seconds = timeout_seconds
        self.execution_slot_variable = execution_slot_variable
        self.concurrency_available = concurrency_available
        self.cache_scope = cache_scope


@rule
async def setup_pex_process(request: PexProcess, pex_environment: PexEnvironment) -> Process:
    pex = request.pex
    complete_pex_env = pex_environment.in_sandbox(working_directory=request.working_directory)
    argv = complete_pex_env.create_argv(pex.name, *request.argv, python=pex.python)
    env = {
        **complete_pex_env.environment_dict(python_configured=pex.python is not None),
        **request.extra_env,
    }
    input_digest = (
        await Get(Digest, MergeDigests((pex.digest, request.input_digest)))
        if request.input_digest
        else pex.digest
    )
    return Process(
        argv,
        description=request.description,
        level=request.level,
        input_digest=input_digest,
        working_directory=request.working_directory,
        env=env,
        output_files=request.output_files,
        output_directories=request.output_directories,
        append_only_caches=complete_pex_env.append_only_caches,
        timeout_seconds=request.timeout_seconds,
        execution_slot_variable=request.execution_slot_variable,
        concurrency_available=request.concurrency_available,
        cache_scope=request.cache_scope,
    )


@frozen_after_init
@dataclass(unsafe_hash=True)
class VenvPexProcess:
    venv_pex: VenvPex
    argv: tuple[str, ...]
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    input_digest: Digest | None
    working_directory: str | None
    extra_env: FrozenDict[str, str] | None
    output_files: tuple[str, ...] | None
    output_directories: tuple[str, ...] | None
    timeout_seconds: int | None
    execution_slot_variable: str | None
    concurrency_available: int
    cache_scope: ProcessCacheScope
    append_only_caches: FrozenDict[str, str]

    def __init__(
        self,
        venv_pex: VenvPex,
        *,
        description: str,
        argv: Iterable[str] = (),
        level: LogLevel = LogLevel.INFO,
        input_digest: Digest | None = None,
        working_directory: str | None = None,
        extra_env: Mapping[str, str] | None = None,
        output_files: Iterable[str] | None = None,
        output_directories: Iterable[str] | None = None,
        timeout_seconds: int | None = None,
        execution_slot_variable: str | None = None,
        concurrency_available: int = 0,
        cache_scope: ProcessCacheScope = ProcessCacheScope.SUCCESSFUL,
        append_only_caches: Mapping[str, str] | None = None,
    ) -> None:
        self.venv_pex = venv_pex
        self.argv = tuple(argv)
        self.description = description
        self.level = level
        self.input_digest = input_digest
        self.working_directory = working_directory
        self.extra_env = FrozenDict(extra_env) if extra_env else None
        self.output_files = tuple(output_files) if output_files else None
        self.output_directories = tuple(output_directories) if output_directories else None
        self.timeout_seconds = timeout_seconds
        self.execution_slot_variable = execution_slot_variable
        self.concurrency_available = concurrency_available
        self.cache_scope = cache_scope
        self.append_only_caches = FrozenDict(append_only_caches or {})


@rule
async def setup_venv_pex_process(
    request: VenvPexProcess, pex_environment: PexEnvironment
) -> Process:
    venv_pex = request.venv_pex
    pex_bin = (
        os.path.relpath(venv_pex.pex.argv0, request.working_directory)
        if request.working_directory
        else venv_pex.pex.argv0
    )
    argv = (pex_bin, *request.argv)
    input_digest = (
        await Get(Digest, MergeDigests((venv_pex.digest, request.input_digest)))
        if request.input_digest
        else venv_pex.digest
    )
    append_only_caches: FrozenDict[str, str] = FrozenDict(
        **pex_environment.in_sandbox(
            working_directory=request.working_directory
        ).append_only_caches,
        **request.append_only_caches,
    )
    return Process(
        argv=argv,
        description=request.description,
        level=request.level,
        input_digest=input_digest,
        working_directory=request.working_directory,
        env=request.extra_env,
        output_files=request.output_files,
        output_directories=request.output_directories,
        append_only_caches=append_only_caches,
        timeout_seconds=request.timeout_seconds,
        execution_slot_variable=request.execution_slot_variable,
        concurrency_available=request.concurrency_available,
        cache_scope=request.cache_scope,
    )


@dataclass(frozen=True)
class PexDistributionInfo:
    """Information about an individual distribution in a PEX file, as reported by `PEX_TOOLS=1
    repository info -v`."""

    project_name: str
    version: packaging.version.Version
    requires_python: packaging.specifiers.SpecifierSet | None
    # Note: These are parsed from metadata written by the pex tool, and are always
    #   a valid pkg_resources.Requirement.
    requires_dists: tuple[Requirement, ...]


DefaultT = TypeVar("DefaultT")


class PexResolveInfo(Collection[PexDistributionInfo]):
    """Information about all distributions resolved in a PEX file, as reported by `PEX_TOOLS=1
    repository info -v`."""

    def find(
        self, name: str, default: DefaultT | None = None
    ) -> PexDistributionInfo | DefaultT | None:
        """Returns the PexDistributionInfo with the given name, first one wins."""
        try:
            return next(info for info in self if info.project_name == name)
        except StopIteration:
            return default


def parse_repository_info(repository_info: str) -> PexResolveInfo:
    def iter_dist_info() -> Iterator[PexDistributionInfo]:
        for line in repository_info.splitlines():
            info = json.loads(line)
            requires_python = info["requires_python"]
            yield PexDistributionInfo(
                project_name=info["project_name"],
                version=packaging.version.Version(info["version"]),
                requires_python=(
                    packaging.specifiers.SpecifierSet(requires_python)
                    if requires_python is not None
                    else None
                ),
                requires_dists=tuple(
                    Requirement.parse(req) for req in sorted(info["requires_dists"])
                ),
            )

    return PexResolveInfo(sorted(iter_dist_info(), key=lambda dist: dist.project_name))


@rule
async def determine_venv_pex_resolve_info(venv_pex: VenvPex) -> PexResolveInfo:
    process_result = await Get(
        ProcessResult,
        VenvPexProcess(
            venv_pex,
            argv=["repository", "info", "-v"],
            extra_env={"PEX_TOOLS": "1"},
            input_digest=venv_pex.digest,
            description=f"Determine distributions found in {venv_pex.pex_filename}",
            level=LogLevel.DEBUG,
        ),
    )
    return parse_repository_info(process_result.stdout.decode())


@rule
async def determine_pex_resolve_info(pex_pex: PexPEX, pex: Pex) -> PexResolveInfo:
    process_result = await Get(
        ProcessResult,
        PexProcess(
            pex=Pex(digest=pex_pex.digest, name=pex_pex.exe, python=pex.python),
            argv=[pex.name, "repository", "info", "-v"],
            input_digest=pex.digest,
            extra_env={"PEX_MODULE": "pex.tools"},
            description=f"Determine distributions found in {pex.name}",
            level=LogLevel.DEBUG,
        ),
    )
    return parse_repository_info(process_result.stdout.decode())


def rules():
    return [*collect_rules(), *pex_cli.rules(), *pex_requirements.rules()]
