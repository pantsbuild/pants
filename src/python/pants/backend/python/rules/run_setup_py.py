# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Set, Tuple, cast

from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexProcess,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.rules.python_sources import (
    PythonSourceFilesRequest,
    StrippedPythonSourceFiles,
)
from pants.backend.python.rules.python_sources import rules as python_sources_rules
from pants.backend.python.rules.setuptools import Setuptools
from pants.backend.python.rules.util import PackageDatum, distutils_repr, find_packages, is_python2
from pants.backend.python.target_types import (
    PythonEntryPoint,
    PythonInterpreterCompatibility,
    PythonProvidesField,
    PythonRequirementsField,
    PythonSources,
)
from pants.base.specs import (
    AddressLiteralSpec,
    AddressSpecs,
    AscendantAddresses,
    FilesystemLiteralSpec,
)
from pants.core.target_types import FilesSources, ResourcesSources
from pants.core.util_rules.distdir import DistDir
from pants.engine.addresses import Address, Addresses, AddressInput
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
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    Sources,
    Target,
    Targets,
    TargetsWithOrigins,
    TransitiveTargets,
)
from pants.engine.unions import UnionMembership, union
from pants.option.custom_types import shell_str
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


class InvalidSetupPyArgs(Exception):
    """Indicates invalid arguments to setup.py."""


class TargetNotExported(Exception):
    """Indicates a target that was expected to be exported is not."""


class NoOwnerError(Exception):
    """Indicates an exportable target has no owning exported target."""


class AmbiguousOwnerError(Exception):
    """Indicates an exportable target has more than one owning exported target."""


class UnsupportedPythonVersion(Exception):
    """Indicates that the Python version is unsupported for running setup.py commands."""


class InvalidEntryPoint(Exception):
    """Indicates that a specified binary entry point was invalid."""


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
    package_data: Tuple[PackageDatum, ...]


@dataclass(frozen=True)
class SetupPyChrootRequest:
    """A request to create a chroot containing a setup.py and the sources it operates on."""

    exported_target: ExportedTarget
    py2: bool  # Whether to use py2 or py3 package semantics.


@frozen_after_init
@dataclass(unsafe_hash=True)
class SetupKwargs:
    """The keyword arguments to the `setup()` function in the generated `setup.py`."""

    json_str: str

    def __init__(
        self, kwargs: Mapping[str, Any], *, address: Address, _allow_banned_keys: bool = False
    ) -> None:
        super().__init__()
        if "version" not in kwargs:
            raise ValueError(f"Missing a `version` kwarg in the `provides` field for {address}.")

        if not _allow_banned_keys:
            for arg in {"data_files", "package_dir", "package_data", "packages"}:
                if arg in kwargs:
                    raise ValueError(
                        f"{arg} cannot be set in the `provides` field for {address}, but it was "
                        f"set to {kwargs[arg]}. Pants will dynamically set the value for you."
                    )

        # We convert to a `str` so that this type can be hashable. We don't use `FrozenDict`
        # because it would require that all values are immutable, and we may have lists and
        # dictionaries as values. It's too difficult/clunky to convert those all, then to convert
        # them back out of `FrozenDict`.
        self.json_str = json.dumps(kwargs, sort_keys=True)

    @memoized_property
    def kwargs(self) -> Dict[str, Any]:
        return cast(Dict[str, Any], json.loads(self.json_str))

    @property
    def name(self) -> str:
        return cast(str, self.kwargs["name"])

    @property
    def version(self) -> str:
        return cast(str, self.kwargs["version"])


# Note: This only exists as a hook for plugins. To resolve `SetupKwargs`, call
# `await Get(SetupKwargs, ExportedTarget)`, which handles running any plugin implementations vs.
# using the default implementation.
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
    chroot: SetupPyChroot
    args: Tuple[str, ...]


@dataclass(frozen=True)
class RunSetupPyResult:
    """The result of running a setup.py command."""

    output: Digest  # The state of the chroot after running setup.py.


@dataclass(frozen=True)
class SetuptoolsSetup:
    """The setuptools tool."""

    requirements_pex: Pex


class SetupPySubsystem(GoalSubsystem):
    """Run setup.py commands."""

    name = "setup-py"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            passthrough=True,
            help=(
                "Arguments to pass directly to setup.py, e.g. `--setup-py-args='bdist_wheel "
                "--python-tag py36.py37'`. If unspecified, Pants will dump the setup.py chroot."
            ),
        )
        register(
            "--transitive",
            type=bool,
            default=False,
            help=(
                "If specified, will run the setup.py command recursively on all exported targets "
                "that the specified targets depend on, in dependency order."
            ),
        )

    @property
    def args(self) -> Tuple[str, ...]:
        return tuple(self.options.args)

    @property
    def transitive(self) -> bool:
        return cast(bool, self.options.transitive)


class SetupPy(Goal):
    subsystem_cls = SetupPySubsystem


def validate_args(args: Tuple[str, ...]):
    # We rely on the dist dir being the default, so we know where to find the created dists.
    if "--dist-dir" in args or "-d" in args:
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
    if "upload" in args or "register" in args:
        raise InvalidSetupPyArgs("Cannot use the `upload` or `register` setup.py commands")


@goal_rule
async def run_setup_pys(
    targets_with_origins: TargetsWithOrigins,
    setup_py_subsystem: SetupPySubsystem,
    python_setup: PythonSetup,
    distdir: DistDir,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> SetupPy:
    """Run setup.py commands on all exported targets addressed."""
    validate_args(setup_py_subsystem.args)

    # Get all exported targets, ignoring any non-exported targets that happened to be
    # globbed over, but erroring on any explicitly-requested non-exported targets.

    exported_targets: List[ExportedTarget] = []
    explicit_nonexported_targets: List[Target] = []

    for target_with_origin in targets_with_origins:
        tgt = target_with_origin.target
        if tgt.has_field(PythonProvidesField):
            exported_targets.append(ExportedTarget(tgt))
        elif isinstance(target_with_origin.origin, (AddressLiteralSpec, FilesystemLiteralSpec)):
            explicit_nonexported_targets.append(tgt)
    if explicit_nonexported_targets:
        raise TargetNotExported(
            "Cannot run setup.py on these targets, because they have no `provides=` clause: "
            f'{", ".join(so.address.spec for so in explicit_nonexported_targets)}'
        )

    if setup_py_subsystem.transitive:
        # Expand out to all owners of the entire dep closure.
        transitive_targets = await Get(
            TransitiveTargets, Addresses(et.target.address for et in exported_targets)
        )
        owners = await MultiGet(
            Get(ExportedTarget, OwnedDependency(tgt))
            for tgt in transitive_targets.closure
            if is_ownable_target(tgt, union_membership)
        )
        exported_targets = list(FrozenOrderedSet(owners))

    py2 = is_python2(
        python_setup.compatibilities_or_constraints(
            target_with_origin.target.get(PythonInterpreterCompatibility).value
            for target_with_origin in targets_with_origins
        )
    )
    chroots = await MultiGet(
        Get(SetupPyChroot, SetupPyChrootRequest(exported_target, py2))
        for exported_target in exported_targets
    )

    # If args were provided, run setup.py with them; Otherwise just dump chroots.
    if setup_py_subsystem.args:
        setup_py_results = await MultiGet(
            Get(
                RunSetupPyResult,
                RunSetupPyRequest(exported_target, chroot, setup_py_subsystem.args),
            )
            for exported_target, chroot in zip(exported_targets, chroots)
        )

        for exported_target, setup_py_result in zip(exported_targets, setup_py_results):
            addr = exported_target.target.address.spec
            logger.info(f"Writing dist for {addr} under {distdir.relpath}/.")
            workspace.write_digest(setup_py_result.output, path_prefix=str(distdir.relpath))
    else:
        # Just dump the chroot.
        for exported_target, chroot in zip(exported_targets, chroots):
            addr = exported_target.target.address.spec
            setup_py_dir = (
                distdir.relpath / f"{chroot.setup_kwargs.name}-{chroot.setup_kwargs.version}"
            )
            logger.info(f"Writing setup.py chroot for {addr} to {setup_py_dir}")
            workspace.write_digest(chroot.digest, path_prefix=str(setup_py_dir))

    return SetupPy(0)


# We write .py sources into the chroot under this dir.
CHROOT_SOURCE_ROOT = "src"


SETUP_BOILERPLATE = """
# DO NOT EDIT THIS FILE -- AUTOGENERATED BY PANTS
# Target: {target_address_spec}

from setuptools import setup

setup(**{setup_kwargs_str})
"""


@rule
async def run_setup_py(
    req: RunSetupPyRequest, setuptools_setup: SetuptoolsSetup
) -> RunSetupPyResult:
    """Run a setup.py command on a single exported target."""
    input_digest = await Get(
        Digest, MergeDigests((req.chroot.digest, setuptools_setup.requirements_pex.digest))
    )
    # The setuptools dist dir, created by it under the chroot (not to be confused with
    # pants's own dist dir, at the buildroot).
    dist_dir = "dist/"
    result = await Get(
        ProcessResult,
        PexProcess(
            setuptools_setup.requirements_pex,
            argv=("setup.py", *req.args),
            input_digest=input_digest,
            # setuptools commands that create dists write them to the distdir.
            # TODO: Could there be other useful files to capture?
            output_directories=(dist_dir,),
            description=f"Run setuptools for {req.exported_target.target.address}",
        ),
    )
    output_digest = await Get(Digest, RemovePrefix(result.output_digest, dist_dir))
    return RunSetupPyResult(output_digest)


@rule
async def determine_setup_kwargs(
    exported_target: ExportedTarget, union_membership: UnionMembership
) -> SetupKwargs:
    target = exported_target.target
    plugin_requests = union_membership.get(SetupKwargsRequest)  # type: ignore[misc]

    # If no plugins, simply return what the user explicitly specified in a BUILD file.
    if not plugin_requests:
        return SetupKwargs(exported_target.provides.kwargs, address=target.address)

    applicable_plugin_requests = tuple(
        plugin_request for plugin_request in plugin_requests if plugin_request.is_applicable(target)
    )
    if len(applicable_plugin_requests) > 1:
        possible_plugins = sorted(plugin.__name__ for plugin in applicable_plugin_requests)
        raise ValueError(
            f"Multiple of the registered `SetupKwargsRequest`s can work on the target "
            f"{target.address}, and it's ambiguous which to use: {possible_plugins}\n\nPlease "
            "activate fewer implementations, or make the classmethod `is_applicable()` more "
            "precise so that only one plugin implementation is applicable for this target."
        )
    plugin_request = tuple(applicable_plugin_requests)[0]
    return await Get(SetupKwargs, SetupKwargsRequest, plugin_request(target))


@rule
async def generate_chroot(request: SetupPyChrootRequest) -> SetupPyChroot:
    exported_target = request.exported_target

    owned_deps, transitive_targets = await MultiGet(
        Get(OwnedDependencies, DependencyOwner(exported_target)),
        Get(TransitiveTargets, Addresses([exported_target.target.address])),
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
    setup_kwargs.update(
        {
            "package_dir": {"": CHROOT_SOURCE_ROOT},
            "packages": sources.packages,
            "namespace_packages": sources.namespace_packages,
            "package_data": dict(sources.package_data),
            "install_requires": tuple(requirements),
        }
    )
    key_to_binary_spec = exported_target.provides.binaries
    keys = list(key_to_binary_spec.keys())
    addresses = await MultiGet(
        Get(
            Address,
            AddressInput,
            AddressInput.parse(key_to_binary_spec[key], relative_to=target.address.spec_path),
        )
        for key in keys
    )
    binaries = await Get(Targets, Addresses(addresses))
    for key, binary in zip(keys, binaries):
        binary_entry_point = binary.get(PythonEntryPoint).value
        if not binary_entry_point:
            raise InvalidEntryPoint(
                f"The binary {key} exported by {target.address} is not a valid entry point."
            )
        entry_points = setup_kwargs["entry_points"] = setup_kwargs.get("entry_points", {})
        console_scripts = entry_points["console_scripts"] = entry_points.get("console_scripts", [])
        console_scripts.append(f"{key}={binary_entry_point}")

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
    dep_owner: DependencyOwner, union_membership: UnionMembership
) -> ExportedTargetRequirements:
    transitive_targets = await Get(
        TransitiveTargets, Addresses([dep_owner.exported_target.target.address])
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
    #
    # TODO: Note that this logic doesn't account for indirection via dep aggregator targets, of type
    #  `target`. But we don't have those in v2 (yet) anyway. Plus, as we move towards buildgen and/or
    #  stricter build graph hygiene, it makes sense to require that targets directly declare their
    #  true dependencies. Plus, in the specific realm of setup-py, since we must exclude indirect
    #  deps across exported target boundaries, it's not a big stretch to just insist that
    #  requirements must be direct deps.
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
        f"{kwargs.name}=={kwargs.version}"
        for kwargs in set(kwargs_for_exported_targets_we_depend_on)
    )

    return ExportedTargetRequirements(req_strs)


@rule(desc="Find all code to be published in the distribution", level=LogLevel.INFO)
async def get_owned_dependencies(
    dependency_owner: DependencyOwner, union_membership: UnionMembership
) -> OwnedDependencies:
    """Find the dependencies of dependency_owner that are owned by it.

    Includes dependency_owner itself.
    """
    transitive_targets = await Get(
        TransitiveTargets, Addresses([dependency_owner.exported_target.target.address])
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
        transitive_targets = await Get(TransitiveTargets, Addresses([exported_ancestor.address]))
        if target in transitive_targets.closure:
            owner = exported_ancestor
            # Find any exported siblings of owner that also depend on target. They have the
            # same spec_path as it, so they must immediately follow it in ancestor_iter.
            sibling_owners = []
            sibling = next(exported_ancestor_iter, None)
            while sibling and sibling.address.spec_path == owner.address.spec_path:
                transitive_targets = await Get(TransitiveTargets, Addresses([sibling.address]))
                if target in transitive_targets.closure:
                    sibling_owners.append(sibling)
                sibling = next(exported_ancestor_iter, None)
            if sibling_owners:
                raise AmbiguousOwnerError(
                    f"Exporting owners for {target.address} are "
                    f"ambiguous. Found {exported_ancestor.address} and "
                    f"{len(sibling_owners)} others: "
                    f'{", ".join(so.address.spec for so in sibling_owners)}'
                )
            return ExportedTarget(owner)
    raise NoOwnerError(f"No exported target owner found for {target.address}")


@rule(desc="Set up setuptools")
async def setup_setuptools(setuptools: Setuptools) -> SetuptoolsSetup:
    # Note that this pex has no entrypoint. We use it to run our generated setup.py, which
    # in turn imports from and invokes setuptools.
    requirements_pex = await Get(
        Pex,
        PexRequest(
            output_filename="setuptools.pex",
            internal_only=True,
            requirements=PexRequirements(setuptools.all_requirements),
            interpreter_constraints=PexInterpreterConstraints(setuptools.interpreter_constraints),
        ),
    )
    return SetuptoolsSetup(
        requirements_pex=requirements_pex,
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


def rules():
    return [
        *python_sources_rules(),
        *collect_rules(),
    ]
