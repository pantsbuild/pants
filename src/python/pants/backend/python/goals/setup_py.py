# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import enum
import io
import itertools
import logging
import os
import pickle
from abc import ABC, abstractmethod
from collections import abc, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Set, Tuple, cast

from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems.setuptools import Setuptools
from pants.backend.python.target_types import (
    PexBinarySources,
    PexEntryPointField,
    PythonProvidesField,
    PythonRequirementsField,
    PythonSources,
    ResolvedPexEntryPoint,
    ResolvePexEntryPointRequest,
    SetupPyCommandsField,
)
from pants.backend.python.util_rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexProcess,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFilesRequest,
    StrippedPythonSourceFiles,
)
from pants.backend.python.util_rules.python_sources import rules as python_sources_rules
from pants.base.specs import AddressSpecs, AscendantAddresses
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.target_types import FilesSources, ResourcesSources
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
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    Sources,
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.option.subsystem import Subsystem
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init
from pants.util.strutil import ensure_text

logger = logging.getLogger(__name__)


class InvalidSetupPyArgs(Exception):
    """Indicates invalid arguments to setup.py."""


class TargetNotExported(Exception):
    """Indicates a target that was expected to be exported is not."""


class InvalidEntryPoint(Exception):
    """Indicates that a specified binary entry point was invalid."""


class OwnershipError(Exception):
    """An error related to target ownership calculation."""

    def __init__(self, msg: str):
        super().__init__(
            f"{msg} See https://www.pantsbuild.org/v2.0/docs/python-setup-py-goal for "
            f"how python_library targets are mapped to distributions."
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
class PythonDistributionFieldSet(PackageFieldSet):
    required_fields = (PythonProvidesField,)

    provides: PythonProvidesField


@dataclass(frozen=True)
class SetupPySourcesRequest:
    targets: Targets
    py2: bool  # Whether to use py2 or py3 package semantics.


@dataclass(frozen=True)
class SetupPySources:
    """The sources required by a setup.py command.

    Includes some information derived from analyzing the source, namely the packages, namespace
    packages and resource files in the source.
    """

    digest: Digest
    packages: Tuple[str, ...]
    namespace_packages: Tuple[str, ...]
    package_data: Tuple["PackageDatum", ...]


@dataclass(frozen=True)
class SetupPyChrootRequest:
    """A request to create a chroot containing a setup.py and the sources it operates on."""

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
        if "version" not in kwargs:
            raise ValueError(f"Missing a `version` kwarg in the `provides` field for {address}.")

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
    def kwargs(self) -> Dict[str, Any]:
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
    def explicit_kwargs(self) -> Dict[str, Any]:
        return self.target[PythonProvidesField].value.kwargs


class FinalizedSetupKwargs(SetupKwargs):
    """The final kwargs used for the `setup()` function, after Pants added requirements and sources
    information."""

    def __init__(self, kwargs: Mapping[str, Any], *, address: Address) -> None:
        super().__init__(kwargs, address=address, _allow_banned_keys=True)


@dataclass(frozen=True)
class SetupPyChroot:
    """A chroot containing a generated setup.py and the sources it operates on."""

    digest: Digest
    setup_kwargs: FinalizedSetupKwargs


@dataclass(frozen=True)
class RunSetupPyRequest:
    """A request to run a setup.py command."""

    exported_target: ExportedTarget
    interpreter_constraints: PexInterpreterConstraints
    chroot: SetupPyChroot
    args: Tuple[str, ...]


@dataclass(frozen=True)
class RunSetupPyResult:
    """The result of running a setup.py command."""

    output: Digest  # The state of the chroot after running setup.py.


@enum.unique
class FirstPartyDependencyVersionScheme(enum.Enum):
    EXACT = "exact"  # i.e., ==
    COMPATIBLE = "compatible"  # i.e., ~=
    ANY = "any"  # i.e., no specifier


class SetupPyGeneration(Subsystem):
    """Options to control how setup.py is generated from a `python_distribution` target."""

    options_scope = "setup-py-generation"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
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

    def first_party_dependency_version(self, version: str) -> str:
        """Return the version string (e.g. '~=4.0') for a first-party dependency.

        If the user specified to use "any" version, then this will return an empty string.
        """
        scheme = self.options.first_party_dependency_version_scheme
        if scheme == FirstPartyDependencyVersionScheme.ANY:
            return ""
        specifier = "==" if scheme == FirstPartyDependencyVersionScheme.EXACT else "~="
        return f"{specifier}{version}"


def validate_commands(commands: Tuple[str, ...]):
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
    # TODO: A `publish` rule, that can invoke Twine to do the actual uploading.
    #  See https://github.com/pantsbuild/pants/issues/8935.
    if "upload" in commands or "register" in commands:
        raise InvalidSetupPyArgs("Cannot use the `upload` or `register` setup.py commands")


@rule
async def package_python_dist(
    field_set: PythonDistributionFieldSet,
    python_setup: PythonSetup,
) -> BuiltPackage:
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address]))
    exported_target = ExportedTarget(transitive_targets.roots[0])
    interpreter_constraints = PexInterpreterConstraints.create_from_targets(
        transitive_targets.closure, python_setup
    )
    chroot = await Get(
        SetupPyChroot,
        SetupPyChrootRequest(exported_target, py2=interpreter_constraints.includes_python2()),
    )

    # If commands were provided, run setup.py with them; Otherwise just dump chroots.
    commands = exported_target.target.get(SetupPyCommandsField).value or ()
    if commands:
        validate_commands(commands)
        setup_py_result = await Get(
            RunSetupPyResult,
            RunSetupPyRequest(exported_target, interpreter_constraints, chroot, commands),
        )
        dist_snapshot = await Get(Snapshot, Digest, setup_py_result.output)
        return BuiltPackage(
            setup_py_result.output,
            tuple(BuiltPackageArtifact(path) for path in dist_snapshot.files),
        )
    else:
        dirname = f"{chroot.setup_kwargs.name}-{chroot.setup_kwargs.version}"
        rel_chroot = await Get(Digest, AddPrefix(chroot.digest, dirname))
        return BuiltPackage(rel_chroot, (BuiltPackageArtifact(dirname),))


# We write .py sources into the chroot under this dir.
CHROOT_SOURCE_ROOT = "src"


SETUP_BOILERPLATE = """
# DO NOT EDIT THIS FILE -- AUTOGENERATED BY PANTS
# Target: {target_address_spec}

from setuptools import setup

setup(**{setup_kwargs_str})
"""


@rule
async def run_setup_py(req: RunSetupPyRequest, setuptools: Setuptools) -> RunSetupPyResult:
    """Run a setup.py command on a single exported target."""
    # Note that this pex has no entrypoint. We use it to run our generated setup.py, which
    # in turn imports from and invokes setuptools.
    setuptools_pex = await Get(
        Pex,
        PexRequest(
            output_filename="setuptools.pex",
            internal_only=True,
            requirements=PexRequirements(setuptools.all_requirements),
            interpreter_constraints=(
                req.interpreter_constraints
                if setuptools.options.is_default("interpreter_constraints")
                else PexInterpreterConstraints(setuptools.interpreter_constraints)
            ),
        ),
    )
    input_digest = await Get(Digest, MergeDigests((req.chroot.digest, setuptools_pex.digest)))
    # The setuptools dist dir, created by it under the chroot (not to be confused with
    # pants's own dist dir, at the buildroot).
    dist_dir = "dist/"
    result = await Get(
        ProcessResult,
        PexProcess(
            setuptools_pex,
            argv=("setup.py", *req.args),
            input_digest=input_digest,
            # setuptools commands that create dists write them to the distdir.
            # TODO: Could there be other useful files to capture?
            output_directories=(dist_dir,),
            description=f"Run setuptools for {req.exported_target.target.address}",
            level=LogLevel.DEBUG,
        ),
    )
    output_digest = await Get(Digest, RemovePrefix(result.output_digest, dist_dir))
    return RunSetupPyResult(output_digest)


@rule
async def determine_setup_kwargs(
    exported_target: ExportedTarget, union_membership: UnionMembership
) -> SetupKwargs:
    target = exported_target.target
    setup_kwargs_requests = union_membership.get(SetupKwargsRequest)  # type: ignore[misc]
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
    return await Get(SetupKwargs, SetupKwargsRequest, setup_kwargs_request(target))


@rule
async def generate_chroot(request: SetupPyChrootRequest) -> SetupPyChroot:
    exported_target = request.exported_target
    exported_addr = exported_target.target.address

    owned_deps, transitive_targets = await MultiGet(
        Get(OwnedDependencies, DependencyOwner(exported_target)),
        Get(TransitiveTargets, TransitiveTargetsRequest([exported_target.target.address])),
    )

    # files() targets aren't owned by a single exported target - they aren't code, so
    # we allow them to be in multiple dists. This is helpful for, e.g., embedding
    # a standard license file in a dist.
    files_targets = (tgt for tgt in transitive_targets.closure if tgt.has_field(FilesSources))
    targets = Targets(itertools.chain((od.target for od in owned_deps), files_targets))

    sources, requirements = await MultiGet(
        Get(SetupPySources, SetupPySourcesRequest(targets, py2=request.py2)),
        Get(ExportedTargetRequirements, DependencyOwner(exported_target)),
    )

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
            "package_dir": {"": CHROOT_SOURCE_ROOT, **setup_kwargs.get("package_dir", {})},
            "packages": (*sources.packages, *(setup_kwargs.get("packages", []))),
            "namespace_packages": (
                *sources.namespace_packages,
                *setup_kwargs.get("namespace_packages", []),
            ),
            "package_data": {**dict(sources.package_data), **setup_kwargs.get("package_data", {})},
            "install_requires": (*requirements, *setup_kwargs.get("install_requires", [])),
        }
    )

    # Add any `pex_binary` targets from `setup_py().with_binaries()` to the dist's entry points.
    key_to_binary_spec = exported_target.provides.binaries
    binaries = await Get(
        Targets, UnparsedAddressInputs(key_to_binary_spec.values(), owning_address=target.address)
    )
    entry_point_requests = []
    for binary in binaries:
        if not binary.has_fields([PexEntryPointField, PexBinarySources]):
            raise InvalidEntryPoint(
                "Expected addresses to `pex_binary` targets in `.with_binaries()` for the "
                f"`provides` field for {exported_addr}, but found {binary.address} with target "
                f"type {binary.alias}."
            )
        entry_point = binary[PexEntryPointField].value
        url = "https://python-packaging.readthedocs.io/en/latest/command-line-scripts.html#the-console-scripts-entry-point"
        if not entry_point:
            raise InvalidEntryPoint(
                "Every `pex_binary` used in `.with_binaries()` for the `provides` field for "
                f"{exported_addr} must explicitly set the `entry_point` field, but "
                f"{binary.address} left the field off. Set `entry_point` to either "
                "`path.to.module:func`, or the shorthand `:func` (requires setting the `sources` "
                f"field to exactly one file). See {url}."
            )
        if ":" not in entry_point:
            # We already validated that `entry_point` was set, so we can assume that we're not
            # using the shorthand `:my_func` because they would have already used the `:` char.
            raise InvalidEntryPoint(
                "Every `pex_binary` used in `with_binaries()` for the `provides()` field for "
                f"{exported_addr} must end in the format `:my_func` for the `entry_point` field, "
                f"but {binary.address} set it to {repr(entry_point)}. For example, set "
                f"`entry_point='{entry_point}:main'. You may also use the shorthand "
                f"`entry_point=':func'` if you set the `sources` field to a single file. See {url}."
            )
        entry_point_requests.append(
            ResolvePexEntryPointRequest(binary[PexEntryPointField], binary[PexBinarySources])
        )
    binary_entry_points = await MultiGet(
        Get(ResolvedPexEntryPoint, ResolvePexEntryPointRequest, request)
        for request in entry_point_requests
    )
    for key, binary_entry_point in zip(key_to_binary_spec.keys(), binary_entry_points):
        entry_points = setup_kwargs["entry_points"] = setup_kwargs.get("entry_points", {})
        console_scripts = entry_points["console_scripts"] = entry_points.get("console_scripts", [])
        console_scripts.append(f"{key}={binary_entry_point.val}")

    # Generate the setup script.
    setup_py_content = SETUP_BOILERPLATE.format(
        target_address_spec=target.address.spec,
        setup_kwargs_str=distutils_repr(setup_kwargs),
    ).encode()
    files_to_create = [
        FileContent("setup.py", setup_py_content),
        FileContent("MANIFEST.in", "include *.py".encode()),
    ]
    extra_files_digest, src_digest = await MultiGet(
        Get(Digest, CreateDigest(files_to_create)),
        # Nest the sources under the src/ prefix.
        Get(Digest, AddPrefix(sources.digest, CHROOT_SOURCE_ROOT)),
    )

    chroot_digest = await Get(Digest, MergeDigests((src_digest, extra_files_digest)))
    return SetupPyChroot(chroot_digest, FinalizedSetupKwargs(setup_kwargs, address=target.address))


@rule
async def get_sources(request: SetupPySourcesRequest) -> SetupPySources:
    python_sources_request = PythonSourceFilesRequest(
        targets=request.targets, include_resources=False, include_files=False
    )
    all_sources_request = PythonSourceFilesRequest(
        targets=request.targets, include_resources=True, include_files=True
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
    return SetupPySources(
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
        TransitiveTargets, TransitiveTargetsRequest([dep_owner.exported_target.target.address])
    )

    ownable_tgts = [
        tgt for tgt in transitive_targets.closure if is_ownable_target(tgt, union_membership)
    ]
    owners = await MultiGet(Get(ExportedTarget, OwnedDependency(tgt)) for tgt in ownable_tgts)
    owned_by_us: Set[Target] = set()
    owned_by_others: Set[Target] = set()
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
    reqs = PexRequirements.create_from_requirement_fields(
        tgt[PythonRequirementsField]
        for tgt in itertools.chain.from_iterable(direct_deps_tgts)
        if tgt.has_field(PythonRequirementsField)
    )
    req_strs = list(reqs)

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
        [t for t in ancestor_tgts if t.has_field(PythonProvidesField)],
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
        # This isn't particularly useful (3rdparty requirements should be on the python_library
        # that consumes them)... but users may expect it to work anyway.
        tgt.has_field(PythonProvidesField)
        or tgt.has_field(PythonSources)
        or tgt.has_field(ResourcesSources)
        or tgt.get(Sources).can_generate(PythonSources, union_membership)
    )


# Convenient type alias for the pair (package name, data files in the package).
PackageDatum = Tuple[str, Tuple[str, ...]]


# Distutils does not support unicode strings in setup.py, so we must explicitly convert to binary
# strings as pants uses unicode_literals. A natural and prior technique was to use `pprint.pformat`,
# but that embeds u's in the string itself during conversion. For that reason we roll out own
# literal pretty-printer here.
#
# Note that we must still keep this code, even though Pants only runs with Python 3, because
# the created product may still be run by Python 2.
#
# For more information, see http://bugs.python.org/issue13943.
def distutils_repr(obj):
    """Compute a string repr suitable for use in generated setup.py files."""
    output = io.StringIO()
    linesep = os.linesep

    def _write(data):
        output.write(ensure_text(data))

    def _write_repr(o, indent=False, level=0):
        pad = " " * 4 * level
        if indent:
            _write(pad)
        level += 1

        if isinstance(o, (bytes, str)):
            # The py2 repr of str (unicode) is `u'...'` and we don't want the `u` prefix; likewise,
            # the py3 repr of bytes is `b'...'` and we don't want the `b` prefix so we hand-roll a
            # repr here.
            o_txt = ensure_text(o)
            if linesep in o_txt:
                _write('"""{}"""'.format(o_txt.replace('"""', r"\"\"\"")))
            else:
                _write("'{}'".format(o_txt.replace("'", r"\'")))
        elif isinstance(o, abc.Mapping):
            _write("{" + linesep)
            for k, v in o.items():
                _write_repr(k, indent=True, level=level)
                _write(": ")
                _write_repr(v, indent=False, level=level)
                _write("," + linesep)
            _write(pad + "}")
        elif isinstance(o, abc.Iterable):
            if isinstance(o, abc.MutableSequence):
                open_collection, close_collection = "[]"
            elif isinstance(o, abc.Set):
                open_collection, close_collection = "{}"
            else:
                open_collection, close_collection = "()"

            _write(open_collection + linesep)
            for i in o:
                _write_repr(i, indent=True, level=level)
                _write("," + linesep)
            _write(pad + close_collection)
        else:
            _write(repr(o))  # Numbers and bools.

    _write_repr(obj)
    return output.getvalue()


def find_packages(
    *,
    python_files: Set[str],
    resource_files: Set[str],
    init_py_digest_contents: DigestContents,
    py2: bool,
) -> Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[PackageDatum, ...]]:
    """Analyze the package structure for the given sources.

    Returns a tuple (packages, namespace_packages, package_data), suitable for use as setup()
    kwargs.
    """
    # Find all packages implied by the sources.
    packages: Set[str] = set()
    package_data: Dict[str, List[str]] = defaultdict(list)
    for python_file in python_files:
        # Python 2: An __init__.py file denotes a package.
        # Python 3: Any directory containing python source files is a package.
        if not py2 or os.path.basename(python_file) == "__init__.py":
            packages.add(os.path.dirname(python_file).replace(os.path.sep, "."))

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
    namespace_packages: Set[str] = set()
    init_py_by_path: Dict[str, bytes] = {ipc.path: ipc.content for ipc in init_py_digest_contents}
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

    def has_args(call_node: ast.Call, required_arg_ids: Tuple[str, ...]) -> bool:
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


def rules():
    return [
        *python_sources_rules(),
        *collect_rules(),
        UnionRule(PackageFieldSet, PythonDistributionFieldSet),
    ]
