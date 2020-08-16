# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import itertools
import logging
from dataclasses import dataclass
from typing import (
    FrozenSet,
    Iterable,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeVar,
)

from typing_extensions import Protocol

from pants.backend.python.rules import pex_cli
from pants.backend.python.rules.pex_cli import PexCliProcess
from pants.backend.python.rules.pex_environment import PexEnvironment, PexRuntimeEnvironment
from pants.backend.python.rules.util import parse_interpreter_constraint
from pants.backend.python.target_types import PythonInterpreterCompatibility
from pants.backend.python.target_types import PythonPlatforms as PythonPlatformsField
from pants.backend.python.target_types import PythonRequirementsField
from pants.engine.addresses import Address
from pants.engine.collection import DeduplicatedCollection
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    Digest,
    GlobExpansionConjunction,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
from pants.engine.platform import Platform, PlatformConstraint
from pants.engine.process import MultiPlatformProcess, Process, ProcessResult
from pants.engine.rules import Get, RootRule, collect_rules, rule
from pants.python.python_repos import PythonRepos
from pants.python.python_setup import PythonSetup
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.strutil import pluralize


class PexRequirements(DeduplicatedCollection[str]):
    sort_input = True

    @classmethod
    def create_from_requirement_fields(
        cls,
        fields: Iterable[PythonRequirementsField],
        *,
        additional_requirements: Iterable[str] = (),
    ) -> "PexRequirements":
        field_requirements = {
            str(python_req.requirement) for field in fields for python_req in field.value
        }
        return PexRequirements({*field_requirements, *additional_requirements})


Spec = Tuple[str, str]  # e.g. (">=", "3.6")


class ParsedConstraint(NamedTuple):
    interpreter: str
    specs: FrozenSet[Spec]

    def __str__(self) -> str:
        specs = ",".join(
            f"{op}{version}" for op, version in sorted(self.specs, key=lambda spec: spec[1])
        )
        return f"{self.interpreter}{specs}"


# This protocol allows us to work with any arbitrary FieldSet. See
# https://mypy.readthedocs.io/en/stable/protocols.html.
class FieldSetWithCompatibility(Protocol):
    @property
    def address(self) -> Address:
        ...

    @property
    def compatibility(self) -> PythonInterpreterCompatibility:
        ...


_FS = TypeVar("_FS", bound=FieldSetWithCompatibility)


class PexInterpreterConstraints(DeduplicatedCollection[str]):
    sort_input = True

    @staticmethod
    def merge_constraint_sets(constraint_sets: Iterable[Iterable[str]]) -> List[str]:
        """Given a collection of constraints sets, merge by ORing within each individual constraint
        set and ANDing across each distinct constraint set.

        For example, given `[["CPython>=2.7", "CPython<=3"], ["CPython==3.6.*"]]`, return
        `["CPython>=2.7,==3.6.*", "CPython<=3,==3.6.*"]`.
        """
        # Each element (a Set[ParsedConstraint]) will get ANDed. We use sets to deduplicate
        # identical top-level parsed constraint sets.
        if not constraint_sets:
            return []
        parsed_constraint_sets: Set[FrozenSet[ParsedConstraint]] = set()
        for constraint_set in constraint_sets:
            # Each element (a ParsedConstraint) will get ORed.
            parsed_constraint_set: Set[ParsedConstraint] = set()
            for constraint in constraint_set:
                parsed_requirement = parse_interpreter_constraint(constraint)
                interpreter = parsed_requirement.project_name
                specs = frozenset(parsed_requirement.specs)
                parsed_constraint_set.add(ParsedConstraint(interpreter, specs))
            parsed_constraint_sets.add(frozenset(parsed_constraint_set))

        def and_constraints(parsed_constraints: Sequence[ParsedConstraint]) -> ParsedConstraint:
            merged_specs: Set[Spec] = set()
            expected_interpreter = parsed_constraints[0][0]
            for parsed_constraint in parsed_constraints:
                if parsed_constraint.interpreter != expected_interpreter:
                    attempted_interpreters = {
                        interp: sorted(
                            str(parsed_constraint) for parsed_constraint in parsed_constraints
                        )
                        for interp, parsed_constraints in itertools.groupby(
                            parsed_constraints, key=lambda pc: pc.interpreter,
                        )
                    }
                    raise ValueError(
                        "Tried ANDing Python interpreter constraints with different interpreter "
                        "types. Please use only one interpreter type. Got "
                        f"{attempted_interpreters}."
                    )
                merged_specs.update(parsed_constraint.specs)
            return ParsedConstraint(expected_interpreter, frozenset(merged_specs))

        return sorted(
            {
                str(and_constraints(constraints_product))
                for constraints_product in itertools.product(*parsed_constraint_sets)
            }
        )

    @classmethod
    def create_from_compatibility_fields(
        cls, fields: Iterable[PythonInterpreterCompatibility], python_setup: PythonSetup
    ) -> "PexInterpreterConstraints":
        constraint_sets = {field.value_or_global_default(python_setup) for field in fields}
        # This will OR within each field and AND across fields.
        merged_constraints = cls.merge_constraint_sets(constraint_sets)
        return PexInterpreterConstraints(merged_constraints)

    @classmethod
    def group_field_sets_by_constraints(
        cls, field_sets: Iterable[_FS], python_setup: PythonSetup
    ) -> FrozenDict["PexInterpreterConstraints", Tuple[_FS, ...]]:
        constraints_to_field_sets = {
            constraints: tuple(sorted(fs_collection, key=lambda fs: fs.address))
            for constraints, fs_collection in itertools.groupby(
                field_sets,
                key=lambda fs: cls.create_from_compatibility_fields(
                    [fs.compatibility], python_setup
                ),
            )
        }
        return FrozenDict(sorted(constraints_to_field_sets.items()))

    def generate_pex_arg_list(self) -> List[str]:
        args = []
        for constraint in self:
            args.extend(["--interpreter-constraint", constraint])
        return args


class PexPlatforms(DeduplicatedCollection[str]):
    sort_input = True

    @classmethod
    def create_from_platforms_field(cls, field: PythonPlatformsField) -> "PexPlatforms":
        return cls(field.value or ())

    def generate_pex_arg_list(self) -> List[str]:
        args = []
        for platform in self:
            args.extend(["--platform", platform])
        return args


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexRequest:
    output_filename: str
    internal_only: bool
    requirements: PexRequirements
    interpreter_constraints: PexInterpreterConstraints
    platforms: PexPlatforms
    sources: Optional[Digest]
    additional_inputs: Optional[Digest]
    entry_point: Optional[str]
    additional_args: Tuple[str, ...]
    description: Optional[str] = dataclasses.field(compare=False)

    def __init__(
        self,
        *,
        output_filename: str,
        internal_only: bool,
        requirements: PexRequirements = PexRequirements(),
        interpreter_constraints=PexInterpreterConstraints(),
        platforms=PexPlatforms(),
        sources: Optional[Digest] = None,
        additional_inputs: Optional[Digest] = None,
        entry_point: Optional[str] = None,
        additional_args: Iterable[str] = (),
        description: Optional[str] = None,
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
        :param entry_point: The entry-point for the built Pex, equivalent to Pex's `-m` flag. If
            left off, the Pex will open up as a REPL.
        :param additional_args: Any additional Pex flags.
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
        self.entry_point = entry_point
        self.additional_args = tuple(additional_args)
        self.description = description


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
    internal_only: bool


@dataclass(frozen=True)
class TwoStepPex:
    """The result of creating a PEX in two steps.

    TODO(9320): A workaround for https://github.com/pantsbuild/pants/issues/9320. Really we
      just want the rules to directly return a Pex.
    """

    pex: Pex


logger = logging.getLogger(__name__)


@rule
async def create_pex(
    request: PexRequest,
    python_setup: PythonSetup,
    python_repos: PythonRepos,
    platform: Platform,
    pex_runtime_environment: PexRuntimeEnvironment,
) -> Pex:
    """Returns a PEX with the given settings."""

    argv = [
        "--output-file",
        request.output_filename,
        # NB: In setting `--no-pypi`, we rely on the default value of `--python-repos-indexes`
        # including PyPI, which will override `--no-pypi` and result in using PyPI in the default
        # case. Why set `--no-pypi`, then? We need to do this so that
        # `--python-repos-repos=['custom_url']` will only point to that index and not include PyPI.
        "--no-pypi",
        *(f"--index={index}" for index in python_repos.indexes),
        *(f"--repo={repo}" for repo in python_repos.repos),
        *request.additional_args,
    ]

    if request.internal_only:
        # This will result in a faster build, but worse compatibility at runtime.
        argv.append("--use-first-matching-interpreter")

    # NB: If `--platform` is specified, this signals that the PEX should not be built locally.
    # `--interpreter-constraint` only makes sense in the context of building locally. These two
    # flags are mutually exclusive. See https://github.com/pantsbuild/pex/issues/957.
    if request.platforms:
        # TODO(#9560): consider validating that these platforms are valid with the interpreter
        #  constraints.
        argv.extend(request.platforms.generate_pex_arg_list())
    else:
        argv.extend(request.interpreter_constraints.generate_pex_arg_list())

    argv.append("--no-emit-warnings")
    verbosity = pex_runtime_environment.verbosity
    if verbosity > 0:
        argv.append(f"-{'v' * verbosity}")

    if python_setup.resolver_jobs:
        argv.extend(["--jobs", str(python_setup.resolver_jobs)])

    if python_setup.manylinux:
        argv.extend(["--manylinux", python_setup.manylinux])
    else:
        argv.append("--no-manylinux")

    if request.entry_point is not None:
        argv.extend(["--entry-point", request.entry_point])

    if python_setup.requirement_constraints is not None:
        argv.extend(["--constraints", python_setup.requirement_constraints])

    source_dir_name = "source_files"
    argv.append(f"--sources-directory={source_dir_name}")

    argv.extend(request.requirements)

    constraint_file_digest = EMPTY_DIGEST
    if python_setup.requirement_constraints is not None:
        constraint_file_digest = await Get(
            Digest,
            PathGlobs(
                [python_setup.requirement_constraints],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                conjunction=GlobExpansionConjunction.all_match,
                description_of_origin="the option `--python-setup-requirement-constraints`",
            ),
        )

    sources_digest_as_subdir = await Get(
        Digest, AddPrefix(request.sources or EMPTY_DIGEST, source_dir_name)
    )
    additional_inputs_digest = request.additional_inputs or EMPTY_DIGEST

    merged_digest = await Get(
        Digest,
        MergeDigests((sources_digest_as_subdir, additional_inputs_digest, constraint_file_digest,)),
    )

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
            argv=argv,
            additional_input_digest=merged_digest,
            description=description,
            output_files=[request.output_filename],
        ),
    )

    # NB: Building a Pex is platform dependent, so in order to get a PEX that we can use locally
    # without cross-building, we specify that our PEX command should be run on the current local
    # platform.
    result = await Get(
        ProcessResult,
        MultiPlatformProcess(
            {(PlatformConstraint(platform.value), PlatformConstraint(platform.value)): process}
        ),
    )

    if verbosity > 0:
        log_output = result.stderr.decode()
        if log_output:
            logger.info("%s", log_output)

    return Pex(
        digest=result.output_digest,
        name=request.output_filename,
        internal_only=request.internal_only,
    )


@rule
async def two_step_create_pex(two_step_pex_request: TwoStepPexRequest) -> TwoStepPex:
    """Create a PEX in two steps: a requirements-only PEX and then a full PEX from it."""
    request = two_step_pex_request.pex_request
    req_pex_name = "__requirements.pex"

    additional_inputs: Optional[Digest]

    # Create a pex containing just the requirements.
    if request.requirements:
        requirements_pex_request = PexRequest(
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
        )
        requirements_pex = await Get(Pex, PexRequest, requirements_pex_request)
        additional_inputs = requirements_pex.digest
        additional_args = (*request.additional_args, f"--requirements-pex={req_pex_name}")
    else:
        additional_inputs = None
        additional_args = request.additional_args

    # Now create a full PEX on top of the requirements PEX.
    full_pex_request = dataclasses.replace(
        request,
        requirements=PexRequirements(),
        additional_inputs=additional_inputs,
        additional_args=additional_args,
    )
    full_pex = await Get(Pex, PexRequest, full_pex_request)
    return TwoStepPex(pex=full_pex)


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexProcess:
    pex: Pex
    argv: Tuple[str, ...]
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    input_digest: Digest
    extra_env: Optional[FrozenDict[str, str]]
    output_files: Optional[Tuple[str, ...]]
    output_directories: Optional[Tuple[str, ...]]
    timeout_seconds: Optional[int]
    execution_slot_variable: Optional[str]

    def __init__(
        self,
        pex: Pex,
        *,
        argv: Iterable[str],
        description: str,
        level: LogLevel = LogLevel.INFO,
        input_digest: Optional[Digest] = None,
        extra_env: Optional[Mapping[str, str]] = None,
        output_files: Optional[Iterable[str]] = None,
        output_directories: Optional[Iterable[str]] = None,
        timeout_seconds: Optional[int] = None,
        execution_slot_variable: Optional[str] = None,
    ) -> None:
        self.pex = pex
        self.argv = tuple(argv)
        self.description = description
        self.level = level
        self.input_digest = input_digest or pex.digest
        self.extra_env = FrozenDict(extra_env) if extra_env else None
        self.output_files = tuple(output_files) if output_files else None
        self.output_directories = tuple(output_directories) if output_directories else None
        self.timeout_seconds = timeout_seconds
        self.execution_slot_variable = execution_slot_variable


@rule
async def setup_pex_process(request: PexProcess, pex_environment: PexEnvironment) -> Process:
    argv = pex_environment.create_argv(
        f"./{request.pex.name}",
        *request.argv,
        # If the Pex isn't distributed to users, then we must use the shebang because we will have
        # used the flag `--use-first-matching-interpreter`, which requires running via shebang.
        always_use_shebang=request.pex.internal_only,
    )
    env = {**pex_environment.environment_dict, **(request.extra_env or {})}
    return Process(
        argv,
        description=request.description,
        level=request.level,
        input_digest=request.input_digest,
        env=env,
        output_files=request.output_files,
        output_directories=request.output_directories,
        timeout_seconds=request.timeout_seconds,
        execution_slot_variable=request.execution_slot_variable,
    )


def rules():
    return [
        *collect_rules(),
        *pex_cli.rules(),
        RootRule(PexProcess),
        RootRule(PexRequest),
        RootRule(TwoStepPexRequest),
    ]
