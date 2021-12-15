# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import enum
import itertools
import logging
import os
import pickle
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from functools import partial
from typing import Any, DefaultDict, Dict, List, Mapping, Tuple, cast

from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.subsystems.setuptools import PythonDistributionFieldSet
from pants.backend.python.target_types import (
    GenerateSetupField,
    PythonDistributionEntryPointsField,
    PythonGeneratingSourcesBase,
    PythonProvidesField,
    PythonRequirementsField,
    PythonSourceField,
    ResolvedPythonDistributionEntryPoints,
    ResolvePythonDistributionEntryPointsRequest,
    SDistConfigSettingsField,
    SDistField,
    WheelConfigSettingsField,
    WheelField,
)
from pants.backend.python.util_rules.dists import (
    BuildSystem,
    BuildSystemRequest,
    DistBuildRequest,
    DistBuildResult,
    distutils_repr,
)
from pants.backend.python.util_rules.dists import rules as dists_rules
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequirements
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFilesRequest,
    StrippedPythonSourceFiles,
)
from pants.backend.python.util_rules.python_sources import rules as python_sources_rules
from pants.base.specs import AddressSpecs, AscendantAddresses
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.core.util_rules.stripped_source_files import StrippedSourceFileNames
from pants.engine.addresses import Address, UnparsedAddressInputs
from pants.engine.collection import Collection, DeduplicatedCollection
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    DigestSubset,
    FileContent,
    MergeDigests,
    PathGlobs,
    Snapshot,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    SourcesField,
    SourcesPaths,
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
    targets_with_sources_types,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


class SetupPyError(Exception):
    def __init__(self, msg: str):
        super().__init__(f"{msg} See {doc_url('python-distributions')}.")


class InvalidSetupPyArgs(SetupPyError):
    """Indicates invalid arguments to setup.py."""


class TargetNotExported(SetupPyError):
    """Indicates a target that was expected to be exported is not."""


class InvalidEntryPoint(SetupPyError):
    """Indicates that a specified binary entry point was invalid."""


class OwnershipError(SetupPyError):
    """An error related to target ownership calculation."""

    def __init__(self, msg: str):
        super().__init__(
            f"{msg} See {doc_url('python-distributions')} for "
            f"how python_sources targets are mapped to distributions."
        )


class NoOwnerError(OwnershipError):
    """Indicates an exportable target has no owning exported target."""


class AmbiguousOwnerError(OwnershipError):
    """Indicates an exportable target has more than one owning exported target."""


@dataclass(frozen=True)
class ExportedTarget:
    """A target that explicitly exports a setup.py artifact, using a `provides=` stanza.

    The code provided by this artifact can be from this target or from any targets it owns.
    """

    target: Target  # In practice, a PythonDistribution.

    @property
    def provides(self) -> PythonArtifact:
        return self.target[PythonProvidesField].value


@dataclass(frozen=True)
class DependencyOwner:
    """An ExportedTarget in its role as an owner of other targets.

    We need this type to prevent rule ambiguities when computing the list of targets owned by an
    ExportedTarget (which involves going from ExportedTarget -> dep -> owner (which is itself an
    ExportedTarget) and checking if owner is the original ExportedTarget.
    """

    exported_target: ExportedTarget


@dataclass(frozen=True)
class OwnedDependency:
    """A target that is owned by some ExportedTarget.

    Code in this target is published in the owner's distribution.

    The owner of a target T is T's closest filesystem ancestor among the python_distribution
    targets that directly or indirectly depend on it (including T itself).
    """

    target: Target


class OwnedDependencies(Collection[OwnedDependency]):
    pass


class ExportedTargetRequirements(DeduplicatedCollection[str]):
    """The requirements of an ExportedTarget.

    Includes:
    - The "normal" 3rdparty requirements of the ExportedTarget and all targets it owns.
    - The published versions of any other ExportedTargets it depends on.
    """

    sort_input = True


@dataclass(frozen=True)
class DistBuildSources:
    """The sources required to build a distribution.

    Includes some information derived from analyzing the source, namely the packages, namespace
    packages and resource files in the source.
    """

    digest: Digest
    packages: tuple[str, ...]
    namespace_packages: tuple[str, ...]
    package_data: tuple[PackageDatum, ...]


@dataclass(frozen=True)
class DistBuildChrootRequest:
    """A request to create a chroot for building a dist in."""

    exported_target: ExportedTarget
    py2: bool  # Whether to use py2 or py3 package semantics.


@frozen_after_init
@dataclass(unsafe_hash=True)
class SetupKwargs:
    """The keyword arguments to the `setup()` function in the generated `setup.py`."""

    _pickled_bytes: bytes

    def __init__(
        self, kwargs: Mapping[str, Any], *, address: Address, _allow_banned_keys: bool = False
    ) -> None:
        super().__init__()
        if "name" not in kwargs:
            raise InvalidSetupPyArgs(
                f"Missing a `name` kwarg in the `provides` field for {address}."
            )
        if "version" not in kwargs:
            raise InvalidSetupPyArgs(
                f"Missing a `version` kwarg in the `provides` field for {address}."
            )

        if not _allow_banned_keys:
            for arg in {
                "data_files",
                "namespace_packages",
                "package_dir",
                "package_data",
                "packages",
                "install_requires",
            }:
                if arg in kwargs:
                    raise ValueError(
                        f"{arg} cannot be set in the `provides` field for {address}, but it was "
                        f"set to {kwargs[arg]}. Pants will dynamically set the value for you."
                    )

        # We serialize with `pickle` so that is hashable. We don't use `FrozenDict` because it
        # would require that all values are immutable, and we may have lists and dictionaries as
        # values. It's too difficult/clunky to convert those all, then to convert them back out of
        # `FrozenDict`. We don't use JSON because it does not preserve data types like `tuple`.
        self._pickled_bytes = pickle.dumps({k: v for k, v in sorted(kwargs.items())}, protocol=4)

    @memoized_property
    def kwargs(self) -> dict[str, Any]:
        return cast(Dict[str, Any], pickle.loads(self._pickled_bytes))

    @property
    def name(self) -> str:
        return cast(str, self.kwargs["name"])

    @property
    def version(self) -> str:
        return cast(str, self.kwargs["version"])


# Note: This only exists as a hook for additional logic for the `setup()` kwargs, e.g. for plugin
# authors. To resolve `SetupKwargs`, call `await Get(SetupKwargs, ExportedTarget)`, which handles
# running any custom implementations vs. using the default implementation.
@union
@dataclass(frozen=True)  # type: ignore[misc]
class SetupKwargsRequest(ABC):
    """A request to allow setting the kwargs passed to the `setup()` function.

    By default, Pants will pass the kwargs provided in the BUILD file unchanged. To customize this
    behavior, subclass `SetupKwargsRequest`, register the rule `UnionRule(SetupKwargsRequest,
    MyCustomSetupKwargsRequest)`, and add a rule that takes your subclass as a parameter and returns
    `SetupKwargs`.
    """

    target: Target

    @classmethod
    @abstractmethod
    def is_applicable(cls, target: Target) -> bool:
        """Whether the kwargs implementation should be used for this target or not."""

    @property
    def explicit_kwargs(self) -> dict[str, Any]:
        return self.target[PythonProvidesField].value.kwargs


class FinalizedSetupKwargs(SetupKwargs):
    """The final kwargs used for the `setup()` function, after Pants added requirements and sources
    information."""

    def __init__(self, kwargs: Mapping[str, Any], *, address: Address) -> None:
        super().__init__(kwargs, address=address, _allow_banned_keys=True)


@dataclass(frozen=True)
class DistBuildChroot:
    """A chroot containing PEP 517 build setup and the sources it operates on."""

    digest: Digest
    working_directory: str  # Path to dir within digest.


@enum.unique
class FirstPartyDependencyVersionScheme(enum.Enum):
    EXACT = "exact"  # i.e., ==
    COMPATIBLE = "compatible"  # i.e., ~=
    ANY = "any"  # i.e., no specifier


class SetupPyGeneration(Subsystem):
    options_scope = "setup-py-generation"
    help = "Options to control how setup.py is generated from a `python_distribution` target."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        # Generating setup is the more aggressive thing to do, so we'd prefer that the default
        # be False. However that would break widespread existing usage, so we'll make that
        # change in a future deprecation cycle.
        register(
            "--generate-setup-default",
            type=bool,
            default=True,
            help=(
                "The default value for the `generate_setup` field on `python_distribution` targets."
                "Can be overridden per-target by setting that field explicitly. Set this to False "
                "if you mostly rely on handwritten setup files (setup.py, setup.cfg and similar). "
                "Leave as True if you mostly rely on Pants generating setup files for you."
            ),
        )

        register(
            "--first-party-dependency-version-scheme",
            type=FirstPartyDependencyVersionScheme,
            default=FirstPartyDependencyVersionScheme.EXACT,
            help=(
                "What version to set in `install_requires` when a `python_distribution` depends on "
                "other `python_distribution`s. If `exact`, will use `==`. If `compatible`, will "
                "use `~=`. If `any`, will leave off the version. See "
                "https://www.python.org/dev/peps/pep-0440/#version-specifiers."
            ),
        )

    @property
    def generate_setup_default(self) -> bool:
        return cast(bool, self.options.generate_setup_default)

    def first_party_dependency_version(self, version: str) -> str:
        """Return the version string (e.g. '~=4.0') for a first-party dependency.

        If the user specified to use "any" version, then this will return an empty string.
        """
        scheme = self.options.first_party_dependency_version_scheme
        if scheme == FirstPartyDependencyVersionScheme.ANY:
            return ""
        specifier = "==" if scheme == FirstPartyDependencyVersionScheme.EXACT else "~="
        return f"{specifier}{version}"


def validate_commands(commands: tuple[str, ...]):
    # We rely on the dist dir being the default, so we know where to find the created dists.
    if "--dist-dir" in commands or "-d" in commands:
        raise InvalidSetupPyArgs(
            "Cannot set --dist-dir/-d in setup.py args. To change where dists "
            "are written, use the global --pants-distdir option."
        )
    # We don't allow publishing via setup.py, as we don't want the setup.py running rule,
    # which is not a @goal_rule, to side-effect (plus, we'd need to ensure that publishing
    # happens in dependency order).  Note that `upload` and `register` were removed in
    # setuptools 42.0.0, in favor of Twine, but we still check for them in case the user modified
    # the default version used by our Setuptools subsystem.
    if "upload" in commands or "register" in commands:
        raise InvalidSetupPyArgs("Cannot use the `upload` or `register` setup.py commands.")


class NoDistTypeSelected(ValueError):
    pass


@rule
async def package_python_dist(
    field_set: PythonDistributionFieldSet,
    python_setup: PythonSetup,
) -> BuiltPackage:
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address]))
    exported_target = ExportedTarget(transitive_targets.roots[0])

    dist_tgt = exported_target.target
    wheel = dist_tgt.get(WheelField).value
    sdist = dist_tgt.get(SDistField).value
    if not wheel and not sdist:
        raise NoDistTypeSelected(
            f"In order to package {dist_tgt.address.spec} at least one of {WheelField.alias!r} or "
            f"{SDistField.alias!r} must be `True`."
        )

    wheel_config_settings = dist_tgt.get(WheelConfigSettingsField).value or FrozenDict()
    sdist_config_settings = dist_tgt.get(SDistConfigSettingsField).value or FrozenDict()

    interpreter_constraints = InterpreterConstraints.create_from_targets(
        transitive_targets.closure, python_setup
    ) or InterpreterConstraints(python_setup.interpreter_constraints)
    chroot = await Get(
        DistBuildChroot,
        DistBuildChrootRequest(
            exported_target,
            py2=interpreter_constraints.includes_python2(),
        ),
    )

    # We prefix the entire chroot, and run with this prefix as the cwd, so that we can capture
    # any changes setup made within it without also capturing other artifacts of the pex
    # process invocation.
    chroot_prefix = "chroot"
    working_directory = os.path.join(chroot_prefix, chroot.working_directory)
    prefixed_chroot = await Get(Digest, AddPrefix(chroot.digest, chroot_prefix))
    build_system = await Get(BuildSystem, BuildSystemRequest(prefixed_chroot, working_directory))
    setup_py_result = await Get(
        DistBuildResult,
        DistBuildRequest(
            build_system=build_system,
            interpreter_constraints=interpreter_constraints,
            build_wheel=wheel,
            build_sdist=sdist,
            input=prefixed_chroot,
            working_directory=working_directory,
            target_address_spec=exported_target.target.address.spec,
            wheel_config_settings=wheel_config_settings,
            sdist_config_settings=sdist_config_settings,
        ),
    )
    dist_snapshot = await Get(Snapshot, Digest, setup_py_result.output)
    return BuiltPackage(
        setup_py_result.output,
        tuple(BuiltPackageArtifact(path) for path in dist_snapshot.files),
    )


SETUP_BOILERPLATE = """
# DO NOT EDIT THIS FILE -- AUTOGENERATED BY PANTS
# Target: {target_address_spec}

from setuptools import setup

setup(**{setup_kwargs_str})
"""


@rule
async def determine_setup_kwargs(
    exported_target: ExportedTarget, union_membership: UnionMembership
) -> SetupKwargs:
    target = exported_target.target
    setup_kwargs_requests = union_membership.get(SetupKwargsRequest)
    applicable_setup_kwargs_requests = tuple(
        request for request in setup_kwargs_requests if request.is_applicable(target)
    )

    # If no provided implementations, fall back to our default implementation that simply returns
    # what the user explicitly specified in the BUILD file.
    if not applicable_setup_kwargs_requests:
        return SetupKwargs(exported_target.provides.kwargs, address=target.address)

    if len(applicable_setup_kwargs_requests) > 1:
        possible_requests = sorted(plugin.__name__ for plugin in applicable_setup_kwargs_requests)
        raise ValueError(
            f"Multiple of the registered `SetupKwargsRequest`s can work on the target "
            f"{target.address}, and it's ambiguous which to use: {possible_requests}\n\nPlease "
            "activate fewer implementations, or make the classmethod `is_applicable()` more "
            "precise so that only one implementation is applicable for this target."
        )
    setup_kwargs_request = tuple(applicable_setup_kwargs_requests)[0]
    return await Get(SetupKwargs, SetupKwargsRequest, setup_kwargs_request(target))  # type: ignore[abstract]


@dataclass(frozen=True)
class GenerateSetupPyRequest:
    exported_target: ExportedTarget
    sources: DistBuildSources


@dataclass(frozen=True)
class GeneratedSetupPy:
    digest: Digest


@rule
async def generate_chroot(
    request: DistBuildChrootRequest, subsys: SetupPyGeneration
) -> DistBuildChroot:
    generate_setup = request.exported_target.target.get(GenerateSetupField).value
    if generate_setup is None:
        generate_setup = subsys.generate_setup_default

    sources = await Get(DistBuildSources, DistBuildChrootRequest, request)

    if generate_setup:
        generated_setup_py = await Get(
            GeneratedSetupPy, GenerateSetupPyRequest(request.exported_target, sources)
        )
        # We currently generate a setup.py that expects to be in the source root.
        # TODO: It might make sense to generate one in the target's directory, for
        #  consistency with the existing setup.py case.
        working_directory = ""
        chroot_digest = await Get(Digest, MergeDigests((sources.digest, generated_setup_py.digest)))
    else:
        # To get the stripped target directory we need a dummy path under it. Note that this
        # is just a dummy string, required because our source root stripping mechanism assumes
        # that paths are files and starts searching from the parent dir. It doesn't correspond
        # to an actual file on disk, so there are no collision issues.
        # TODO: Add source root stripping functionality for directories.
        stripped = await Get(
            StrippedSourceFileNames,
            SourcesPaths(
                files=(os.path.join(request.exported_target.target.address.spec_path, "dummy.py"),),
                dirs=(),
            ),
        )
        working_directory = os.path.dirname(stripped[0])
        chroot_digest = sources.digest
    return DistBuildChroot(chroot_digest, working_directory)


@rule
async def generate_setup_py(request: GenerateSetupPyRequest) -> GeneratedSetupPy:
    # Generate the setup script.
    finalized_setup_kwargs = await Get(FinalizedSetupKwargs, GenerateSetupPyRequest, request)
    setup_py_content = SETUP_BOILERPLATE.format(
        target_address_spec=request.exported_target.target.address.spec,
        setup_kwargs_str=distutils_repr(finalized_setup_kwargs.kwargs),
    ).encode()
    files_to_create = [
        FileContent("setup.py", setup_py_content),
        FileContent("MANIFEST.in", b"include *.py"),
    ]
    digest = await Get(Digest, CreateDigest(files_to_create))
    return GeneratedSetupPy(digest)


@rule
async def generate_setup_py_kwargs(request: GenerateSetupPyRequest) -> FinalizedSetupKwargs:
    exported_target = request.exported_target
    sources = request.sources
    requirements = await Get(ExportedTargetRequirements, DependencyOwner(exported_target))

    # Generate the kwargs for the setup() call. In addition to using the kwargs that are either
    # explicitly provided or generated via a user's plugin, we add additional kwargs based on the
    # resolved requirements and sources.
    target = exported_target.target
    resolved_setup_kwargs = await Get(SetupKwargs, ExportedTarget, exported_target)
    setup_kwargs = resolved_setup_kwargs.kwargs.copy()

    # NB: We are careful to not overwrite these values, but we also don't expect them to have been
    # set. The user must have have gone out of their way to use a `SetupKwargs` plugin, and to have
    # specified `SetupKwargs(_allow_banned_keys=True)`.
    setup_kwargs.update(
        {
            "packages": (*sources.packages, *(setup_kwargs.get("packages", []))),
            "namespace_packages": (
                *sources.namespace_packages,
                *setup_kwargs.get("namespace_packages", []),
            ),
            "package_data": {**dict(sources.package_data), **setup_kwargs.get("package_data", {})},
            "install_requires": (*requirements, *setup_kwargs.get("install_requires", [])),
        }
    )

    # Resolve entry points from python_distribution(entry_points=...) and from
    # python_distribution(provides=setup_py(entry_points=...)
    resolved_from_entry_points_field, resolved_from_provides_field = await MultiGet(
        Get(
            ResolvedPythonDistributionEntryPoints,
            ResolvePythonDistributionEntryPointsRequest(
                entry_points_field=exported_target.target.get(PythonDistributionEntryPointsField)
            ),
        ),
        Get(
            ResolvedPythonDistributionEntryPoints,
            ResolvePythonDistributionEntryPointsRequest(
                provides_field=exported_target.target.get(PythonProvidesField)
            ),
        ),
    )

    def _format_entry_points(
        resolved: ResolvedPythonDistributionEntryPoints,
    ) -> dict[str, dict[str, str]]:
        return {
            category: {ep_name: ep_val.entry_point.spec for ep_name, ep_val in entry_points.items()}
            for category, entry_points in resolved.val.items()
        }

    # Gather entry points with source description for any error messages when merging them.
    exported_addr = exported_target.target.address
    entry_point_sources = {
        f"{exported_addr}'s field `entry_points`": _format_entry_points(
            resolved_from_entry_points_field
        ),
        f"{exported_addr}'s field `provides=setup_py()`": _format_entry_points(
            resolved_from_provides_field
        ),
    }

    # Merge all collected entry points and add them to the dist's entry points.
    all_entry_points = merge_entry_points(*list(entry_point_sources.items()))
    if all_entry_points:
        setup_kwargs["entry_points"] = {
            category: [f"{name} = {entry_point}" for name, entry_point in entry_points.items()]
            for category, entry_points in all_entry_points.items()
        }

    return FinalizedSetupKwargs(setup_kwargs, address=target.address)


@rule
async def get_sources(
    request: DistBuildChrootRequest, union_membership: UnionMembership
) -> DistBuildSources:
    owned_deps, transitive_targets = await MultiGet(
        Get(OwnedDependencies, DependencyOwner(request.exported_target)),
        Get(
            TransitiveTargets,
            TransitiveTargetsRequest([request.exported_target.target.address]),
        ),
    )
    # files() targets aren't owned by a single exported target - they aren't code, so
    # we allow them to be in multiple dists. This is helpful for, e.g., embedding
    # a standard license file in a dist.
    # TODO: This doesn't actually work, the generated setup.py has no way of referencing
    #  these, since they aren't in a package, so they won't get included in the built dists.
    # There is a separate `license_files()` setup.py kwarg that we should use for this
    # special case (see https://setuptools.pypa.io/en/latest/references/keywords.html).
    file_targets = targets_with_sources_types(
        [FileSourceField], transitive_targets.closure, union_membership
    )
    targets = Targets(itertools.chain((od.target for od in owned_deps), file_targets))

    python_sources_request = PythonSourceFilesRequest(
        targets=targets, include_resources=False, include_files=False
    )
    all_sources_request = PythonSourceFilesRequest(
        targets=targets, include_resources=True, include_files=True
    )
    python_sources, all_sources = await MultiGet(
        Get(StrippedPythonSourceFiles, PythonSourceFilesRequest, python_sources_request),
        Get(StrippedPythonSourceFiles, PythonSourceFilesRequest, all_sources_request),
    )

    python_files = set(python_sources.stripped_source_files.snapshot.files)
    all_files = set(all_sources.stripped_source_files.snapshot.files)
    resource_files = all_files - python_files

    init_py_digest_contents = await Get(
        DigestContents,
        DigestSubset(
            python_sources.stripped_source_files.snapshot.digest, PathGlobs(["**/__init__.py"])
        ),
    )

    packages, namespace_packages, package_data = find_packages(
        python_files=python_files,
        resource_files=resource_files,
        init_py_digest_contents=init_py_digest_contents,
        py2=request.py2,
    )
    return DistBuildSources(
        digest=all_sources.stripped_source_files.snapshot.digest,
        packages=packages,
        namespace_packages=namespace_packages,
        package_data=package_data,
    )


@rule(desc="Compute distribution's 3rd party requirements")
async def get_requirements(
    dep_owner: DependencyOwner,
    union_membership: UnionMembership,
    setup_py_generation: SetupPyGeneration,
) -> ExportedTargetRequirements:
    transitive_targets = await Get(
        TransitiveTargets,
        TransitiveTargetsRequest([dep_owner.exported_target.target.address]),
    )
    ownable_tgts = [
        tgt for tgt in transitive_targets.closure if is_ownable_target(tgt, union_membership)
    ]
    owners = await MultiGet(Get(ExportedTarget, OwnedDependency(tgt)) for tgt in ownable_tgts)
    owned_by_us: set[Target] = set()
    owned_by_others: set[Target] = set()
    for tgt, owner in zip(ownable_tgts, owners):
        (owned_by_us if owner == dep_owner.exported_target else owned_by_others).add(tgt)

    # Get all 3rdparty deps of our owned deps.
    #
    # Note that we need only consider requirements that are direct dependencies of our owned deps:
    # If T depends on R indirectly, then it must be via some direct deps U1, U2, ... For each such U,
    # if U is in the owned deps then we'll pick up R through U. And if U is not in the owned deps
    # then it's owned by an exported target ET, and so R will be in the requirements for ET, and we
    # will require ET.
    direct_deps_tgts = await MultiGet(
        Get(Targets, DependenciesRequest(tgt.get(Dependencies))) for tgt in owned_by_us
    )

    transitive_excludes: FrozenOrderedSet[Target] = FrozenOrderedSet()
    uneval_trans_excl = [
        tgt.get(Dependencies).unevaluated_transitive_excludes for tgt in transitive_targets.closure
    ]
    if uneval_trans_excl:
        nested_trans_excl = await MultiGet(
            Get(Targets, UnparsedAddressInputs, unparsed) for unparsed in uneval_trans_excl
        )
        transitive_excludes = FrozenOrderedSet(
            itertools.chain.from_iterable(excludes for excludes in nested_trans_excl)
        )

    direct_deps_chained = FrozenOrderedSet(itertools.chain.from_iterable(direct_deps_tgts))
    direct_deps_with_excl = direct_deps_chained.difference(transitive_excludes)

    reqs = PexRequirements.create_from_requirement_fields(
        tgt[PythonRequirementsField]
        for tgt in direct_deps_with_excl
        if tgt.has_field(PythonRequirementsField)
    )
    req_strs = list(reqs.req_strings)

    # Add the requirements on any exported targets on which we depend.
    kwargs_for_exported_targets_we_depend_on = await MultiGet(
        Get(SetupKwargs, OwnedDependency(tgt)) for tgt in owned_by_others
    )
    req_strs.extend(
        f"{kwargs.name}{setup_py_generation.first_party_dependency_version(kwargs.version)}"
        for kwargs in set(kwargs_for_exported_targets_we_depend_on)
    )
    return ExportedTargetRequirements(req_strs)


@rule(desc="Find all code to be published in the distribution", level=LogLevel.DEBUG)
async def get_owned_dependencies(
    dependency_owner: DependencyOwner, union_membership: UnionMembership
) -> OwnedDependencies:
    """Find the dependencies of dependency_owner that are owned by it.

    Includes dependency_owner itself.
    """
    transitive_targets = await Get(
        TransitiveTargets,
        TransitiveTargetsRequest([dependency_owner.exported_target.target.address]),
    )
    ownable_targets = [
        tgt for tgt in transitive_targets.closure if is_ownable_target(tgt, union_membership)
    ]
    owners = await MultiGet(Get(ExportedTarget, OwnedDependency(tgt)) for tgt in ownable_targets)
    owned_dependencies = [
        tgt
        for owner, tgt in zip(owners, ownable_targets)
        if owner == dependency_owner.exported_target
    ]
    return OwnedDependencies(OwnedDependency(t) for t in owned_dependencies)


@rule(desc="Get exporting owner for target")
async def get_exporting_owner(owned_dependency: OwnedDependency) -> ExportedTarget:
    """Find the exported target that owns the given target (and therefore exports it).

    The owner of T (i.e., the exported target in whose artifact T's code is published) is:

     1. An exported target that depends on T (or is T itself).
     2. Is T's closest filesystem ancestor among those satisfying 1.

    If there are multiple such exported targets at the same degree of ancestry, the ownership
    is ambiguous and an error is raised. If there is no exported target that depends on T
    and is its ancestor, then there is no owner and an error is raised.
    """
    target = owned_dependency.target
    ancestor_addrs = AscendantAddresses(target.address.spec_path)
    ancestor_tgts = await Get(Targets, AddressSpecs([ancestor_addrs]))
    # Note that addresses sort by (spec_path, target_name), and all these targets are
    # ancestors of the given target, i.e., their spec_paths are all prefixes. So sorting by
    # address will effectively sort by closeness of ancestry to the given target.
    exported_ancestor_tgts = sorted(
        (t for t in ancestor_tgts if t.has_field(PythonProvidesField)),
        key=lambda t: t.address,
        reverse=True,
    )
    exported_ancestor_iter = iter(exported_ancestor_tgts)
    for exported_ancestor in exported_ancestor_iter:
        transitive_targets = await Get(
            TransitiveTargets, TransitiveTargetsRequest([exported_ancestor.address])
        )
        if target in transitive_targets.closure:
            owner = exported_ancestor
            # Find any exported siblings of owner that also depend on target. They have the
            # same spec_path as it, so they must immediately follow it in ancestor_iter.
            sibling_owners = []
            sibling = next(exported_ancestor_iter, None)
            while sibling and sibling.address.spec_path == owner.address.spec_path:
                transitive_targets = await Get(
                    TransitiveTargets, TransitiveTargetsRequest([sibling.address])
                )
                if target in transitive_targets.closure:
                    sibling_owners.append(sibling)
                sibling = next(exported_ancestor_iter, None)
            if sibling_owners:
                all_owners = [exported_ancestor] + sibling_owners
                raise AmbiguousOwnerError(
                    f"Found multiple sibling python_distribution targets that are the closest "
                    f"ancestor dependees of {target.address} and are therefore candidates to "
                    f"own it: {', '.join(o.address.spec for o in all_owners)}. Only a "
                    f"single such owner is allowed, to avoid ambiguity."
                )
            return ExportedTarget(owner)
    raise NoOwnerError(
        f"No python_distribution target found to own {target.address}. Note that "
        f"the owner must be in or above the owned target's directory, and must "
        f"depend on it (directly or indirectly)."
    )


def is_ownable_target(tgt: Target, union_membership: UnionMembership) -> bool:
    return (
        # Note that we check for a PythonProvides field so that a python_distribution
        # target can be owned (by itself). This is so that if there are any 3rdparty
        # requirements directly on the python_distribution target, we apply them to the dist.
        # This isn't particularly useful (3rdparty requirements should be on the python_sources
        # that consumes them)... but users may expect it to work anyway.
        tgt.has_field(PythonProvidesField)
        or tgt.has_field(PythonSourceField)
        or tgt.has_field(ResourceSourceField)
        or tgt.get(SourcesField).can_generate(PythonSourceField, union_membership)
        or tgt.get(SourcesField).can_generate(ResourceSourceField, union_membership)
        # We also check for generating sources so that dependencies on `python_sources(sources=[])`
        # is included. Those won't generate any `python_source` targets, but still can be
        # dependended upon.
        or tgt.has_field(PythonGeneratingSourcesBase)
    )


# Convenient type alias for the pair (package name, data files in the package).
PackageDatum = Tuple[str, Tuple[str, ...]]


def find_packages(
    *,
    python_files: set[str],
    resource_files: set[str],
    init_py_digest_contents: DigestContents,
    py2: bool,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[PackageDatum, ...]]:
    """Analyze the package structure for the given sources.

    Returns a tuple (packages, namespace_packages, package_data), suitable for use as setup()
    kwargs.
    """
    # Find all packages implied by all the sources.
    packages: set[str] = set()
    package_data: DefaultDict[str, list[str]] = defaultdict(list)
    for file_path in itertools.chain(python_files, resource_files):
        # Python 2: An __init__.py file denotes a package.
        # Python 3: Any directory containing python source files is a package.
        if (file_path.endswith(".py") and not py2) or os.path.basename(file_path) == "__init__.py":
            packages.add(os.path.dirname(file_path).replace(os.path.sep, "."))

    # Now find all package_data.
    for resource_file in resource_files:
        # Find the closest enclosing package, if any.  Resources will be loaded relative to that.
        maybe_package: str = os.path.dirname(resource_file).replace(os.path.sep, ".")
        while maybe_package and maybe_package not in packages:
            maybe_package = maybe_package.rpartition(".")[0]
        # If resource is not in a package, ignore it. There's no principled way to load it anyway.
        if maybe_package:
            package_data[maybe_package].append(
                os.path.relpath(resource_file, maybe_package.replace(".", os.path.sep))
            )

    # See which packages are pkg_resources-style namespace packages.
    # Note that implicit PEP 420 namespace packages and pkgutil-style namespace packages
    # should *not* be listed in the setup namespace_packages kwarg. That's for pkg_resources-style
    # namespace packages only. See https://github.com/pypa/sample-namespace-packages/.
    namespace_packages: set[str] = set()
    init_py_by_path: dict[str, bytes] = {ipc.path: ipc.content for ipc in init_py_digest_contents}
    for pkg in packages:
        path = os.path.join(pkg.replace(".", os.path.sep), "__init__.py")
        if path in init_py_by_path and declares_pkg_resources_namespace_package(
            init_py_by_path[path].decode()
        ):
            namespace_packages.add(pkg)

    return (
        tuple(sorted(packages)),
        tuple(sorted(namespace_packages)),
        tuple((pkg, tuple(sorted(files))) for pkg, files in package_data.items()),
    )


def declares_pkg_resources_namespace_package(python_src: str) -> bool:
    """Given .py file contents, determine if it declares a pkg_resources-style namespace package.

    Detects pkg_resources-style namespaces. See here for details:
    https://packaging.python.org/guides/packaging-namespace-packages/.

    Note: Accepted namespace package decls are valid Python syntax in all Python versions,
    so this code can, e.g., detect namespace packages in Python 2 code while running on Python 3.
    """
    import ast

    def is_name(node: ast.AST, name: str) -> bool:
        return isinstance(node, ast.Name) and node.id == name

    def is_call_to(node: ast.AST, func_name: str) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        return (isinstance(func, ast.Attribute) and func.attr == func_name) or is_name(
            func, func_name
        )

    def has_args(call_node: ast.Call, required_arg_ids: tuple[str, ...]) -> bool:
        args = call_node.args
        if len(args) != len(required_arg_ids):
            return False
        actual_arg_ids = tuple(arg.id for arg in args if isinstance(arg, ast.Name))
        return actual_arg_ids == required_arg_ids

    try:
        python_src_ast = ast.parse(python_src)
    except SyntaxError:
        # The namespace package incantations we check for are valid code in all Python versions.
        # So if the code isn't parseable we know it isn't a valid namespace package.
        return False

    # Note that these checks are slightly heuristic. It is possible to construct adversarial code
    # that would defeat them. But the only consequence would be an incorrect namespace_packages list
    # in setup.py, and we're assuming our users aren't trying to shoot themselves in the foot.
    for ast_node in ast.walk(python_src_ast):
        # pkg_resources-style namespace, e.g.,
        #   __import__('pkg_resources').declare_namespace(__name__).
        if is_call_to(ast_node, "declare_namespace") and has_args(
            cast(ast.Call, ast_node), ("__name__",)
        ):
            return True
    return False


def merge_entry_points(
    *all_entry_points_with_descriptions_of_source: tuple[str, dict[str, dict[str, str]]]
) -> dict[str, dict[str, str]]:
    """Merge all entry points, throwing ValueError if there are any conflicts."""
    merged = cast(
        # this gives us a two level deep defaultdict with the inner values being of list type
        DefaultDict[str, DefaultDict[str, List[Tuple[str, str]]]],
        defaultdict(partial(defaultdict, list)),
    )

    for description_of_source, source_entry_points in all_entry_points_with_descriptions_of_source:
        for category, entry_points in source_entry_points.items():
            for ep_name, entry_point in entry_points.items():
                merged[category][ep_name].append((description_of_source, entry_point))

    def _check_entry_point_single_source(
        category: str, name: str, entry_points_with_source: list[tuple[str, str]]
    ) -> tuple[str, str]:
        if len(entry_points_with_source) > 1:
            raise ValueError(
                f"Multiple entry_points registered for {category} {name} in: "
                f"{', '.join(ep_source for ep_source, _ in entry_points_with_source)}"
            )
        _, entry_point = entry_points_with_source[0]
        return name, entry_point

    return {
        category: dict(
            _check_entry_point_single_source(category, name, entry_points_with_source)
            for name, entry_points_with_source in merged_entry_points.items()
        )
        for category, merged_entry_points in merged.items()
    }


def rules():
    return [
        *python_sources_rules(),
        *dists_rules(),
        *collect_rules(),
        UnionRule(PackageFieldSet, PythonDistributionFieldSet),
    ]
