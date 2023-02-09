# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import os.path
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from typing_extensions import Literal

from pants.backend.project_info import dependencies
from pants.base.specs import AncestorGlobSpec, RawSpecs
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.target_types import (
    TargetGeneratorSourcesHelperSourcesField,
    TargetGeneratorSourcesHelperTarget,
)
from pants.core.util_rules import stripped_source_files
from pants.engine import fs
from pants.engine.collection import Collection
from pants.engine.fs import DigestContents, PathGlobs
from pants.engine.internals import graph
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    Dependencies,
    DependenciesRequest,
    GeneratedTargets,
    GenerateTargetsRequest,
    SequenceField,
    SingleSourceField,
    SourcesField,
    StringField,
    StringSequenceField,
    Target,
    TargetGenerator,
    Targets,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.global_options import UnmatchedBuildFileGlobs
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import softwrap


class NodePackageDependenciesField(Dependencies):
    pass


class PackageJsonSourceField(SingleSourceField):
    default = "package.json"
    required = False


@dataclass(frozen=True)
class NodeBuildScript:
    entry_point: str
    output_directories: tuple[str, ...] = ()
    output_files: tuple[str, ...] = ()

    def __init__(
        self,
        entry_point: str,
        output_directories: Iterable[str] = (),
        output_files: Iterable[str] = (),
    ) -> None:
        object.__setattr__(self, "entry_point", entry_point)
        object.__setattr__(self, "output_directories", tuple(output_directories))
        object.__setattr__(self, "output_files", tuple(output_files))


class NodePackageScriptsField(SequenceField[NodeBuildScript]):
    alias = "scripts"
    expected_element_type = NodeBuildScript

    help = softwrap(
        """
        Custom node package manager scripts that should be known
        and ran as part of relevant goals.

        Maps the package.json#scripts section to a cache:able pants invocation.
        """
    )
    expected_type_description = (
        '[node_build_script(entry_point="build", output_directories=["./dist/"], ...])'
    )
    default = ()


class PackageJsonTarget(TargetGenerator):
    alias = "package_json"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PackageJsonSourceField,
        NodePackageScriptsField,
        NodePackageDependenciesField,
    )
    help = "A package.json file."

    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (PackageJsonSourceField, NodePackageDependenciesField)


class NodePackageVersionField(StringField):
    alias = "version"
    help = softwrap(
        """
        Version of the Node package, as specified in the package.json.

        This field should not be overridden; use the value from target generation.
        """
    )
    required = True
    value: str


class NodeThirdPartyPackageVersionField(NodePackageVersionField):
    alias = "version"
    help = softwrap(
        """
        Version of the Node package, as specified in the package.json.

        This field should not be overridden; use the value from target generation.
        """
    )
    required = True
    value: str


class NodePackageNameField(StringField):
    alias = "package"
    help = softwrap(
        """
        Name of the Node package, as specified in the package.json.

        This field should not be overridden; use the value from target generation.
        """
    )
    required = True
    value: str


class NodeThirdPartyPackageNameField(NodePackageNameField):
    pass


class NodeThirdPartyPackageDependenciesField(Dependencies):
    pass


class NodeThirdPartyPackageTarget(Target):
    alias = "node_third_party_package"

    help = "A third party node package."

    core_fields = (
        *COMMON_TARGET_FIELDS,
        NodeThirdPartyPackageNameField,
        NodeThirdPartyPackageVersionField,
        NodeThirdPartyPackageDependenciesField,
    )


class NodePackageTarget(Target):
    alias = "node_package"

    help = "A first party node package."

    core_fields = (
        *COMMON_TARGET_FIELDS,
        PackageJsonSourceField,
        NodePackageNameField,
        NodePackageVersionField,
        NodePackageDependenciesField,
    )


class NodeBuildScriptEntryPointField(StringField):
    alias = "entry_point"
    required = True


class NodeBuildScriptSourcesField(SourcesField):
    alias = "_sources"
    required = False
    default = None

    help = "Marker field for node_build_scripts used in export-codegen."


class NodeBuildScriptOutputFilesField(StringSequenceField):
    alias = "output_files"
    required = False
    default = ()
    help = softwrap(
        """
        Specify the build script's output files to capture, relative to the package.json.

        For directories, use `output_directories`. At least one of `output_files` and
        `output_directories` must be specified.

        Relative paths (including `..`) may be used, as long as the path does not ascend further
        than the package.json parent directory.
        """
    )


class NodeBuildScriptOutputDirectoriesField(StringSequenceField):
    alias = "output_directories"
    required = False
    default = ()
    help = softwrap(
        """
        Specify full directories (including recursive descendants) of output to capture from the
        build script, relative to the package.json.

        For individual files, use `output_files`. At least one of `output_files` and
        `output_directories` must be specified.

        Relative paths (including `..`) may be used, as long as the path does not ascend further
        than the package.json parent directory.
        """
    )


class NodeBuildScriptTarget(Target):
    core_fields = (
        *COMMON_TARGET_FIELDS,
        NodeBuildScriptEntryPointField,
        NodeBuildScriptOutputDirectoriesField,
        NodeBuildScriptOutputFilesField,
        NodePackageDependenciesField,
    )

    alias = "_node_build_script"

    help = softwrap(
        """
        A package.json script that is invoked by the configured package manager
        to produce `resource` targets.
        """
    )


@dataclass(frozen=True)
class PackageJsonEntryPoints:
    """See https://nodejs.org/api/packages.html#package-entry-points and
    https://docs.npmjs.com/cli/v9/configuring-npm/package-json#browser."""

    exports: FrozenDict[str, str]
    bin: FrozenDict[str, str]

    @property
    def globs(self) -> Iterable[str]:
        for export in self.exports.values():
            yield export.replace("*", "**/*")
        yield from self.bin.values()

    def globs_relative_to(self, pkg_json: PackageJson) -> Iterable[str]:
        for path in self.globs:
            yield os.path.normpath(os.path.join(pkg_json.root_dir, path))

    @classmethod
    def from_package_json(cls, pkg_json: PackageJson) -> PackageJsonEntryPoints:
        return cls(
            exports=cls._exports_form_package_json(pkg_json),
            bin=cls._binaries_from_package_json(pkg_json),
        )

    @staticmethod
    def _exports_form_package_json(pkg_json: PackageJson) -> FrozenDict[str, str]:
        content = pkg_json.content
        exports: str | Mapping[str, str] | None = content.get("exports")
        main: str | None = content.get("main")
        browser: str | None = content.get("browser")
        if exports:
            if isinstance(exports, str):
                return FrozenDict({".": exports})
            else:
                return FrozenDict(exports)
        elif browser:
            return FrozenDict({".": browser})
        elif main:
            return FrozenDict({".": main})
        return FrozenDict()

    @staticmethod
    def _binaries_from_package_json(pkg_json: PackageJson) -> FrozenDict[str, str]:
        binaries: str | Mapping[str, str] | None = pkg_json.content.get("bin")
        if binaries:
            if isinstance(binaries, str):
                return FrozenDict({pkg_json.name: binaries})
            else:
                return FrozenDict(binaries)
        return FrozenDict()


@dataclass(frozen=True)
class PackageJsonScripts:
    scripts: FrozenDict[str, str]

    @classmethod
    def from_package_json(cls, pkg_json: PackageJson) -> PackageJsonScripts:
        return cls(FrozenDict.deep_freeze(pkg_json.content.get("scripts", {})))


@dataclass(frozen=True)
class PackageJson:
    content: FrozenDict[str, Any]
    name: str
    version: str
    snapshot: Snapshot
    workspaces: tuple[PackageJson, ...] = ()
    module: Literal["commonjs", "module"] | None = None
    dependencies: FrozenDict[str, str] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        if self.module not in (None, "commonjs", "module"):
            raise ValueError(
                f'package.json "type" can only be one of "commonjs", "module", but was "{self.module}".'
            )

    @property
    def digest(self) -> Digest:
        return self.snapshot.digest

    @property
    def file(self) -> str:
        return self.snapshot.files[0]

    @property
    def root_dir(self) -> str:
        return os.path.dirname(self.file)

    @property
    def workspace_digests(self) -> Iterable[Digest]:
        yield self.digest
        for workspace in self.workspaces:
            yield from workspace.workspace_digests


class FirstPartyNodePackageTargets(Targets):
    pass


class AllPackageJson(Collection[PackageJson]):
    def root_pkg_json(self, name: str) -> PackageJson:
        """Find the root package.json in a workspace for an in-repo package name.

        If the package is not part of a workspace, or is the root, its own `PackageJson` is
        returned.
        """
        pkgs_by_name = {pkg.name: pkg for pkg in self}
        workspace_pkgs = OrderedSet(pkg for pkg in pkgs_by_name.values() if pkg.workspaces)
        current_root = pkgs_by_name[name]
        while workspace_pkgs:
            pkg = workspace_pkgs.pop()
            if current_root in pkg.workspaces:
                current_root = pkg
        return current_root


class PackageJsonForGlobs(Collection[PackageJson]):
    pass


@rule
async def all_first_party_node_package_targets(targets: AllTargets) -> FirstPartyNodePackageTargets:
    return FirstPartyNodePackageTargets(
        tgt for tgt in targets if tgt.has_fields((PackageJsonSourceField, NodePackageNameField))
    )


@dataclass(frozen=True)
class OwningNodePackageRequest:
    address: Address


@dataclass(frozen=True)
class OwningNodePackage:
    target: Target | None = None
    third_party: tuple[Target, ...] = ()

    @classmethod
    def no_owner(cls) -> OwningNodePackage:
        return cls()


@rule
async def find_owning_package(request: OwningNodePackageRequest) -> OwningNodePackage:
    candidate_targets = await Get(
        Targets,
        RawSpecs(
            ancestor_globs=(AncestorGlobSpec(request.address.spec_path),),
            description_of_origin=f"the `{OwningNodePackage.__name__}` rule",
        ),
    )
    package_json_tgts = sorted(
        (tgt for tgt in candidate_targets if tgt.has_field(PackageJsonSourceField)),
        key=lambda tgt: tgt.address.spec_path,
        reverse=True,
    )
    tgt = package_json_tgts[0] if package_json_tgts else None
    if tgt:
        deps = await Get(Targets, DependenciesRequest(tgt[Dependencies]))
        return OwningNodePackage(
            tgt, tuple(dep for dep in deps if dep.has_field(NodeThirdPartyPackageNameField))
        )
    return OwningNodePackage()


@rule
async def read_package_jsons(globs: PathGlobs) -> PackageJsonForGlobs:
    snapshot = await Get(Snapshot, PathGlobs, globs)
    digest_contents = await Get(DigestContents, Digest, snapshot.digest)

    pkgs = []
    for digest_content in digest_contents:
        parsed_package_json = FrozenDict.deep_freeze(json.loads(digest_content.content))

        self_reference = f"{os.path.curdir}{os.sep}"
        workspaces = await Get(
            PackageJsonForGlobs,
            PathGlobs(
                os.path.join(
                    os.path.dirname(digest_content.path),
                    workspace_dir,
                    PackageJsonSourceField.default,
                )
                for workspace_dir in parsed_package_json.get("workspaces", ())
                if workspace_dir != self_reference
            ),
        )
        pkg = PackageJson(
            content=parsed_package_json,
            name=parsed_package_json["name"],
            version=parsed_package_json["version"],
            snapshot=await Get(Snapshot, PathGlobs([digest_content.path])),
            module=parsed_package_json.get("type"),
            workspaces=tuple(workspaces),
            dependencies=FrozenDict.deep_freeze(
                {
                    **parsed_package_json.get("dependencies", {}),
                    **parsed_package_json.get("devDependencies", {}),
                    **parsed_package_json.get("peerDependencies", {}),
                }
            ),
        )
        pkgs.append(pkg)
    return PackageJsonForGlobs(pkgs)


@rule
async def all_package_json() -> AllPackageJson:
    return AllPackageJson(await Get(PackageJsonForGlobs, PathGlobs(["**/package.json"])))


class GenerateNodePackageTargets(GenerateTargetsRequest):
    generate_from = PackageJsonTarget


@rule
async def generate_node_package_targets(
    request: GenerateNodePackageTargets,
    union_membership: UnionMembership,
    all_pkg_jsons: AllPackageJson,
) -> GeneratedTargets:
    file = request.generator[PackageJsonSourceField].file_path
    file_tgt = TargetGeneratorSourcesHelperTarget(
        {TargetGeneratorSourcesHelperSourcesField.alias: file},
        request.generator.address.create_generated(file),
        union_membership,
    )

    [pkg_json] = await Get(
        PackageJsonForGlobs,
        PathGlobs,
        request.generator[PackageJsonSourceField].path_globs(UnmatchedBuildFileGlobs.error),
    )

    first_party_names = {pkg.name for pkg in all_pkg_jsons}
    third_party_tgts = [
        NodeThirdPartyPackageTarget(
            {
                **{
                    key: value
                    for key, value in request.template.items()
                    if key != PackageJsonSourceField.alias
                },
                NodeThirdPartyPackageNameField.alias: name,
                NodeThirdPartyPackageVersionField.alias: version,
                NodeThirdPartyPackageDependenciesField.alias: [file_tgt.address.spec],
            },
            request.generator.address.create_generated(name.replace("@", "__")),
            union_membership,
        )
        for name, version in pkg_json.dependencies.items()
        if name not in first_party_names
    ]

    package_target = NodePackageTarget(
        {
            **request.template,
            NodePackageNameField.alias: pkg_json.name.replace("@", "__"),
            NodePackageVersionField.alias: pkg_json.version,
            NodePackageDependenciesField.alias: [
                file_tgt.address.spec,
                *(tgt.address.spec for tgt in third_party_tgts),
                *request.template.get("dependencies", []),
            ],
        },
        request.generator.address.create_generated(pkg_json.name),
        union_membership,
    )
    scripts = PackageJsonScripts.from_package_json(pkg_json).scripts
    build_script_tgts = []
    for build_script in request.generator[NodePackageScriptsField].value:
        if build_script.entry_point in scripts:
            build_script_tgts.append(
                NodeBuildScriptTarget(
                    {
                        **request.template,
                        NodeBuildScriptEntryPointField.alias: build_script.entry_point,
                        NodeBuildScriptOutputDirectoriesField.alias: build_script.output_directories,
                        NodeBuildScriptOutputFilesField.alias: build_script.output_files,
                        NodePackageDependenciesField.alias: [
                            file_tgt.address.spec,
                            *(tgt.address.spec for tgt in third_party_tgts),
                            *request.template.get("dependencies", []),
                        ],
                    },
                    request.generator.address.create_generated(build_script.entry_point),
                    union_membership,
                )
            )
        else:
            raise ValueError(
                softwrap(
                    f"""
                    {build_script.entry_point} was not found in package.json#scripts section
                    of the `{PackageJsonTarget.alias}` target with address {request.generator.address}.

                    Available scripts are: {', '.join(scripts)}.
                    """
                )
            )

    return GeneratedTargets(
        request.generator, [package_target, file_tgt, *third_party_tgts, *build_script_tgts]
    )


def target_types() -> Iterable[type[Target]]:
    return [PackageJsonTarget, NodePackageTarget, NodeThirdPartyPackageTarget]


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *graph.rules(),
        *dependencies.rules(),
        *stripped_source_files.rules(),
        *fs.rules(),
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateNodePackageTargets),
    ]


def build_file_aliases() -> BuildFileAliases:
    return BuildFileAliases(objects={"node_build_script": NodeBuildScript})
