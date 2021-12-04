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
from typing import Iterable, Iterator, Mapping

import packaging.specifiers
import packaging.version
from pkg_resources import Requirement

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.repos import PythonRepos
from pants.backend.python.subsystems.setup import InvalidLockfileBehavior, PythonSetup
from pants.backend.python.target_types import MainSpecification, PexLayout
from pants.backend.python.target_types import PexPlatformsField as PythonPlatformsField
from pants.backend.python.target_types import PythonRequirementsField
from pants.backend.python.util_rules import pex_cli
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import (
    InvalidLockfileError,
    InvalidLockfileReason,
    LockfileMetadata,
)
from pants.backend.python.util_rules.pex_cli import PexCliProcess, PexPEX
from pants.backend.python.util_rules.pex_environment import (
    CompletePexEnvironment,
    PexEnvironment,
    PexRuntimeEnvironment,
    PythonExecutable,
)
from pants.engine.collection import Collection, DeduplicatedCollection
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
from pants.engine.platform import Platform
from pants.engine.process import BashBinary, Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Lockfile:
    file_path: str
    file_path_description_of_origin: str
    lockfile_hex_digest: str | None
    req_strings: FrozenOrderedSet[str] | None


@dataclass(frozen=True)
class LockfileContent:
    file_content: FileContent
    lockfile_hex_digest: str | None
    req_strings: FrozenOrderedSet[str] | None


@dataclass(frozen=True)
class _ToolLockfileMixin:
    options_scope_name: str
    uses_source_plugins: bool
    uses_project_interpreter_constraints: bool


@dataclass(frozen=True)
class ToolDefaultLockfile(LockfileContent, _ToolLockfileMixin):
    pass


@dataclass(frozen=True)
class ToolCustomLockfile(Lockfile, _ToolLockfileMixin):
    pass


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexRequirements:
    req_strings: FrozenOrderedSet[str]
    apply_constraints: bool
    # TODO: The constraints.txt resolve for `resolve_all_constraints` will be removed as part of
    # #12314, but in the meantime, it "acts like" a lockfile, but isn't actually typed as a Lockfile
    # because the constraints are modified in memory first. This flag marks a `PexRequirements`
    # resolve as being a request for the entire constraints file.
    is_all_constraints_resolve: bool
    repository_pex: Pex | None

    def __init__(
        self,
        req_strings: Iterable[str] = (),
        *,
        apply_constraints: bool = False,
        is_all_constraints_resolve: bool = False,
        repository_pex: Pex | None = None,
    ) -> None:
        """
        :param req_strings: The requirement strings to resolve.
        :param apply_constraints: Whether to apply any configured requirement_constraints while
            building this PEX.
        :param repository_pex: An optional PEX to resolve requirements from via the Pex CLI
            `--pex-repository` option.
        """
        self.req_strings = FrozenOrderedSet(sorted(req_strings))
        self.apply_constraints = apply_constraints
        self.is_all_constraints_resolve = is_all_constraints_resolve
        self.repository_pex = repository_pex

    @classmethod
    def create_from_requirement_fields(
        cls,
        fields: Iterable[PythonRequirementsField],
        *,
        additional_requirements: Iterable[str] = (),
        apply_constraints: bool = True,
    ) -> PexRequirements:
        field_requirements = {str(python_req) for field in fields for python_req in field.value}
        return PexRequirements(
            {*field_requirements, *additional_requirements}, apply_constraints=apply_constraints
        )

    def __bool__(self) -> bool:
        return bool(self.req_strings)


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


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexRequest(EngineAwareParameter):
    output_filename: str
    internal_only: bool
    layout: PexLayout | None
    python: PythonExecutable | None
    requirements: PexRequirements | Lockfile | LockfileContent
    interpreter_constraints: InterpreterConstraints
    platforms: PexPlatforms
    sources: Digest | None
    additional_inputs: Digest | None
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
        requirements: PexRequirements | Lockfile | LockfileContent = PexRequirements(),
        interpreter_constraints=InterpreterConstraints(),
        platforms=PexPlatforms(),
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
        :param platforms: Which platforms should be supported. Setting this value will cause
            interpreter constraints to not be used because platforms already constrain the valid
            Python versions, e.g. by including `cp36m` in the platform string.
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
        self.layout = layout
        self.python = python
        self.requirements = requirements
        self.interpreter_constraints = interpreter_constraints
        self.platforms = platforms
        self.sources = sources
        self.additional_inputs = additional_inputs
        self.main = main
        self.additional_args = tuple(additional_args)
        self.pex_path = tuple(pex_path)
        self.description = description
        self.__post_init__()

    def __post_init__(self):
        if self.internal_only and self.platforms:
            raise ValueError(
                "Internal only PEXes can only constrain interpreters with interpreter_constraints."
                f"Given platform constraints {self.platforms} for internal only pex request: "
                f"{self}."
            )
        if self.internal_only and self.layout:
            raise ValueError(
                "Internal only PEXes have their layout controlled centrally. Given layout "
                f"{self.layout} for internal only pex request: {self}."
            )
        if self.python and self.platforms:
            raise ValueError(
                "Only one of platforms or a specific interpreter may be set. Got "
                f"both {self.platforms} and {self.python}."
            )
        if self.python and self.interpreter_constraints:
            raise ValueError(
                "Only one of interpreter_constraints or a specific interpreter may be set. Got "
                f"both {self.interpreter_constraints} and {self.python}."
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
    interpreter_constraints: InterpreterConstraints, pex_runtime_env: PexRuntimeEnvironment
) -> PythonExecutable:
    formatted_constraints = " OR ".join(str(constraint) for constraint in interpreter_constraints)
    result = await Get(
        ProcessResult,
        PexCliProcess(
            description=f"Find interpreter for constraints: {formatted_constraints}",
            # Here, we run the Pex CLI with no requirements, which just selects an interpreter.
            # Normally, this would start an isolated repl. By passing `--`, we force the repl to
            # instead act as an interpreter (the selected one) and tell us about itself. The upshot
            # is we run the Pex interpreter selection logic unperturbed but without resolving any
            # distributions.
            argv=(
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
            # NB: We want interpreter discovery to re-run fairly frequently
            # (PER_RESTART_SUCCESSFUL), but not on every run of Pants (NEVER, which is effectively
            # per-Session). See #10769 for a solution that is less of a tradeoff.
            cache_scope=ProcessCacheScope.PER_RESTART_SUCCESSFUL,
        ),
    )
    path, fingerprint = result.stdout.decode().strip().splitlines()

    if pex_runtime_env.verbosity > 0:
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


@rule(level=LogLevel.DEBUG)
async def build_pex(
    request: PexRequest,
    python_setup: PythonSetup,
    python_repos: PythonRepos,
    platform: Platform,
    pex_runtime_env: PexRuntimeEnvironment,
) -> BuildPexResult:
    """Returns a PEX with the given settings."""
    argv = ["--output-file", request.output_filename, *request.additional_args]

    repository_pex = (
        request.requirements.repository_pex
        if isinstance(request.requirements, PexRequirements)
        else None
    )
    if repository_pex:
        argv.extend(["--pex-repository", repository_pex.name])
    else:
        # NB: In setting `--no-pypi`, we rely on the default value of `--python-repos-indexes`
        # including PyPI, which will override `--no-pypi` and result in using PyPI in the default
        # case. Why set `--no-pypi`, then? We need to do this so that
        # `--python-repos-repos=['custom_url']` will only point to that index and not include PyPI.
        argv.extend(
            [
                "--no-pypi",
                *(f"--index={index}" for index in python_repos.indexes),
                *(f"--repo={repo}" for repo in python_repos.repos),
                "--resolver-version",
                "pip-2020-resolver",
            ]
        )

    python: PythonExecutable | None = None

    # NB: If `--platform` is specified, this signals that the PEX should not be built locally.
    # `--interpreter-constraint` only makes sense in the context of building locally. These two
    # flags are mutually exclusive. See https://github.com/pantsbuild/pex/issues/957.
    if request.platforms:
        # TODO(#9560): consider validating that these platforms are valid with the interpreter
        #  constraints.
        argv.extend(request.platforms.generate_pex_arg_list())
    elif request.python:
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
        argv.extend(request.interpreter_constraints.generate_pex_arg_list())

    if python:
        argv.extend(["--python", python.path])

    argv.append("--no-emit-warnings")

    if python_setup.resolver_jobs:
        argv.extend(["--jobs", str(python_setup.resolver_jobs)])

    if python_setup.manylinux:
        argv.extend(["--manylinux", python_setup.manylinux])
    else:
        argv.append("--no-manylinux")

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

    additional_inputs_digest = request.additional_inputs or EMPTY_DIGEST
    repository_pex_digest = repository_pex.digest if repository_pex else EMPTY_DIGEST
    constraint_file_digest = EMPTY_DIGEST
    requirements_file_digest = EMPTY_DIGEST

    # TODO(#12314): Capture the resolve name for multiple user lockfiles.
    resolve_name = (
        request.requirements.options_scope_name
        if isinstance(request.requirements, (ToolDefaultLockfile, ToolCustomLockfile))
        else None
    )

    if isinstance(request.requirements, Lockfile):
        is_monolithic_resolve = True
        argv.extend(["--requirement", request.requirements.file_path])
        argv.append("--no-transitive")
        globs = PathGlobs(
            [request.requirements.file_path],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=request.requirements.file_path_description_of_origin,
        )
        if python_setup.invalid_lockfile_behavior in {
            InvalidLockfileBehavior.warn,
            InvalidLockfileBehavior.error,
        }:
            requirements_file_digest_contents = await Get(DigestContents, PathGlobs, globs)
            metadata = LockfileMetadata.from_lockfile(
                requirements_file_digest_contents[0].content,
                request.requirements.file_path,
                resolve_name,
            )
            _validate_metadata(metadata, request, request.requirements, python_setup)
        requirements_file_digest = await Get(Digest, PathGlobs, globs)

    elif isinstance(request.requirements, LockfileContent):
        is_monolithic_resolve = True
        file_content = request.requirements.file_content
        argv.extend(["--requirement", file_content.path])
        argv.append("--no-transitive")
        if python_setup.invalid_lockfile_behavior in {
            InvalidLockfileBehavior.warn,
            InvalidLockfileBehavior.error,
        }:
            metadata = LockfileMetadata.from_lockfile(
                file_content.content, resolve_name=resolve_name
            )
            _validate_metadata(metadata, request, request.requirements, python_setup)
        requirements_file_digest = await Get(Digest, CreateDigest([file_content]))
    else:
        assert isinstance(request.requirements, PexRequirements)
        is_monolithic_resolve = request.requirements.is_all_constraints_resolve

        if (
            request.requirements.apply_constraints
            and python_setup.requirement_constraints is not None
        ):
            argv.extend(["--constraints", python_setup.requirement_constraints])
            constraint_file_digest = await Get(
                Digest,
                PathGlobs(
                    [python_setup.requirement_constraints],
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    description_of_origin="the option `[python].requirement_constraints`",
                ),
            )

        argv.extend(request.requirements.req_strings)

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                sources_digest_as_subdir,
                additional_inputs_digest,
                constraint_file_digest,
                requirements_file_digest,
                repository_pex_digest,
                *(pex.digest for pex in request.pex_path),
            )
        ),
    )

    if request.internal_only or is_monolithic_resolve:
        # This is a much friendlier layout for the CAS than the default zipapp.
        layout = PexLayout.PACKED
    else:
        layout = request.layout or PexLayout.ZIPAPP
    argv.extend(["--layout", layout.value])

    output_files: Iterable[str] | None = None
    output_directories: Iterable[str] | None = None
    if PexLayout.ZIPAPP == layout:
        output_files = [request.output_filename]
    else:
        output_directories = [request.output_filename]

    process = await Get(
        Process,
        PexCliProcess(
            python=python,
            argv=argv,
            additional_input_digest=merged_digest,
            description=_build_pex_description(request),
            output_files=output_files,
            output_directories=output_directories,
        ),
    )

    process = dataclasses.replace(process, platform=platform)

    # NB: Building a Pex is platform dependent, so in order to get a PEX that we can use locally
    # without cross-building, we specify that our PEX command should be run on the current local
    # platform.
    result = await Get(ProcessResult, Process, process)

    if pex_runtime_env.verbosity > 0:
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
        result=result, pex_filename=request.output_filename, digest=digest, python=python
    )


def _validate_metadata(
    metadata: LockfileMetadata,
    request: PexRequest,
    requirements: (Lockfile | LockfileContent),
    python_setup: PythonSetup,
) -> None:

    # TODO(#12314): Improve this message: `Requirement.parse` raises `InvalidRequirement`, which
    # doesn't have mypy stubs at the moment; it may be hard to catch this exception and typecheck.
    req_strings = (
        {PipRequirement.parse(i) for i in requirements.req_strings}
        if requirements.req_strings is not None
        else None
    )

    validation = metadata.is_valid_for(
        requirements.lockfile_hex_digest,
        request.interpreter_constraints,
        python_setup.interpreter_universe,
        req_strings,
    )

    if validation:
        return

    def tool_message_parts(
        requirements: (ToolCustomLockfile | ToolDefaultLockfile),
    ) -> Iterator[str]:

        tool_name = requirements.options_scope_name
        uses_source_plugins = requirements.uses_source_plugins
        uses_project_interpreter_constraints = requirements.uses_project_interpreter_constraints

        yield "You are using "

        if isinstance(requirements, ToolDefaultLockfile):
            yield "the `<default>` lockfile provided by Pants "
        elif isinstance(requirements, ToolCustomLockfile):
            yield f"the lockfile at {requirements.file_path} "

        yield (
            f"to install the tool `{tool_name}`, but it is not compatible with your "
            "configuration: "
            "\n\n"
        )

        if any(
            i == InvalidLockfileReason.INVALIDATION_DIGEST_MISMATCH
            or i == InvalidLockfileReason.REQUIREMENTS_MISMATCH
            for i in validation.failure_reasons
        ):
            # TODO(12314): Add message showing _which_ requirements diverged.

            yield (
                "- You have set different requirements than those used to generate the lockfile. "
                f"You can fix this by not setting `[{tool_name}].version`, "
            )

            if uses_source_plugins:
                yield f"`[{tool_name}].source_plugins`, "

            yield (
                f"and `[{tool_name}].extra_requirements`, or by using a new "
                "custom lockfile."
                "\n"
            )

        if InvalidLockfileReason.INTERPRETER_CONSTRAINTS_MISMATCH in validation.failure_reasons:
            yield (
                f"- You have set interpreter constraints (`{request.interpreter_constraints}`) that "
                "are not compatible with those used to generate the lockfile "
                f"(`{metadata.valid_for_interpreter_constraints}`). "
            )
            if not uses_project_interpreter_constraints:
                yield (
                    f"You can fix this by not setting `[{tool_name}].interpreter_constraints`, "
                    "or by using a new custom lockfile. "
                )
            else:
                yield (
                    f"`{tool_name}` determines its interpreter constraints based on your code's own "
                    "constraints. To fix this error, you can either change your code's constraints "
                    f"(see {doc_url('python-interpreter-compatibility')}) or by generating a new "
                    "custom lockfile. "
                )
            yield "\n"

        yield "\n"

        if not isinstance(requirements, ToolCustomLockfile):
            yield (
                "To generate a custom lockfile based on your current configuration, set "
                f"`[{tool_name}].lockfile` to where you want to create the lockfile, then run "
                f"`./pants generate-lockfiles --resolve={tool_name}`. "
            )
        else:
            yield (
                "To regenerate your lockfile based on your current configuration, run "
                f"`./pants generate-lockfiles --resolve={tool_name}`. "
            )

    message: str
    if isinstance(requirements, (ToolCustomLockfile, ToolDefaultLockfile)):
        message = "".join(tool_message_parts(requirements)).strip()
    else:
        # TODO(12314): Improve this message
        raise InvalidLockfileError(f"{validation.failure_reasons}")

    if python_setup.invalid_lockfile_behavior == InvalidLockfileBehavior.error:
        raise ValueError(message)
    else:
        logger.warning("%s", message)


def _build_pex_description(request: PexRequest) -> str:
    if request.description:
        return request.description

    if isinstance(request.requirements, Lockfile):
        desc_suffix = f"from {request.requirements.file_path}"
    elif isinstance(request.requirements, LockfileContent):
        desc_suffix = f"from {request.requirements.file_content.path}"
    else:
        if not request.requirements.req_strings:
            return f"Building {request.output_filename}"
        elif request.requirements.repository_pex:
            repo_pex = request.requirements.repository_pex.name
            return (
                f"Extracting {pluralize(len(request.requirements.req_strings), 'requirement')} "
                f"to build {request.output_filename} from {repo_pex}: "
                f"{', '.join(request.requirements.req_strings)}"
            )
        else:
            desc_suffix = (
                f"with {pluralize(len(request.requirements.req_strings), 'requirement')}: "
                f"{', '.join(request.requirements.req_strings)}"
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
        # invocation of the venv scripts; so we deal with working_directory inside the scripts
        # themselves by absolutifying all relevant paths at runtime.
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
            f"$(ensure_absolute {shlex.quote(arg)})"
            for arg in self.complete_pex_env.create_argv(self.pex.name, python=self.pex.python)
        )

        script = dedent(
            f"""\
            #!{bash.path}
            set -euo pipefail

            # N.B.: We convert all sandbox root relative paths to absolute paths so this script
            # works when run with a cwd set elsewhere.

            # N.B.: This relies on BASH_SOURCE which has been available since bash-3.0, released in
            # 2004. In turn, our use of BASH_SOURCE relies on the fact that this script is executed
            # by the engine via its absolute path.
            ABS_SANDBOX_ROOT="${{BASH_SOURCE%/*}}"

            function ensure_absolute() {{
                local value0="$1"
                shift
                if [ "${{value0:0:1}}" == "/" ]; then
                    echo "${{value0}}" "$@"
                else
                    echo "${{ABS_SANDBOX_ROOT}}/${{value0}}" "$@"
                fi
            }}

            export {" ".join(env_vars)}
            export PEX_ROOT="$(ensure_absolute ${{PEX_ROOT}})"

            execute_pex_args="{execute_pex_args}"
            target_venv_executable="$(ensure_absolute {target_venv_executable})"
            venv_dir="$(ensure_absolute {venv_dir})"

            # Let PEX_TOOLS invocations pass through to the original PEX file since venvs don't come
            # with tools support.
            if [ -n "${{PEX_TOOLS:-}}" ]; then
              exec ${{execute_pex_args}} "$@"
            fi

            # If the seeded venv has been removed from the PEX_ROOT, we re-seed from the original
            # `--venv` mode PEX file.
            if [ ! -e "${{target_venv_executable}}" ]; then
                rm -rf "${{venv_dir}}" || true
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

    def __init__(self, pex_request: PexRequest, bin_names: Iterable[str] = ()) -> None:
        """A request for a PEX that runs in a venv and optionally exposes select venv `bin` scripts.

        :param pex_request: The details of the desired PEX.
        :param bin_names: The names of venv `bin` scripts to expose for execution.
        """
        self.pex_request = pex_request
        self.bin_names = tuple(bin_names)


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
        pex_request, additional_args=pex_request.additional_args + ("--venv", "--seed", "verbose")
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
    extra_env: FrozenDict[str, str] | None
    output_files: tuple[str, ...] | None
    output_directories: tuple[str, ...] | None
    timeout_seconds: int | None
    execution_slot_variable: str | None
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
        cache_scope: ProcessCacheScope = ProcessCacheScope.SUCCESSFUL,
    ) -> None:
        self.pex = pex
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
        self.cache_scope = cache_scope


@rule
async def setup_pex_process(request: PexProcess, pex_environment: PexEnvironment) -> Process:
    pex = request.pex
    complete_pex_env = pex_environment.in_sandbox(working_directory=request.working_directory)
    argv = complete_pex_env.create_argv(pex.name, *request.argv, python=pex.python)
    env = {
        **complete_pex_env.environment_dict(python_configured=pex.python is not None),
        **(request.extra_env or {}),
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
    cache_scope: ProcessCacheScope

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
        cache_scope: ProcessCacheScope = ProcessCacheScope.SUCCESSFUL,
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
        self.cache_scope = cache_scope


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
    return Process(
        argv=argv,
        description=request.description,
        level=request.level,
        input_digest=input_digest,
        working_directory=request.working_directory,
        env=request.extra_env,
        output_files=request.output_files,
        output_directories=request.output_directories,
        append_only_caches=pex_environment.in_sandbox(
            working_directory=request.working_directory
        ).append_only_caches,
        timeout_seconds=request.timeout_seconds,
        execution_slot_variable=request.execution_slot_variable,
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


class PexResolveInfo(Collection[PexDistributionInfo]):
    """Information about all distributions resolved in a PEX file, as reported by `PEX_TOOLS=1
    repository info -v`."""


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
    return [*collect_rules(), *pex_cli.rules()]
