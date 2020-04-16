# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import json
import logging
import os
from dataclasses import dataclass
from typing import List, Set, Tuple, cast

from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.rules.setuptools import Setuptools
from pants.backend.python.rules.targets import (
    PythonEntryPoint,
    PythonInterpreterCompatibility,
    PythonProvidesField,
    PythonRequirementsField,
    PythonSources,
)
from pants.backend.python.rules.util import (
    PackageDatum,
    distutils_repr,
    find_packages,
    is_python2,
    source_root_or_raise,
)
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.base.specs import AddressSpecs, AscendantAddresses, SingleAddress
from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.fs import (
    Digest,
    DirectoriesToMerge,
    DirectoryToMaterialize,
    DirectoryWithPrefixToAdd,
    DirectoryWithPrefixToStrip,
    FileContent,
    FilesContent,
    InputFilesContent,
    PathGlobs,
    Snapshot,
    SnapshotSubset,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import Process, ProcessResult
from pants.engine.objects import Collection
from pants.engine.rules import goal_rule, named_rule, rule, subsystem_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import (
    Dependencies,
    Sources,
    Target,
    Targets,
    TargetsWithOrigins,
    TransitiveTargets,
)
from pants.option.custom_types import shell_str
from pants.python.python_setup import PythonSetup
from pants.rules.core.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.rules.core.distdir import DistDir
from pants.rules.core.strip_source_roots import SourceRootStrippedSources, StripSourcesFieldRequest
from pants.rules.core.targets import ResourcesSources
from pants.source.source_root import SourceRootConfig
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

    target: Target

    @property
    def provides(self) -> PythonArtifact:
        return cast(PythonArtifact, self.target[PythonProvidesField].value)


@dataclass(frozen=True)
class DependencyOwner:
    """An ExportedTarget in its role as an owner of other targets.

    We need this type to prevent rule ambiguities when computing the list of targets owned by an
    ExportedTarget (which involves going from ExportedTarget -> dep -> owner (which is itself an
    ExportedTarget) and checking if owner is this the original ExportedTarget.
    """

    exported_target: ExportedTarget


@dataclass(frozen=True)
class OwnedDependency:
    """A target that is owned by some ExportedTarget.

    Code in this target is published in the owner's artifact.

    The owner of a target T is T's closest filesystem ancestor among the exported targets
    that directly or indirectly depend on it (including T itself).
    """

    target: Target


class OwnedDependencies(Collection[OwnedDependency]):
    pass


@dataclass(frozen=True)
class ExportedTargetRequirements:
    """The requirements of an ExportedTarget.

    Includes:
    - The "normal" 3rdparty requirements of the ExportedTarget and all targets it owns.
    - The published versions of any other ExportedTargets it depends on.
    """

    requirement_strs: Tuple[str, ...]


@dataclass(frozen=True)
class AncestorInitPyFiles:
    """__init__.py files in enclosing packages of the exported code."""

    digests: Tuple[Digest, ...]  # The files stripped of their source roots.


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


@dataclass(frozen=True)
class SetupPyChroot:
    """A chroot containing a generated setup.py and the sources it operates on."""

    digest: Digest
    # The keywords are embedded in the setup.py file in the digest, so these aren't
    # strictly needed here, but they are convenient for testing.
    setup_keywords_json: str


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


class SetupPyOptions(GoalSubsystem):
    """Run setup.py commands."""

    name = "setup-py2"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help="Arguments to pass directly to setup.py, e.g. "
            '`--setup-py2-args="bdist_wheel --python-tag py36.py37"`. If unspecified, we just '
            "dump the setup.py chroot.",
        )
        register(
            "--transitive",
            type=bool,
            default=False,
            help="If specified, will run the setup.py command recursively on all exported targets that "
            "the specified targets depend on, in dependency order. This is useful, e.g., when "
            "the command publishes dists, to ensure that any dependencies of a dist are published "
            "before it.",
        )


class SetupPy(Goal):
    subsystem_cls = SetupPyOptions


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
    options: SetupPyOptions,
    console: Console,
    python_setup: PythonSetup,
    distdir: DistDir,
    workspace: Workspace,
) -> SetupPy:
    """Run setup.py commands on all exported targets addressed."""
    args = tuple(options.values.args)
    validate_args(args)

    # Get all exported targets, ignoring any non-exported targets that happened to be
    # globbed over, but erroring on any explicitly-requested non-exported targets.

    exported_targets: List[ExportedTarget] = []
    explicit_nonexported_targets: List[Target] = []

    for target_with_origin in targets_with_origins:
        tgt = target_with_origin.target
        if _is_exported(tgt):
            exported_targets.append(ExportedTarget(tgt))
        elif isinstance(target_with_origin.origin, SingleAddress):
            explicit_nonexported_targets.append(tgt)
    if explicit_nonexported_targets:
        raise TargetNotExported(
            "Cannot run setup.py on these targets, because they have no `provides=` clause: "
            f'{", ".join(so.address.reference() for so in explicit_nonexported_targets)}'
        )

    if options.values.transitive:
        # Expand out to all owners of the entire dep closure.
        transitive_targets = await Get[TransitiveTargets](
            Addresses(et.target.address for et in exported_targets)
        )
        owners = await MultiGet(
            Get[ExportedTarget](OwnedDependency(tgt))
            for tgt in transitive_targets.closure
            if is_ownable_target(tgt)
        )
        exported_targets = list(FrozenOrderedSet(owners))

    py2 = is_python2(
        (
            target_with_origin.target.get(PythonInterpreterCompatibility).value
            for target_with_origin in targets_with_origins
        ),
        python_setup,
    )
    chroots = await MultiGet(
        Get[SetupPyChroot](SetupPyChrootRequest(exported_target, py2))
        for exported_target in exported_targets
    )

    # If args were provided, run setup.py with them; Otherwise just dump chroots.
    if args:
        setup_py_results = await MultiGet(
            Get[RunSetupPyResult](RunSetupPyRequest(exported_target, chroot, tuple(args)))
            for exported_target, chroot in zip(exported_targets, chroots)
        )

        for exported_target, setup_py_result in zip(exported_targets, setup_py_results):
            addr = exported_target.target.address.reference()
            console.print_stderr(f"Writing dist for {addr} under {distdir.relpath}/.")
            workspace.materialize_directory(
                DirectoryToMaterialize(setup_py_result.output, path_prefix=str(distdir.relpath))
            )
    else:
        # Just dump the chroot.
        for exported_target, chroot in zip(exported_targets, chroots):
            addr = exported_target.target.address.reference()
            provides = exported_target.provides
            setup_py_dir = distdir.relpath / f"{provides.name}-{provides.version}"
            console.print_stderr(f"Writing setup.py chroot for {addr} to {setup_py_dir}")
            workspace.materialize_directory(
                DirectoryToMaterialize(chroot.digest, path_prefix=str(setup_py_dir))
            )

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
    req: RunSetupPyRequest,
    setuptools_setup: SetuptoolsSetup,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> RunSetupPyResult:
    """Run a setup.py command on a single exported target."""
    merged_input_files = await Get[Digest](
        DirectoriesToMerge(
            directories=(req.chroot.digest, setuptools_setup.requirements_pex.directory_digest)
        )
    )
    # The setuptools dist dir, created by it under the chroot (not to be confused with
    # pants's own dist dir, at the buildroot).
    dist_dir = "dist/"
    request = setuptools_setup.requirements_pex.create_execute_request(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path="./setuptools.pex",
        pex_args=("setup.py", *req.args),
        input_files=merged_input_files,
        # setuptools commands that create dists write them to the distdir.
        # TODO: Could there be other useful files to capture?
        output_directories=(dist_dir,),
        description=f"Run setuptools for {req.exported_target.target.address.reference()}",
    )
    result = await Get[ProcessResult](Process, request)
    output_digest = await Get[Digest](
        DirectoryWithPrefixToStrip(result.output_directory_digest, dist_dir)
    )
    return RunSetupPyResult(output_digest)


@rule
async def generate_chroot(request: SetupPyChrootRequest) -> SetupPyChroot:
    exported_target = request.exported_target

    owned_deps = await Get[OwnedDependencies](DependencyOwner(exported_target))
    targets = Targets(od.target for od in owned_deps)
    sources = await Get[SetupPySources](SetupPySourcesRequest(targets, py2=request.py2))
    requirements = await Get[ExportedTargetRequirements](DependencyOwner(exported_target))

    # Nest the sources under the src/ prefix.
    src_digest = await Get[Digest](DirectoryWithPrefixToAdd(sources.digest, CHROOT_SOURCE_ROOT))

    target = exported_target.target
    provides = exported_target.provides

    # Generate the kwargs to the setup() call.
    setup_kwargs = provides.setup_py_keywords.copy()
    setup_kwargs.update(
        {
            "package_dir": {"": CHROOT_SOURCE_ROOT},
            "packages": sources.packages,
            "namespace_packages": sources.namespace_packages,
            "package_data": dict(sources.package_data),
            "install_requires": requirements.requirement_strs,
        }
    )
    key_to_binary_spec = provides.binaries
    keys = list(key_to_binary_spec.keys())
    binaries = await Get[Targets](
        Addresses(
            Address.parse(key_to_binary_spec[key], relative_to=target.address.spec_path)
            for key in keys
        )
    )
    for key, binary in zip(keys, binaries):
        binary_entry_point = binary.get(PythonEntryPoint).value
        if not binary_entry_point:
            raise InvalidEntryPoint(
                f"The binary {key} exported by {target.address.reference()} is not a valid entry "
                f"point."
            )
        entry_points = setup_kwargs["entry_points"] = setup_kwargs.get("entry_points", {})
        console_scripts = entry_points["console_scripts"] = entry_points.get("console_scripts", [])
        console_scripts.append(f"{key}={binary_entry_point}")

    # Generate the setup script.
    setup_py_content = SETUP_BOILERPLATE.format(
        target_address_spec=target.address.reference(),
        setup_kwargs_str=distutils_repr(setup_kwargs),
    ).encode()
    extra_files_digest = await Get[Digest](
        InputFilesContent(
            [
                FileContent("setup.py", setup_py_content),
                FileContent(
                    "MANIFEST.in", "include *.py".encode()
                ),  # Make sure setup.py is included.
            ]
        )
    )

    chroot_digest = await Get[Digest](DirectoriesToMerge((src_digest, extra_files_digest)))
    return SetupPyChroot(chroot_digest, json.dumps(setup_kwargs, sort_keys=True))


@rule
async def get_sources(
    request: SetupPySourcesRequest, source_root_config: SourceRootConfig
) -> SetupPySources:
    targets = request.targets
    stripped_srcs_list = await MultiGet(
        Get[SourceRootStrippedSources](StripSourcesFieldRequest(target.get(Sources)))
        for target in targets
    )

    # Create a chroot with all the sources, and any ancestor __init__.py files that might be needed
    # for imports to work.  Note that if a repo has multiple exported targets under a single ancestor
    # package, then that package must be a namespace package, which in Python 3 means it must not
    # have an __init__.py. We don't validate this here, because it would require inspecting *all*
    # targets, whether or not they are in the target set for this run - basically the entire repo.
    # So it's the repo owners' responsibility to ensure __init__.py hygiene.
    stripped_srcs_digests = [
        stripped_sources.snapshot.directory_digest for stripped_sources in stripped_srcs_list
    ]
    ancestor_init_pys = await Get[AncestorInitPyFiles](Targets, targets)
    sources_digest = await Get[Digest](
        DirectoriesToMerge(directories=tuple([*stripped_srcs_digests, *ancestor_init_pys.digests]))
    )
    init_pys_snapshot = await Get[Snapshot](
        SnapshotSubset(sources_digest, PathGlobs(["**/__init__.py"]))
    )
    init_py_contents = await Get[FilesContent](Digest, init_pys_snapshot.directory_digest)

    packages, namespace_packages, package_data = find_packages(
        source_roots=source_root_config.get_source_roots(),
        tgts_and_stripped_srcs=list(zip(targets, stripped_srcs_list)),
        init_py_contents=init_py_contents,
        py2=request.py2,
    )
    return SetupPySources(
        digest=sources_digest,
        packages=packages,
        namespace_packages=namespace_packages,
        package_data=package_data,
    )


@rule
async def get_ancestor_init_py(
    targets: Targets, source_root_config: SourceRootConfig
) -> AncestorInitPyFiles:
    """Find any ancestor __init__.py files for the given targets.

    Includes sibling __init__.py files. Returns the files stripped of their source roots.
    """
    source_roots = source_root_config.get_source_roots()
    sources = await Get[SourceFiles](
        AllSourceFilesRequest(tgt[PythonSources] for tgt in targets if tgt.has_field(PythonSources))
    )
    # Find the ancestors of all dirs containing .py files, including those dirs themselves.
    source_dir_ancestors: Set[Tuple[str, str]] = set()  # Items are (src_root, path incl. src_root).
    for fp in sources.snapshot.files:
        source_dir_ancestor = os.path.dirname(fp)
        source_root = source_root_or_raise(source_roots, fp)
        # Do not allow the repository root to leak (i.e., '.' should not be a package in setup.py).
        while source_dir_ancestor != source_root:
            source_dir_ancestors.add((source_root, source_dir_ancestor))
            source_dir_ancestor = os.path.dirname(source_dir_ancestor)

    source_dir_ancestors_list = list(source_dir_ancestors)  # To force a consistent order.

    # Note that we must MultiGet single globs instead of a a single Get for all the globs, because
    # we match each result to its originating glob (see use of zip below).
    ancestor_init_py_snapshots = await MultiGet[Snapshot](
        Get[Snapshot](PathGlobs, PathGlobs([os.path.join(source_dir_ancestor[1], "__init__.py")]))
        for source_dir_ancestor in source_dir_ancestors_list
    )

    source_root_stripped_ancestor_init_pys = await MultiGet[Digest](
        Get[Digest](
            DirectoryWithPrefixToStrip(
                directory_digest=snapshot.directory_digest, prefix=source_dir_ancestor[0]
            )
        )
        for snapshot, source_dir_ancestor in zip(
            ancestor_init_py_snapshots, source_dir_ancestors_list
        )
    )

    return AncestorInitPyFiles(source_root_stripped_ancestor_init_pys)


def _is_exported(target: Target) -> bool:
    return target.has_field(PythonProvidesField) and target[PythonProvidesField].value is not None


@named_rule(desc="Compute distribution's 3rd party requirements")
async def get_requirements(dep_owner: DependencyOwner) -> ExportedTargetRequirements:
    transitive_targets = await Get[TransitiveTargets](
        Addresses([dep_owner.exported_target.target.address])
    )

    ownable_tgts = [tgt for tgt in transitive_targets.closure if is_ownable_target(tgt)]
    owners = await MultiGet(Get[ExportedTarget](OwnedDependency(tgt)) for tgt in ownable_tgts)
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
    direct_deps_addrs = sorted(
        set(itertools.chain.from_iterable(tgt.get(Dependencies).value or () for tgt in owned_by_us))
    )
    direct_deps_tgts = await Get[Targets](Addresses(direct_deps_addrs))
    reqs = PexRequirements.create_from_requirement_fields(
        tgt[PythonRequirementsField]
        for tgt in direct_deps_tgts
        if tgt.has_field(PythonRequirementsField)
    )
    req_strs = list(reqs.requirements)

    # Add the requirements on any exported targets on which we depend.
    exported_targets_we_depend_on = await MultiGet(
        Get[ExportedTarget](OwnedDependency(tgt)) for tgt in owned_by_others
    )
    req_strs.extend(sorted(et.provides.requirement for et in set(exported_targets_we_depend_on)))

    return ExportedTargetRequirements(tuple(req_strs))


@named_rule(desc="Find all code to be published in the distribution")
async def get_owned_dependencies(dependency_owner: DependencyOwner) -> OwnedDependencies:
    """Find the dependencies of dependency_owner that are owned by it.

    Includes dependency_owner itself.
    """
    transitive_targets = await Get[TransitiveTargets](
        Addresses([dependency_owner.exported_target.target.address])
    )
    ownable_targets = [tgt for tgt in transitive_targets.closure if is_ownable_target(tgt)]
    owners = await MultiGet(Get[ExportedTarget](OwnedDependency(tgt)) for tgt in ownable_targets)
    owned_dependencies = [
        tgt
        for owner, tgt in zip(owners, ownable_targets)
        if owner == dependency_owner.exported_target
    ]
    return OwnedDependencies(OwnedDependency(t) for t in owned_dependencies)


@named_rule(desc="Get exporting owner for target")
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
    ancestor_tgts = await Get[Targets](AddressSpecs((ancestor_addrs,)))
    # Note that addresses sort by (spec_path, target_name), and all these targets are
    # ancestors of the given target, i.e., their spec_paths are all prefixes. So sorting by
    # address will effectively sort by closeness of ancestry to the given target.
    exported_ancestor_tgts = sorted(
        [t for t in ancestor_tgts if _is_exported(t)], key=lambda t: t.address, reverse=True,
    )
    exported_ancestor_iter = iter(exported_ancestor_tgts)
    for exported_ancestor in exported_ancestor_iter:
        transitive_targets = await Get[TransitiveTargets](Addresses([exported_ancestor.address]))
        if target in transitive_targets.closure:
            owner = exported_ancestor
            # Find any exported siblings of owner that also depend on target. They have the
            # same spec_path as it, so they must immediately follow it in ancestor_iter.
            sibling_owners = []
            sibling = next(exported_ancestor_iter, None)
            while sibling and sibling.address.spec_path == owner.address.spec_path:
                transitive_targets = await Get[TransitiveTargets](Addresses([sibling.address]))
                if target in transitive_targets.closure:
                    sibling_owners.append(sibling)
                sibling = next(exported_ancestor_iter, None)
            if sibling_owners:
                raise AmbiguousOwnerError(
                    f"Exporting owners for {target.address.reference()} are "
                    f"ambiguous. Found {exported_ancestor.address.reference()} and "
                    f"{len(sibling_owners)} others: "
                    f'{", ".join(so.address.reference() for so in sibling_owners)}'
                )
            return ExportedTarget(owner)
    raise NoOwnerError(f"No exported target owner found for {target.address.reference()}")


@named_rule(desc="Set up setuptools")
async def setup_setuptools(setuptools: Setuptools) -> SetuptoolsSetup:
    # Note that this pex has no entrypoint. We use it to run our generated setup.py, which
    # in turn imports from and invokes setuptools.
    requirements_pex = await Get[Pex](
        PexRequest(
            output_filename="setuptools.pex",
            requirements=PexRequirements(setuptools.get_requirement_specs()),
            interpreter_constraints=PexInterpreterConstraints(
                setuptools.default_interpreter_constraints
            ),
        )
    )
    return SetuptoolsSetup(requirements_pex=requirements_pex,)


def is_ownable_target(tgt: Target) -> bool:
    return tgt.has_field(PythonSources) or tgt.has_field(ResourcesSources)


def rules():
    return [
        run_setup_pys,
        run_setup_py,
        generate_chroot,
        get_sources,
        get_requirements,
        get_ancestor_init_py,
        get_owned_dependencies,
        get_exporting_owner,
        setup_setuptools,
        subsystem_rule(Setuptools),
    ]
