# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import itertools
import logging
from dataclasses import dataclass
from typing import FrozenSet, Iterable, Iterator, List, NamedTuple, Optional, Sequence, Set, Tuple

from pants.backend.python.rules.download_pex_bin import DownloadedPexBin
from pants.backend.python.rules.hermetic_pex import HermeticPex
from pants.backend.python.rules.targets import PythonInterpreterCompatibility
from pants.backend.python.rules.targets import PythonPlatforms as PythonPlatformsField
from pants.backend.python.rules.targets import PythonRequirementsField
from pants.backend.python.rules.util import parse_interpreter_constraint
from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import (
    EMPTY_DIRECTORY_DIGEST,
    EMPTY_SNAPSHOT,
    Digest,
    DirectoriesToMerge,
    DirectoryWithPrefixToAdd,
    GlobExpansionConjunction,
    GlobMatchErrorBehavior,
    PathGlobs,
    Snapshot,
)
from pants.engine.isolated_process import MultiPlatformProcess, ProcessResult
from pants.engine.legacy.structs import PythonTargetAdaptor, TargetAdaptor
from pants.engine.platform import Platform, PlatformConstraint
from pants.engine.rules import RootRule, named_rule, rule, subsystem_rule
from pants.engine.selectors import Get
from pants.python.python_repos import PythonRepos
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexRequirements:
    requirements: FrozenOrderedSet[str]

    def __init__(self, requirements: Optional[Iterable[str]] = None) -> None:
        self.requirements = FrozenOrderedSet(sorted(requirements or ()))

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

    @classmethod
    def create_from_adaptors(
        cls, adaptors: Iterable[TargetAdaptor], additional_requirements: Iterable[str] = ()
    ) -> "PexRequirements":
        all_target_requirements = set()
        for maybe_python_req_lib in adaptors:
            # This is a python_requirement()-like target.
            if hasattr(maybe_python_req_lib, "requirement"):
                all_target_requirements.add(str(maybe_python_req_lib.requirement))
            # This is a python_requirement_library()-like target.
            if hasattr(maybe_python_req_lib, "requirements"):
                for py_req in maybe_python_req_lib.requirements:
                    all_target_requirements.add(str(py_req.requirement))
        all_target_requirements.update(additional_requirements)
        return PexRequirements(all_target_requirements)


Spec = Tuple[str, str]  # e.g. (">=", "3.6")


class ParsedConstraint(NamedTuple):
    interpreter: str
    specs: FrozenSet[Spec]

    def __str__(self) -> str:
        specs = ",".join(
            f"{op}{version}" for op, version in sorted(self.specs, key=lambda spec: spec[1])
        )
        return f"{self.interpreter}{specs}"


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexInterpreterConstraints:
    constraints: FrozenOrderedSet[str]

    def __init__(self, constraints: Optional[Iterable[str]] = None) -> None:
        self.constraints = FrozenOrderedSet(sorted(constraints or ()))

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
                        interpreter: sorted(
                            str(parsed_constraint) for parsed_constraint in parsed_constraints
                        )
                        for interpreter, parsed_constraints in itertools.groupby(
                            parsed_constraints,
                            key=lambda parsed_constraint: parsed_constraint.interpreter,
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
    def create_from_adaptors(
        cls, adaptors: Iterable[TargetAdaptor], python_setup: PythonSetup
    ) -> "PexInterpreterConstraints":
        constraint_sets: Set[Iterable[str]] = set()
        for adaptor in adaptors:
            if not isinstance(adaptor, PythonTargetAdaptor):
                continue
            compatibility_field = PythonInterpreterCompatibility(
                adaptor.compatibility, address=adaptor.address
            )
            constraint_sets.add(compatibility_field.value_or_global_default(python_setup))
        # This will OR within each target and AND across targets.
        merged_constraints = cls.merge_constraint_sets(constraint_sets)
        return PexInterpreterConstraints(merged_constraints)

    def generate_pex_arg_list(self) -> List[str]:
        args = []
        for constraint in sorted(self.constraints):
            args.extend(["--interpreter-constraint", constraint])
        return args


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexPlatforms:
    platforms: FrozenOrderedSet[str]

    def __init__(self, platforms: Optional[Iterable[str]] = None) -> None:
        self.platforms = FrozenOrderedSet(sorted(platforms or ()))

    @classmethod
    def create_from_platforms_field(cls, field: PythonPlatformsField) -> "PexPlatforms":
        # TODO(#9562): wire to `--python-setup-platforms` once we know when/where it should be used.
        return cls(field.value or ())

    def generate_pex_arg_list(self) -> List[str]:
        args = []
        for platform in sorted(self.platforms):
            args.extend(["--platform", platform])
        return args


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexRequest:
    """A generic request to create a PEX from its inputs."""

    output_filename: str
    requirements: PexRequirements
    interpreter_constraints: PexInterpreterConstraints
    platforms: PexPlatforms
    sources: Optional[Digest]
    additional_inputs: Optional[Digest]
    entry_point: Optional[str]
    additional_args: Tuple[str, ...]
    # A human-readable description to use in the UI.  This field doesn't participate
    # in comparison (and therefore hashing), as it doesn't affect the result.
    description: Optional[str] = dataclasses.field(compare=False)

    def __init__(
        self,
        *,
        output_filename: str,
        requirements: PexRequirements = PexRequirements(),
        interpreter_constraints=PexInterpreterConstraints(),
        platforms=PexPlatforms(),
        sources: Optional[Digest] = None,
        additional_inputs: Optional[Digest] = None,
        entry_point: Optional[str] = None,
        additional_args: Iterable[str] = (),
        description: Optional[str] = None,
    ) -> None:
        self.output_filename = output_filename
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
class Pex(HermeticPex):
    """Wrapper for a digest containing a pex file created with some filename."""

    directory_digest: Digest
    output_filename: str


@dataclass(frozen=True)
class TwoStepPex:
    """The result of creating a PEX in two steps.

    TODO(9320): A workaround for https://github.com/pantsbuild/pants/issues/9320. Really we
      just want the rules to directly return a Pex.
    """

    pex: Pex


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PexDebug:
    log_level: LogLevel

    _PEX_LEVEL_BY_PANTS_LEVEL = {
        LogLevel.TRACE: 9,
        LogLevel.DEBUG: 3,
    }

    @memoized_property
    def level(self) -> int:
        return self._PEX_LEVEL_BY_PANTS_LEVEL.get(self.log_level, 0)

    def iter_pex_args(self) -> Iterator[str]:
        yield "--no-emit-warnings"
        if self.level > 0:
            yield f"-{'v' * self.level}"

    @property
    def might_log(self):
        return self.level > 0

    def log(self, *args, **kwargs) -> None:
        self.log_level.log(logger, *args, **kwargs)


@named_rule(desc="Create PEX")
async def create_pex(
    request: PexRequest,
    pex_bin: DownloadedPexBin,
    python_setup: PythonSetup,
    python_repos: PythonRepos,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
    pex_build_environment: PexBuildEnvironment,
    platform: Platform,
    log_level: LogLevel,
) -> Pex:
    """Returns a PEX with the given requirements, optional entry point, optional interpreter
    constraints, and optional requirement constraints."""

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

    # NB: If `--platform` is specified, this signals that the PEX should not be built locally.
    # `--interpreter-constraint` only makes sense in the context of building locally. These two
    # flags are mutually exclusive. See https://github.com/pantsbuild/pex/issues/957.
    if request.platforms.platforms:
        # TODO(#9560): consider validating that these platforms are valid with the interpreter
        #  constraints.
        argv.extend(request.platforms.generate_pex_arg_list())
    else:
        argv.extend(request.interpreter_constraints.generate_pex_arg_list())

    pex_debug = PexDebug(log_level)
    argv.extend(pex_debug.iter_pex_args())

    if python_setup.resolver_jobs:
        argv.extend(["--jobs", python_setup.resolver_jobs])

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

    argv.extend(request.requirements.requirements)

    constraint_file_snapshot = EMPTY_SNAPSHOT
    if python_setup.requirement_constraints is not None:
        constraint_file_snapshot = await Get[Snapshot](
            PathGlobs(
                [python_setup.requirement_constraints],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                conjunction=GlobExpansionConjunction.all_match,
                description_of_origin="the option `--python-setup-requirement-constraints`",
            )
        )

    sources_digest_as_subdir = await Get[Digest](
        DirectoryWithPrefixToAdd(request.sources or EMPTY_DIRECTORY_DIGEST, source_dir_name)
    )
    additional_inputs_digest = request.additional_inputs or EMPTY_DIRECTORY_DIGEST

    merged_digest = await Get[Digest](
        DirectoriesToMerge(
            directories=(
                pex_bin.directory_digest,
                sources_digest_as_subdir,
                additional_inputs_digest,
                constraint_file_snapshot.directory_digest,
            )
        )
    )

    # NB: PEX outputs are platform dependent so in order to get a PEX that we can use locally, without
    # cross-building, we specify that our PEX command be run on the current local platform. When we
    # support cross-building through CLI flags we can configure requests that build a PEX for our
    # local platform that are able to execute on a different platform, but for now in order to
    # guarantee correct build we need to restrict this command to execute on the same platform type
    # that the output is intended for. The correct way to interpret the keys
    # (execution_platform_constraint, target_platform_constraint) of this dictionary is "The output of
    # this command is intended for `target_platform_constraint` iff it is run on `execution_platform
    # constraint`".
    description = request.description
    if description is None:
        if request.requirements.requirements:
            description = f"Resolving {', '.join(request.requirements.requirements)}"
        else:
            description = f"Building PEX"
    process = MultiPlatformProcess(
        {
            (
                PlatformConstraint(platform.value),
                PlatformConstraint(platform.value),
            ): pex_bin.create_execute_request(
                python_setup=python_setup,
                subprocess_encoding_environment=subprocess_encoding_environment,
                pex_build_environment=pex_build_environment,
                pex_args=argv,
                input_files=merged_digest,
                description=description,
                output_files=(request.output_filename,),
            )
        }
    )

    result = await Get[ProcessResult](MultiPlatformProcess, process)

    if pex_debug.might_log:
        lines = result.stderr.decode().splitlines()
        if lines:
            pex_debug.log(f"Debug output from Pex for: {process}")
            for line in lines:
                pex_debug.log(line)

    return Pex(
        directory_digest=result.output_directory_digest, output_filename=request.output_filename
    )


@rule
async def two_step_create_pex(two_step_pex_request: TwoStepPexRequest) -> TwoStepPex:
    """Create a PEX in two steps: a requirements-only PEX and then a full PEX from it."""
    request = two_step_pex_request.pex_request
    req_pex_name = "__requirements.pex"

    additional_inputs: Optional[Digest]

    # Create a pex containing just the requirements.
    if request.requirements.requirements:
        requirements_pex_request = PexRequest(
            output_filename=req_pex_name,
            requirements=request.requirements,
            interpreter_constraints=request.interpreter_constraints,
            platforms=request.platforms,
            # TODO: Do we need to pass all the additional args to the requirements pex creation?
            #  Some of them may affect resolution behavior, but others may be irrelevant.
            #  For now we err on the side of caution.
            additional_args=request.additional_args,
            description=f"Resolving {', '.join(request.requirements.requirements)}",
        )
        requirements_pex = await Get[Pex](PexRequest, requirements_pex_request)
        additional_inputs = requirements_pex.directory_digest
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
    full_pex = await Get[Pex](PexRequest, full_pex_request)
    return TwoStepPex(pex=full_pex)


def rules():
    return [
        create_pex,
        two_step_create_pex,
        RootRule(PexRequest),
        RootRule(TwoStepPexRequest),
        subsystem_rule(PythonSetup),
        subsystem_rule(PythonRepos),
    ]
