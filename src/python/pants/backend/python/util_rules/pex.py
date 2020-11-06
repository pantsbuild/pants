# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import functools
import itertools
import logging
from collections import defaultdict
from dataclasses import dataclass
from textwrap import dedent
from typing import (
    FrozenSet,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeVar,
    Union,
)

from pkg_resources import Requirement
from typing_extensions import Protocol

from pants.backend.python.target_types import InterpreterConstraintsField
from pants.backend.python.target_types import PexPlatformsField as PythonPlatformsField
from pants.backend.python.target_types import (
    PythonInterpreterCompatibility,
    PythonRequirementsField,
)
from pants.backend.python.util_rules import pex_cli
from pants.backend.python.util_rules.pex_cli import PexCliProcess
from pants.backend.python.util_rules.pex_environment import (
    PexEnvironment,
    PexRuntimeEnvironment,
    PythonExecutable,
)
from pants.engine.addresses import Address
from pants.engine.collection import DeduplicatedCollection
from pants.engine.engine_aware import EngineAwareParameter
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
from pants.engine.process import (
    MultiPlatformProcess,
    Process,
    ProcessResult,
    ProcessScope,
    UncacheableProcess,
)
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import InvalidFieldException, Target
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
    ) -> "PexRequirements":
        field_requirements = {str(python_req) for field in fields for python_req in field.value}
        return PexRequirements({*field_requirements, *additional_requirements})


# This protocol allows us to work with any arbitrary FieldSet. See
# https://mypy.readthedocs.io/en/stable/protocols.html.
class FieldSetWithCompatibility(Protocol):
    @property
    def address(self) -> Address:
        ...

    @property
    def compatibility(self) -> PythonInterpreterCompatibility:
        ...

    @property
    def interpreter_constraints(self) -> InterpreterConstraintsField:
        ...


_FS = TypeVar("_FS", bound=FieldSetWithCompatibility)


# Normally we would subclass `DeduplicatedCollection`, but we want a custom constructor.
class PexInterpreterConstraints(FrozenOrderedSet[Requirement], EngineAwareParameter):
    def __init__(self, constraints: Iterable[Union[str, Requirement]] = ()) -> None:
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
    def resolve_conflicting_fields(
        cls,
        deprecated: PythonInterpreterCompatibility,
        new: InterpreterConstraintsField,
        address: Address,
    ) -> Union[PythonInterpreterCompatibility, InterpreterConstraintsField]:
        if deprecated.value and new.value:
            raise InvalidFieldException(
                f"Specified both the deprecated `{deprecated.alias}` field and the new "
                f"`{new.alias}` field for the target {address}. Please use only one "
                f"(preferably {new.alias})"
            )
        if deprecated.value:
            return deprecated
        return new

    @classmethod
    def create_from_targets(
        cls, targets: Iterable[Target], python_setup: PythonSetup
    ) -> "PexInterpreterConstraints":
        fields = []
        for tgt in targets:
            has_deprecated = tgt.has_field(PythonInterpreterCompatibility)
            has_new = tgt.has_field(InterpreterConstraintsField)
            if has_deprecated and has_new:
                fields.append(
                    cls.resolve_conflicting_fields(
                        tgt[PythonInterpreterCompatibility],
                        tgt[InterpreterConstraintsField],
                        tgt.address,
                    )
                )
            elif has_deprecated:
                fields.append(tgt[PythonInterpreterCompatibility])
            elif has_new:
                fields.append(tgt[InterpreterConstraintsField])
        return cls.create_from_compatibility_fields(fields, python_setup)

    @classmethod
    def create_from_compatibility_fields(
        cls,
        fields: Iterable[Union[InterpreterConstraintsField, PythonInterpreterCompatibility]],
        python_setup: PythonSetup,
    ) -> "PexInterpreterConstraints":
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
            constraints_field = cls.resolve_conflicting_fields(
                fs.compatibility, fs.interpreter_constraints, fs.address
            )
            constraints = cls.create_from_compatibility_fields([constraints_field], python_setup)
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

    def minimum_python_version(self) -> Optional[str]:
        """Find the lowest major.minor Python version that will work with these constraints.

        The constraints may also be compatible with later versions; this is the lowest version that
        still works.
        """
        if self.includes_python2():
            return "2.7"
        max_expected_py3_patch_version = 12  # The current max is 9.
        for major_minor in ("3.5", "3.6", "3.7", "3.8", "3.9", "3.10"):
            if self._includes_version(major_minor, last_patch=max_expected_py3_patch_version):
                return major_minor
        return None

    def _requires_python3_version_or_newer(
        self, *, allowed_versions: Iterable[str], prior_version: str
    ) -> bool:
        # Assume any 3.x release has no more than 13 releases. The max is currently 10.
        patch_versions = list(reversed(range(0, 13)))
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
            allowed_versions=["3.8", "3.9"], prior_version="3.7"
        )

    def __str__(self) -> str:
        return " OR ".join(str(constraint) for constraint in self)

    def debug_hint(self) -> str:
        return str(self)


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
class PexRequest(EngineAwareParameter):
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
    python: Optional[PythonExecutable]


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
    process = await Get(
        Process,
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
        ),
    )
    result = await Get(
        ProcessResult, UncacheableProcess(process=process, scope=ProcessScope.PER_SESSION)
    )
    path, fingerprint = result.stdout.decode().strip().splitlines()

    if pex_runtime_env.verbosity > 0:
        log_output = result.stderr.decode()
        if log_output:
            logger.info("%s", log_output)

    return PythonExecutable(path=path, fingerprint=fingerprint)


@rule(level=LogLevel.DEBUG)
async def create_pex(
    request: PexRequest,
    python_setup: PythonSetup,
    python_repos: PythonRepos,
    platform: Platform,
    pex_runtime_env: PexRuntimeEnvironment,
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
        "--cache-ttl",
        str(python_setup.resolver_http_cache_ttl),
        *request.additional_args,
    ]

    python: Optional[PythonExecutable] = None

    # NB: If `--platform` is specified, this signals that the PEX should not be built locally.
    # `--interpreter-constraint` only makes sense in the context of building locally. These two
    # flags are mutually exclusive. See https://github.com/pantsbuild/pex/issues/957.
    if request.platforms:
        # TODO(#9560): consider validating that these platforms are valid with the interpreter
        #  constraints.
        argv.extend(request.platforms.generate_pex_arg_list())
    else:
        # NB: If it's an internal_only PEX, we do our own lookup of the interpreter based on the
        # interpreter constraints, and then will run the PEX with that specific interpreter. We
        # will have already validated that there were no platforms.
        # Otherwise, we let Pex resolve the constraints.
        if request.internal_only:
            python = await Get(
                PythonExecutable, PexInterpreterConstraints, request.interpreter_constraints
            )
        else:
            argv.extend(request.interpreter_constraints.generate_pex_arg_list())

    argv.append("--no-emit-warnings")

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
        MergeDigests(
            (
                sources_digest_as_subdir,
                additional_inputs_digest,
                constraint_file_digest,
            )
        ),
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
    result = await Get(
        ProcessResult,
        MultiPlatformProcess(
            {(PlatformConstraint(platform.value), PlatformConstraint(platform.value)): process}
        ),
    )

    if pex_runtime_env.verbosity > 0:
        log_output = result.stderr.decode()
        if log_output:
            logger.info("%s", log_output)

    return Pex(digest=result.output_digest, name=request.output_filename, python=python)


@rule(level=LogLevel.DEBUG)
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
    uncacheable: bool

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
        uncacheable: bool = False,
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
        self.uncacheable = uncacheable


@rule
async def setup_pex_process(request: PexProcess, pex_environment: PexEnvironment) -> Process:
    argv = pex_environment.create_argv(
        f"./{request.pex.name}",
        *request.argv,
        python=request.pex.python,
    )
    env = {
        **pex_environment.environment_dict(python_configured=request.pex.python is not None),
        **(request.extra_env or {}),
    }
    process = Process(
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
    return await Get(Process, UncacheableProcess(process)) if request.uncacheable else process


def rules():
    return [*collect_rules(), *pex_cli.rules()]
