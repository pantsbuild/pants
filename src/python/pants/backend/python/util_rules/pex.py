# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import functools
import itertools
import json
import logging
import shlex
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent
from typing import FrozenSet, Iterable, Iterator, List, Mapping, Sequence, Set, Tuple, TypeVar

import packaging.specifiers
import packaging.version
from pkg_resources import Requirement
from typing_extensions import Protocol

from pants.backend.python.target_types import InterpreterConstraintsField, MainSpecification
from pants.backend.python.target_types import PexPlatformsField as PythonPlatformsField
from pants.backend.python.target_types import (
    PythonRequirementConstraintsField,
    PythonRequirementsField,
)
from pants.backend.python.util_rules import pex_cli
from pants.backend.python.util_rules.pex_cli import PexCliProcess, PexPEX
from pants.backend.python.util_rules.pex_environment import (
    PexRuntimeEnvironment,
    PythonExecutable,
    SandboxPexEnvironment,
)
from pants.engine.addresses import Address, UnparsedAddressInputs
from pants.engine.collection import Collection, DeduplicatedCollection
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    FileContent,
    GlobExpansionConjunction,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
from pants.engine.platform import Platform
from pants.engine.process import (
    BashBinary,
    MultiPlatformProcess,
    Process,
    ProcessCacheScope,
    ProcessResult,
)
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import Target, Targets
from pants.python.python_repos import PythonRepos
from pants.python.python_setup import PythonSetup
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import pluralize


class PexRequirements(DeduplicatedCollection[str]):
    sort_input = True

    @classmethod
    def create_from_requirement_fields(
        cls,
        fields: Iterable[PythonRequirementsField],
        *,
        additional_requirements: Iterable[str] = (),
    ) -> PexRequirements:
        field_requirements = {str(python_req) for field in fields for python_req in field.value}
        return PexRequirements({*field_requirements, *additional_requirements})


# This protocol allows us to work with any arbitrary FieldSet. See
# https://mypy.readthedocs.io/en/stable/protocols.html.
class FieldSetWithInterpreterConstraints(Protocol):
    @property
    def address(self) -> Address:
        ...

    @property
    def interpreter_constraints(self) -> InterpreterConstraintsField:
        ...


_FS = TypeVar("_FS", bound=FieldSetWithInterpreterConstraints)


# Normally we would subclass `DeduplicatedCollection`, but we want a custom constructor.
class PexInterpreterConstraints(FrozenOrderedSet[Requirement], EngineAwareParameter):
    def __init__(self, constraints: Iterable[str | Requirement] = ()) -> None:
        super().__init__(
            v if isinstance(v, Requirement) else self.parse_constraint(v)
            for v in sorted(constraints, key=lambda c: str(c))
        )

    @staticmethod
    def parse_constraint(constraint: str) -> Requirement:
        """Parse an interpreter constraint, e.g., CPython>=2.7,<3.

        We allow shorthand such as `>=3.7`, which gets expanded to `CPython>=3.7`. See Pex's
        interpreter.py's `parse_requirement()`.
        """
        try:
            parsed_requirement = Requirement.parse(constraint)
        except ValueError:
            parsed_requirement = Requirement.parse(f"CPython{constraint}")
        return parsed_requirement

    @classmethod
    def merge_constraint_sets(cls, constraint_sets: Iterable[Iterable[str]]) -> List[Requirement]:
        """Given a collection of constraints sets, merge by ORing within each individual constraint
        set and ANDing across each distinct constraint set.

        For example, given `[["CPython>=2.7", "CPython<=3"], ["CPython==3.6.*"]]`, return
        `["CPython>=2.7,==3.6.*", "CPython<=3,==3.6.*"]`.
        """
        # Each element (a Set[ParsedConstraint]) will get ANDed. We use sets to deduplicate
        # identical top-level parsed constraint sets.
        if not constraint_sets:
            return []
        parsed_constraint_sets: Set[FrozenSet[Requirement]] = set()
        for constraint_set in constraint_sets:
            # Each element (a ParsedConstraint) will get ORed.
            parsed_constraint_set = frozenset(
                cls.parse_constraint(constraint) for constraint in constraint_set
            )
            parsed_constraint_sets.add(parsed_constraint_set)

        def and_constraints(parsed_constraints: Sequence[Requirement]) -> Requirement:
            merged_specs: Set[Tuple[str, str]] = set()
            expected_interpreter = parsed_constraints[0].project_name
            for parsed_constraint in parsed_constraints:
                if parsed_constraint.project_name == expected_interpreter:
                    merged_specs.update(parsed_constraint.specs)
                    continue

                def key_fn(req: Requirement):
                    return req.project_name

                # NB: We must pre-sort the data for itertools.groupby() to work properly.
                sorted_constraints = sorted(parsed_constraints, key=key_fn)
                attempted_interpreters = {
                    interp: sorted(
                        str(parsed_constraint) for parsed_constraint in parsed_constraints
                    )
                    for interp, parsed_constraints in itertools.groupby(
                        sorted_constraints, key=key_fn
                    )
                }
                raise ValueError(
                    "Tried ANDing Python interpreter constraints with different interpreter "
                    "types. Please use only one interpreter type. Got "
                    f"{attempted_interpreters}."
                )

            formatted_specs = ",".join(f"{op}{version}" for op, version in merged_specs)
            return Requirement.parse(f"{expected_interpreter}{formatted_specs}")

        def cmp_constraints(req1: Requirement, req2: Requirement) -> int:
            if req1.project_name != req2.project_name:
                return -1 if req1.project_name < req2.project_name else 1
            if req1.specs == req2.specs:
                return 0
            return -1 if req1.specs < req2.specs else 1

        return sorted(
            {
                and_constraints(constraints_product)
                for constraints_product in itertools.product(*parsed_constraint_sets)
            },
            key=functools.cmp_to_key(cmp_constraints),
        )

    @classmethod
    def create_from_targets(
        cls, targets: Iterable[Target], python_setup: PythonSetup
    ) -> PexInterpreterConstraints:
        return cls.create_from_compatibility_fields(
            (
                tgt[InterpreterConstraintsField]
                for tgt in targets
                if tgt.has_field(InterpreterConstraintsField)
            ),
            python_setup,
        )

    @classmethod
    def create_from_compatibility_fields(
        cls, fields: Iterable[InterpreterConstraintsField], python_setup: PythonSetup
    ) -> PexInterpreterConstraints:
        constraint_sets = {field.value_or_global_default(python_setup) for field in fields}
        # This will OR within each field and AND across fields.
        merged_constraints = cls.merge_constraint_sets(constraint_sets)
        return PexInterpreterConstraints(merged_constraints)

    @classmethod
    def group_field_sets_by_constraints(
        cls, field_sets: Iterable[_FS], python_setup: PythonSetup
    ) -> FrozenDict["PexInterpreterConstraints", Tuple[_FS, ...]]:
        results = defaultdict(set)
        for fs in field_sets:
            constraints = cls.create_from_compatibility_fields(
                [fs.interpreter_constraints], python_setup
            )
            results[constraints].add(fs)
        return FrozenDict(
            {
                constraints: tuple(sorted(field_sets, key=lambda fs: fs.address))
                for constraints, field_sets in sorted(results.items())
            }
        )

    def generate_pex_arg_list(self) -> List[str]:
        args = []
        for constraint in self:
            args.extend(["--interpreter-constraint", str(constraint)])
        return args

    def _includes_version(self, major_minor: str, last_patch: int) -> bool:
        patch_versions = list(reversed(range(0, last_patch + 1)))
        for req in self:
            if any(
                req.specifier.contains(f"{major_minor}.{p}") for p in patch_versions  # type: ignore[attr-defined]
            ):
                return True
        return False

    def includes_python2(self) -> bool:
        """Checks if any of the constraints include Python 2.

        This will return True even if the code works with Python 3 too, so long as at least one of
        the constraints works with Python 2.
        """
        last_py27_patch_version = 18
        return self._includes_version("2.7", last_patch=last_py27_patch_version)

    def minimum_python_version(self) -> str | None:
        """Find the lowest major.minor Python version that will work with these constraints.

        The constraints may also be compatible with later versions; this is the lowest version that
        still works.
        """
        if self.includes_python2():
            return "2.7"
        max_expected_py3_patch_version = 15  # The current max is 3.6.12.
        for major_minor in ("3.5", "3.6", "3.7", "3.8", "3.9", "3.10"):
            if self._includes_version(major_minor, last_patch=max_expected_py3_patch_version):
                return major_minor
        return None

    def _requires_python3_version_or_newer(
        self, *, allowed_versions: Iterable[str], prior_version: str
    ) -> bool:
        # Assume any 3.x release has no more than 15 releases. The max is currently 3.6.12.
        patch_versions = list(reversed(range(0, 15)))
        # We only need to look at the prior Python release. For example, consider Python 3.8+
        # looking at 3.7. If using something like `>=3.5`, Py37 will be included.
        # `==3.6.*,!=3.7.*,==3.8.*` is extremely unlikely, and even that will work correctly as
        # it's an invalid constraint so setuptools returns False always. `['==2.7.*', '==3.8.*']`
        # will fail because not every single constraint is exclusively 3.8.
        prior_versions = [f"{prior_version}.{p}" for p in patch_versions]
        allowed_versions = [
            f"{major_minor}.{p}" for major_minor in allowed_versions for p in patch_versions
        ]
        for req in self:
            if any(
                req.specifier.contains(prior) for prior in prior_versions  # type: ignore[attr-defined]
            ):
                return False
            if not any(
                req.specifier.contains(allowed) for allowed in allowed_versions  # type: ignore[attr-defined]
            ):
                return False
        return True

    def requires_python38_or_newer(self) -> bool:
        """Checks if the constraints are all for Python 3.8+.

        This will return False if Python 3.8 is allowed, but prior versions like 3.7 are also
        allowed.
        """
        return self._requires_python3_version_or_newer(
            allowed_versions=["3.8", "3.9", "3.10"], prior_version="3.7"
        )

    def __str__(self) -> str:
        return " OR ".join(str(constraint) for constraint in self)

    def debug_hint(self) -> str:
        return str(self)


class PexPlatforms(DeduplicatedCollection[str]):
    sort_input = True

    @classmethod
    def create_from_platforms_field(cls, field: PythonPlatformsField) -> PexPlatforms:
        return cls(field.value or ())

    def generate_pex_arg_list(self) -> List[str]:
        args = []
        for platform in self:
            args.extend(["--platform", platform])
        return args


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexRequest(EngineAwareParameter):
    output_filename: str
    internal_only: bool
    requirements: PexRequirements
    interpreter_constraints: PexInterpreterConstraints
    platforms: PexPlatforms
    sources: Digest | None
    additional_inputs: Digest | None
    main: MainSpecification | None
    repository_pex: Pex | None
    additional_args: Tuple[str, ...]
    pex_path: Tuple[Pex, ...]
    apply_requirement_constraints: bool
    description: str | None = dataclasses.field(compare=False)

    def __init__(
        self,
        *,
        output_filename: str,
        internal_only: bool,
        requirements: PexRequirements = PexRequirements(),
        interpreter_constraints=PexInterpreterConstraints(),
        platforms=PexPlatforms(),
        sources: Digest | None = None,
        additional_inputs: Digest | None = None,
        main: MainSpecification | None = None,
        repository_pex: Pex | None = None,
        additional_args: Iterable[str] = (),
        pex_path: Iterable[Pex] = (),
        apply_requirement_constraints: bool = True,
        description: str | None = None,
    ) -> None:
        """A request to create a PEX from its inputs.

        :param output_filename: The name of the built Pex file, which typically should end in
            `.pex`.
        :param internal_only: Whether we ever materialize the Pex and distribute it directly
            to end users, such as with the `binary` goal. Typically, instead, the user never
            directly uses the Pex, e.g. with `lint` and `test`. If True, we will use a Pex setting
            that results in faster build time but compatibility with fewer interpreters at runtime.
        :param requirements: The requirements to install.
        :param interpreter_constraints: Any constraints on which Python versions may be used.
        :param platforms: Which platforms should be supported. Setting this value will cause
            interpreter constraints to not be used because platforms already constrain the valid
            Python versions, e.g. by including `cp36m` in the platform string.
        :param sources: Any source files that should be included in the Pex.
        :param additional_inputs: Any inputs that are not source files and should not be included
            directly in the Pex, but should be present in the environment when building the Pex.
        :param main: The main for the built Pex, equivalent to Pex's `-e` or '-c' flag. If
            left off, the Pex will open up as a REPL.
        :param repository_pex: An optional PEX to resolve requirements from via the Pex CLI
            `--pex-repository` option.
        :param additional_args: Any additional Pex flags.
        :param pex_path: Pex files to add to the PEX_PATH.
        :param apply_requirement_constraints: Whether to apply any configured
            requirement_constraints while building this PEX.
        :param description: A human-readable description to render in the dynamic UI when building
            the Pex.
        """
        self.output_filename = output_filename
        self.internal_only = internal_only
        self.requirements = requirements
        self.interpreter_constraints = interpreter_constraints
        self.platforms = platforms
        self.sources = sources
        self.additional_inputs = additional_inputs
        self.main = main
        self.repository_pex = repository_pex
        self.additional_args = tuple(additional_args)
        self.pex_path = tuple(pex_path)
        self.apply_requirement_constraints = apply_requirement_constraints
        self.description = description
        self.__post_init__()

    def __post_init__(self):
        if self.internal_only and self.platforms:
            raise ValueError(
                "Internal only PEXes can only constrain interpreters with interpreter_constraints."
                f"Given platform constraints {self.platforms} for internal only pex request: "
                f"{self}."
            )

    def debug_hint(self) -> str:
        return self.output_filename


@dataclass(frozen=True)
class TwoStepPexRequest:
    """A request to create a PEX in two steps.

    First we create a requirements-only pex. Then we create the full pex on top of that
    requirements pex, instead of having the full pex directly resolve its requirements.

    This allows us to re-use the requirements-only pex when no requirements have changed (which is
    the overwhelmingly common case), thus avoiding spurious re-resolves of the same requirements
    over and over again.
    """

    pex_request: PexRequest


@dataclass(frozen=True)
class Pex:
    """Wrapper for a digest containing a pex file created with some filename."""

    digest: Digest
    name: str
    python: PythonExecutable | None


@dataclass(frozen=True)
class TwoStepPex:
    """The result of creating a PEX in two steps.

    TODO(9320): A workaround for https://github.com/pantsbuild/pants/issues/9320. Really we
      just want the rules to directly return a Pex.
    """

    pex: Pex


logger = logging.getLogger(__name__)


@rule(desc="Find Python interpreter for constraints", level=LogLevel.DEBUG)
async def find_interpreter(
    interpreter_constraints: PexInterpreterConstraints, pex_runtime_env: PexRuntimeEnvironment
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
            # NB: We want interpreter discovery to re-run fairly frequently (PER_RESTART), but
            # not on every run of Pants (NEVER, which is effectively per-Session). See #10769 for
            # a solution that is less of a tradeoff.
            cache_scope=ProcessCacheScope.PER_RESTART,
        ),
    )
    path, fingerprint = result.stdout.decode().strip().splitlines()

    if pex_runtime_env.verbosity > 0:
        log_output = result.stderr.decode()
        if log_output:
            logger.info("%s", log_output)

    return PythonExecutable(path=path, fingerprint=fingerprint)


@dataclass(frozen=True)
class MaybeConstraintsFile:
    path: str | None
    digest: Digest


@rule(desc="Resolve requirements constraints file")
async def resolve_requirements_constraints_file(python_setup: PythonSetup) -> MaybeConstraintsFile:
    if python_setup.requirement_constraints:
        digest = await Get(
            Digest,
            PathGlobs(
                [python_setup.requirement_constraints],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                conjunction=GlobExpansionConjunction.all_match,
                description_of_origin="the option `[python-setup].requirement_constraints`",
            ),
        )
        return MaybeConstraintsFile(python_setup.requirement_constraints, digest)

    if python_setup.requirement_constraints_target:
        targets = await Get(
            Targets,
            UnparsedAddressInputs(
                [python_setup.requirement_constraints_target], owning_address=None
            ),
        )
        tgt = targets.expect_single()
        if not tgt.has_field(PythonRequirementConstraintsField):
            raise ValueError(
                "Invalid target type for `[python-setup].requirement_constraints_target`. Please "
                f"use a `_python_constraints` target instead of a `{tgt.alias}` target."
            )
        formatted_constraints = "\n".join(
            str(constraint) for constraint in tgt[PythonRequirementConstraintsField].value
        )
        path = "constraints.generated.txt"
        digest = await Get(
            Digest, CreateDigest([FileContent(path, formatted_constraints.encode())])
        )
        return MaybeConstraintsFile(path, digest)

    return MaybeConstraintsFile(None, EMPTY_DIGEST)


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
    constraints_file: MaybeConstraintsFile,
) -> BuildPexResult:
    """Returns a PEX with the given settings."""

    argv = [
        "--output-file",
        request.output_filename,
        *request.additional_args,
    ]

    if request.repository_pex:
        argv.extend(["--pex-repository", request.repository_pex.name])
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
    else:
        argv.extend(request.interpreter_constraints.generate_pex_arg_list())
        # NB: If it's an internal_only PEX, we do our own lookup of the interpreter based on the
        # interpreter constraints, and then will run the PEX with that specific interpreter. We
        # will have already validated that there were no platforms.
        if request.internal_only:
            python = await Get(
                PythonExecutable, PexInterpreterConstraints, request.interpreter_constraints
            )

    argv.append("--no-emit-warnings")

    if python_setup.resolver_jobs:
        argv.extend(["--jobs", str(python_setup.resolver_jobs)])

    if python_setup.manylinux:
        argv.extend(["--manylinux", python_setup.manylinux])
    else:
        argv.append("--no-manylinux")

    if request.main is not None:
        argv.extend(request.main.iter_pex_args())

    source_dir_name = "source_files"
    argv.append(f"--sources-directory={source_dir_name}")

    argv.extend(request.requirements)

    constraint_file_digest = EMPTY_DIGEST
    if request.apply_requirement_constraints and constraints_file.path is not None:
        argv.extend(["--constraints", constraints_file.path])
        constraint_file_digest = constraints_file.digest

    sources_digest_as_subdir = await Get(
        Digest, AddPrefix(request.sources or EMPTY_DIGEST, source_dir_name)
    )
    additional_inputs_digest = request.additional_inputs or EMPTY_DIGEST
    repository_pex_digest = (
        request.repository_pex.digest if request.repository_pex else EMPTY_DIGEST
    )

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                sources_digest_as_subdir,
                additional_inputs_digest,
                constraint_file_digest,
                repository_pex_digest,
                *(pex.digest for pex in request.pex_path),
            )
        ),
    )
    # TODO(John Sirois): Right now any request requirements will shadow corresponding pex path
    #  requirements, which could lead to problems. Support shading python binaries.
    #  See: https://github.com/pantsbuild/pants/issues/9206
    if request.pex_path:
        argv.extend(["--pex-path", ":".join(pex.name for pex in request.pex_path)])

    description = request.description
    if description is None:
        if request.requirements:
            description = (
                f"Building {request.output_filename} with "
                f"{pluralize(len(request.requirements), 'requirement')}: "
                f"{', '.join(request.requirements)}"
            )
        else:
            description = f"Building {request.output_filename}"

    process = await Get(
        Process,
        PexCliProcess(
            python=python,
            argv=argv,
            additional_input_digest=merged_digest,
            description=description,
            output_files=[request.output_filename],
        ),
    )

    # NB: Building a Pex is platform dependent, so in order to get a PEX that we can use locally
    # without cross-building, we specify that our PEX command should be run on the current local
    # platform.
    result = await Get(ProcessResult, MultiPlatformProcess({platform: process}))

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


@rule
async def create_pex(request: PexRequest) -> Pex:
    result = await Get(BuildPexResult, PexRequest, request)
    return result.create_pex()


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
    pex: Pex
    venv_dir: PurePath

    def _create_venv_script(
        self,
        bash: BashBinary,
        pex_environment: SandboxPexEnvironment,
        *,
        script_path: PurePath,
        venv_executable: PurePath,
    ) -> VenvScript:
        env_vars = (
            f"{name}={shlex.quote(value)}"
            for name, value in pex_environment.environment_dict(python_configured=True).items()
        )
        target_venv_executable = shlex.quote(str(venv_executable))
        venv_dir = shlex.quote(str(self.venv_dir))
        execute_pex_args = " ".join(
            shlex.quote(arg)
            for arg in pex_environment.create_argv(self.pex.name, python=self.pex.python)
        )

        script = dedent(
            f"""\
            #!{bash.path}
            set -euo pipefail

            export {" ".join(env_vars)}

            # Let PEX_TOOLS invocations pass through to the original PEX file since venvs don't come
            # with tools support.
            if [ -n "${{PEX_TOOLS:-}}" ]; then
              exec {execute_pex_args} "$@"
            fi

            # If the seeded venv has been removed from the PEX_ROOT, we re-seed from the original
            # `--venv` mode PEX file.
            if [ ! -e {target_venv_executable} ]; then
                rm -rf {venv_dir} || true
                PEX_INTERPRETER=1 {execute_pex_args} -c ''
            fi

            exec {target_venv_executable} "$@"
            """
        )
        return VenvScript(
            script=Script(script_path),
            content=FileContent(path=str(script_path), content=script.encode(), is_executable=True),
        )

    def exe(self, bash: BashBinary, pex_environment: SandboxPexEnvironment) -> VenvScript:
        """Writes a safe shim for the venv's executable `pex` script."""
        script_path = PurePath(f"{self.pex.name}_pex_shim.sh")
        return self._create_venv_script(
            bash, pex_environment, script_path=script_path, venv_executable=self.venv_dir / "pex"
        )

    def bin(
        self, bash: BashBinary, pex_environment: SandboxPexEnvironment, name: str
    ) -> VenvScript:
        """Writes a safe shim for an executable or script in the venv's `bin` directory."""
        script_path = PurePath(f"{self.pex.name}_bin_{name}_shim.sh")
        return self._create_venv_script(
            bash,
            pex_environment,
            script_path=script_path,
            venv_executable=self.venv_dir / "bin" / name,
        )

    def python(self, bash: BashBinary, pex_environment: SandboxPexEnvironment) -> VenvScript:
        """Writes a safe shim for the venv's python binary."""
        return self.bin(bash, pex_environment, "python")


@dataclass(frozen=True)
class VenvPex:
    digest: Digest
    pex_filename: str
    pex: Script
    python: Script
    bin: FrozenDict[str, Script]


@frozen_after_init
@dataclass(unsafe_hash=True)
class VenvPexRequest:
    pex_request: PexRequest
    bin_names: Tuple[str, ...] = ()

    def __init__(self, pex_request: PexRequest, bin_names: Iterable[str] = ()) -> None:
        """A request for a PEX that runs in a venv and optionally exposes select vanv `bin` scripts.

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
    request: VenvPexRequest, bash: BashBinary, pex_environment: SandboxPexEnvironment
) -> VenvPex:
    # VenvPex is motivated by improving performance of Python tools by eliminating traditional PEX
    # file startup overhead.
    #
    # To achieve the minimal overhead (on the order of 1ms) we discard:
    # 1. Using Pex `--unzip` mode:
    #    Although this does reduce steady-state overhead, it still leaves a minimum O(100ms) of
    #    overhead per tool invocation. Fundamentally, Pex still needs to execute its `sys.path`
    #    isolation bootstrap code in this case.
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
    venv_dir = pex_environment.pex_root / venv_rel_dir

    venv_script_writer = VenvScriptWriter(pex=venv_pex_result.create_pex(), venv_dir=venv_dir)
    pex = venv_script_writer.exe(bash, pex_environment)
    python = venv_script_writer.python(bash, pex_environment)
    scripts = {
        bin_name: venv_script_writer.bin(bash, pex_environment, bin_name)
        for bin_name in request.bin_names
    }
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
    )


@rule(level=LogLevel.DEBUG)
async def two_step_create_pex(two_step_pex_request: TwoStepPexRequest) -> TwoStepPex:
    """Create a PEX in two steps: a requirements-only PEX and then a full PEX from it."""
    request = two_step_pex_request.pex_request
    req_pex_name = "__requirements.pex"

    repository_pex: Pex | None = None

    # Create a pex containing just the requirements.
    if request.requirements:
        repository_pex = await Get(
            Pex,
            PexRequest(
                output_filename=req_pex_name,
                internal_only=request.internal_only,
                requirements=request.requirements,
                interpreter_constraints=request.interpreter_constraints,
                platforms=request.platforms,
                # TODO: Do we need to pass all the additional args to the requirements pex creation?
                #  Some of them may affect resolution behavior, but others may be irrelevant.
                #  For now we err on the side of caution.
                additional_args=request.additional_args,
                description=(
                    f"Resolving {pluralize(len(request.requirements), 'requirement')}: "
                    f"{', '.join(request.requirements)}"
                ),
            ),
        )

    # Now create a full PEX on top of the requirements PEX.
    full_pex_request = dataclasses.replace(request, repository_pex=repository_pex)
    full_pex = await Get(Pex, PexRequest, full_pex_request)
    return TwoStepPex(pex=full_pex)


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexProcess:
    pex: Pex
    argv: Tuple[str, ...]
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    input_digest: Digest | None
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
        self.extra_env = FrozenDict(extra_env) if extra_env else None
        self.output_files = tuple(output_files) if output_files else None
        self.output_directories = tuple(output_directories) if output_directories else None
        self.timeout_seconds = timeout_seconds
        self.execution_slot_variable = execution_slot_variable
        self.cache_scope = cache_scope


@rule
async def setup_pex_process(request: PexProcess, pex_environment: SandboxPexEnvironment) -> Process:
    pex = request.pex
    argv = pex_environment.create_argv(pex.name, *request.argv, python=pex.python)
    env = {
        **pex_environment.environment_dict(python_configured=pex.python is not None),
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
        env=env,
        output_files=request.output_files,
        output_directories=request.output_directories,
        append_only_caches=pex_environment.append_only_caches,
        timeout_seconds=request.timeout_seconds,
        execution_slot_variable=request.execution_slot_variable,
        cache_scope=request.cache_scope,
    )


@frozen_after_init
@dataclass(unsafe_hash=True)
class VenvPexProcess:
    venv_pex: VenvPex
    argv: Tuple[str, ...]
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    input_digest: Digest | None
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
        self.extra_env = FrozenDict(extra_env) if extra_env else None
        self.output_files = tuple(output_files) if output_files else None
        self.output_directories = tuple(output_directories) if output_directories else None
        self.timeout_seconds = timeout_seconds
        self.execution_slot_variable = execution_slot_variable
        self.cache_scope = cache_scope


@rule
async def setup_venv_pex_process(
    request: VenvPexProcess, pex_environment: SandboxPexEnvironment
) -> Process:
    venv_pex = request.venv_pex
    argv = (venv_pex.pex.argv0, *request.argv)
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
        env=request.extra_env,
        output_files=request.output_files,
        output_directories=request.output_directories,
        append_only_caches=pex_environment.append_only_caches,
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
