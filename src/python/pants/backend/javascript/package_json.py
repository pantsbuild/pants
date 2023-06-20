# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import json
import logging
import os.path
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterable, Mapping, Optional, Tuple

import yaml
from typing_extensions import Literal

from pants.backend.project_info import dependencies
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import AncestorGlobSpec, RawSpecs
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.goals.package import OutputPathField
from pants.core.target_types import (
    TargetGeneratorSourcesHelperSourcesField,
    TargetGeneratorSourcesHelperTarget,
)
from pants.core.util_rules import stripped_source_files
from pants.engine import fs
from pants.engine.collection import Collection, DeduplicatedCollection
from pants.engine.fs import (
    CreateDigest,
    DigestContents,
    FileContent,
    GlobExpansionConjunction,
    PathGlobs,
)
from pants.engine.internals import graph
from pants.engine.internals.graph import (
    ResolveAllTargetGeneratorRequests,
    ResolvedTargetGeneratorRequests,
)
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    Dependencies,
    DependenciesRequest,
    GeneratedTargets,
    GenerateTargetsRequest,
    InvalidFieldException,
    ScalarField,
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
from pants.util.strutil import help_text, softwrap

_logger = logging.getLogger(__name__)


class NodePackageDependenciesField(Dependencies):
    pass


class PackageJsonSourceField(SingleSourceField):
    default = "package.json"
    required = False


class NodeScript(ABC):
    entry_point: str
    alias: ClassVar[str]


@dataclass(frozen=True)
class NodeBuildScript(NodeScript):
    entry_point: str
    output_directories: tuple[str, ...] = ()
    output_files: tuple[str, ...] = ()
    extra_caches: tuple[str, ...] = ()
    extra_env_vars: tuple[str, ...] = ()

    alias: ClassVar[str] = "node_build_script"

    @classmethod
    def create(
        cls,
        entry_point: str,
        output_directories: Iterable[str] = (),
        output_files: Iterable[str] = (),
        extra_caches: Iterable[str] = (),
        extra_env_vars: Iterable[str] = (),
    ) -> NodeBuildScript:
        """A build script, mapped from the `scripts` section of a package.json file.

        Either the `output_directories` or the `output_files` argument has to be set to capture the
        output artifacts of the build.
        """

        return cls(
            entry_point=entry_point,
            output_directories=tuple(output_directories),
            output_files=tuple(output_files),
            extra_caches=tuple(extra_caches),
            extra_env_vars=tuple(extra_env_vars),
        )


@dataclass(frozen=True)
class NodeTestScript(NodeScript):
    entry_point: str = "test"
    report_args: tuple[str, ...] = ()
    report_output_files: tuple[str, ...] = ()
    report_output_directories: tuple[str, ...] = ()
    coverage_args: tuple[str, ...] = ()
    coverage_output_files: tuple[str, ...] = ()
    coverage_output_directories: tuple[str, ...] = ()
    coverage_entry_point: str | None = None
    extra_caches: tuple[str, ...] = ()

    alias: ClassVar[str] = "node_test_script"

    def __str__(self) -> str:
        return f'{self.alias}(entry_point="{self.entry_point}", ...)'

    @classmethod
    def create(
        cls,
        entry_point: str = "test",
        report_args: Iterable[str] = (),
        report_output_files: Iterable[str] = (),
        report_output_directories: Iterable[str] = (),
        coverage_args: Iterable[str] = (),
        coverage_output_files: Iterable[str] = (),
        coverage_output_directories: Iterable[str] = (),
        coverage_entry_point: str | None = None,
    ) -> NodeTestScript:
        """The test script for this package, mapped from the `scripts` section of a package.json
        file. The pointed to script should accept a variadic number of ([ARG]...) path arguments.

        This entry point is the "test" script, by default.
        """
        return cls(
            entry_point=entry_point,
            report_args=tuple(report_args),
            report_output_files=tuple(report_output_files),
            report_output_directories=tuple(report_output_directories),
            coverage_args=tuple(coverage_args),
            coverage_output_files=tuple(coverage_output_files),
            coverage_output_directories=tuple(coverage_output_directories),
            coverage_entry_point=coverage_entry_point,
        )

    def supports_coverage(self) -> bool:
        return bool(self.coverage_entry_point) or bool(self.coverage_args)

    def coverage_globs(self, working_directory: str) -> PathGlobs:
        return self.coverage_globs_for(
            working_directory,
            self.coverage_output_files,
            self.coverage_output_directories,
            GlobMatchErrorBehavior.ignore,
        )

    @classmethod
    def coverage_globs_for(
        cls,
        working_directory: str,
        files: tuple[str, ...],
        directories: tuple[str, ...],
        error_behaviour: GlobMatchErrorBehavior,
        conjunction: GlobExpansionConjunction = GlobExpansionConjunction.any_match,
        description_of_origin: str | None = None,
    ) -> PathGlobs:
        dir_globs = (os.path.join(directory, "*") for directory in directories)
        return PathGlobs(
            (os.path.join(working_directory, glob) for glob in itertools.chain(files, dir_globs)),
            conjunction=conjunction,
            glob_match_error_behavior=error_behaviour,
            description_of_origin=description_of_origin,
        )


class NodePackageScriptsField(SequenceField[NodeScript]):
    alias = "scripts"
    expected_element_type = NodeScript

    help = help_text(
        """
        Custom node package manager scripts that should be known
        and ran as part of relevant goals.

        Maps the package.json#scripts section to a cacheable pants invocation.
        """
    )
    expected_type_description = (
        '[node_build_script(entry_point="build", output_directories=["./dist/"], ...])'
    )
    default = ()

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[Any]], address: Address
    ) -> Optional[Tuple[NodeScript, ...]]:
        values = super().compute_value(raw_value, address)
        test_scripts = [value for value in values or () if isinstance(value, NodeTestScript)]
        if len(test_scripts) > 1:
            entry_points = ", ".join(str(script) for script in test_scripts)
            raise InvalidFieldException(
                softwrap(
                    f"""
                    You can only specify one `{NodeTestScript.alias}` per `{PackageJsonTarget.alias}`,
                    but the {cls.alias} contains {entry_points}.
                    """
                )
            )
        return values

    def build_scripts(self) -> Iterable[NodeBuildScript]:
        for script in self.value or ():
            if isinstance(script, NodeBuildScript):
                yield script

    def get_test_script(self) -> NodeTestScript:
        for script in self.value or ():
            if isinstance(script, NodeTestScript):
                return script
        return NodeTestScript()


class NodePackageTestScriptField(ScalarField[NodeTestScript]):
    alias = "_node_test_script"
    expected_type = NodeTestScript
    expected_type_description = (
        'node_test_script(entry_point="test", coverage_args="--coverage=true")'
    )
    default = NodeTestScript()
    value: NodeTestScript


class NodePackageVersionField(StringField):
    alias = "version"
    help = help_text(
        """
        Version of the Node package, as specified in the package.json.

        This field should not be overridden; use the value from target generation.
        """
    )
    required = False
    value: str | None


class NodeThirdPartyPackageVersionField(NodePackageVersionField):
    alias = "version"
    help = help_text(
        """
        Version of the Node package, as specified in the package.json.

        This field should not be overridden; use the value from target generation.
        """
    )
    required = True
    value: str


class NodePackageNameField(StringField):
    alias = "package"
    help = help_text(
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
        NodePackageTestScriptField,
    )


class NPMDistributionTarget(Target):
    alias = "npm_distribution"

    help = help_text(
        """
        A publishable npm registry distribution, typically a gzipped tarball
        of the sources and any resources, but omitting the lockfile.

        Generated using the projects package manager `pack` implementation.
        """
    )

    core_fields = (
        *COMMON_TARGET_FIELDS,
        PackageJsonSourceField,
        OutputPathField,
    )


class PackageJsonTarget(TargetGenerator):
    alias = "package_json"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PackageJsonSourceField,
        NodePackageScriptsField,
    )
    help = help_text(
        f"""
        A package.json file describing a nodejs package. (https://nodejs.org/api/packages.html#introduction)

        Generates a `{NodePackageTarget.alias}` target for the package.

        Generates `{NodeThirdPartyPackageTarget.alias}` targets for each specified
        3rd party dependency (e.g. in the package.json#devDependencies field).
        """
    )

    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (NodePackageDependenciesField,)


class NodeBuildScriptEntryPointField(StringField):
    alias = "entry_point"
    required = True
    value: str


class NodeBuildScriptSourcesField(SourcesField):
    alias = "_sources"
    required = False
    default = None

    help = "Marker field for node_build_scripts used in export-codegen."


class NodeBuildScriptOutputFilesField(StringSequenceField):
    alias = "output_files"
    required = False
    default = ()
    help = help_text(
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
    help = help_text(
        """
        Specify full directories (including recursive descendants) of output to capture from the
        build script, relative to the package.json.

        For individual files, use `output_files`. At least one of `output_files` and
        `output_directories` must be specified.

        Relative paths (including `..`) may be used, as long as the path does not ascend further
        than the package.json parent directory.
        """
    )


class NodeBuildScriptExtraEnvVarsField(StringSequenceField):
    alias = "extra_env_vars"
    required = False
    default = ()
    help = help_text(
        """
        Additional environment variables to include in environment when running a build script process.

        Entries are strings in the form `ENV_VAR=value` to use explicitly; or just
        `ENV_VAR` to copy the value of a variable in Pants's own environment.
        """
    )


class NodeBuildScriptExtraCaches(StringSequenceField):
    alias = "extra_caches"
    required = False
    default = ()
    help = help_text(
        f"""
        Specify directories that pants should treat as caches for the build script.

        These directories will not be available as sources, but are available to
        subsequent executions of the build script.

        Example usage:
        # BUILD
        {PackageJsonTarget.alias}(
            scripts={NodeBuildScript.alias}(
                entry_point="build",
                output_directories=["dist"],
                extra_caches=[".parcel-cache"],
            )
        )

        # package.json
        {{
            ...
            "scripts": {{
                "build": "parcel build --dist-dir=dist --cache-dir=.parcel-cache"
                ...
            }}
            ...
        }}
        """
    )


class NodeBuildScriptTarget(Target):
    core_fields = (
        *COMMON_TARGET_FIELDS,
        NodeBuildScriptEntryPointField,
        NodeBuildScriptOutputDirectoriesField,
        NodeBuildScriptOutputFilesField,
        NodeBuildScriptSourcesField,
        NodeBuildScriptExtraCaches,
        NodeBuildScriptExtraEnvVarsField,
        NodePackageDependenciesField,
        OutputPathField,
    )

    alias = "_node_build_script"

    help = help_text(
        """
        A package.json script that is invoked by the configured package manager
        to produce `resource` targets or a packaged artifact.
        """
    )


@dataclass(frozen=True)
class PackageJsonImports:
    """https://nodejs.org/api/packages.html#subpath-imports."""

    imports: FrozenDict[str, tuple[str, ...]]
    root_dir: str

    @classmethod
    def from_package_json(cls, pkg_json: PackageJson) -> PackageJsonImports:
        return cls(
            imports=cls._import_from_package_json(pkg_json),
            root_dir=pkg_json.root_dir,
        )

    @staticmethod
    def _import_from_package_json(
        pkg_json: PackageJson,
    ) -> FrozenDict[str, tuple[str, ...]]:
        imports: Mapping[str, Any] | None = pkg_json.content.get("imports")

        def get_subpaths(value: str | Mapping[str, Any]) -> Iterable[str]:
            if isinstance(value, str):
                yield value
            elif isinstance(value, Mapping):
                for v in value.values():
                    yield from get_subpaths(v)

        if not imports:
            return FrozenDict()
        return FrozenDict(
            {key: tuple(sorted(get_subpaths(subpath))) for key, subpath in imports.items()}
        )


@dataclass(frozen=True)
class PackageJsonEntryPoints:
    """See https://nodejs.org/api/packages.html#package-entry-points and
    https://docs.npmjs.com/cli/v9/configuring-npm/package-json#browser."""

    exports: FrozenDict[str, str]
    bin: FrozenDict[str, str]
    root_dir: str

    @property
    def globs(self) -> Iterable[str]:
        for export in self.exports.values():
            yield export.replace("*", "**/*")
        yield from self.bin.values()

    def globs_from_root(self) -> Iterable[str]:
        for path in self.globs:
            yield os.path.normpath(os.path.join(self.root_dir, path))

    @classmethod
    def from_package_json(cls, pkg_json: PackageJson) -> PackageJsonEntryPoints:
        return cls(
            exports=cls._exports_form_package_json(pkg_json),
            bin=cls._binaries_from_package_json(pkg_json),
            root_dir=pkg_json.root_dir,
        )

    @staticmethod
    def _exports_form_package_json(pkg_json: PackageJson) -> FrozenDict[str, str]:
        content = pkg_json.content
        exports: str | Mapping[str, str] | None = content.get("exports")
        main: str | None = content.get("main")
        browser: str | None = content.get("browser")
        source: str | None = content.get("source")
        if exports:
            if isinstance(exports, str):
                return FrozenDict({".": exports})
            else:
                return FrozenDict(exports)
        elif browser:
            return FrozenDict({".": browser})
        elif main:
            return FrozenDict({".": main})
        elif source:
            return FrozenDict({".": source})
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
    version: str | None
    snapshot: Snapshot
    workspaces: tuple[str, ...] = ()
    module: Literal["commonjs", "module"] | None = None
    dependencies: FrozenDict[str, str] = field(default_factory=FrozenDict)
    package_manager: str | None = None

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


class FirstPartyNodePackageTargets(Targets):
    pass


class AllPackageJson(Collection[PackageJson]):
    pass


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

    def ensure_owner(self) -> Target:
        if self != OwningNodePackage.no_owner():
            assert self.target
            return self.target
        raise ValueError("No owner could be determined.")


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
        (
            tgt
            for tgt in candidate_targets
            if tgt.has_field(PackageJsonSourceField) and tgt.has_field(NodePackageNameField)
        ),
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
async def parse_package_json(content: FileContent) -> PackageJson:
    parsed_package_json = FrozenDict.deep_freeze(json.loads(content.content))
    return PackageJson(
        content=parsed_package_json,
        name=parsed_package_json["name"],
        version=parsed_package_json.get("version"),
        snapshot=await Get(Snapshot, PathGlobs([content.path])),
        module=parsed_package_json.get("type"),
        workspaces=tuple(parsed_package_json.get("workspaces", ())),
        dependencies=FrozenDict.deep_freeze(
            {
                **parsed_package_json.get("dependencies", {}),
                **parsed_package_json.get("devDependencies", {}),
                **parsed_package_json.get("peerDependencies", {}),
            }
        ),
        package_manager=parsed_package_json.get("packageManager"),
    )


@rule
async def read_package_jsons(globs: PathGlobs) -> PackageJsonForGlobs:
    snapshot = await Get(Snapshot, PathGlobs, globs)
    digest_contents = await Get(DigestContents, Digest, snapshot.digest)
    return PackageJsonForGlobs(
        await MultiGet(
            Get(PackageJson, FileContent, digest_content) for digest_content in digest_contents
        )
    )


@rule
async def all_package_json() -> AllPackageJson:
    # Avoids using `AllTargets` due to a circular rule dependency.
    # `generate_node_package_targets` requires knowledge of all
    # first party package names.
    description_of_origin = "The `AllPackageJson` rule"
    requests = await Get(
        ResolvedTargetGeneratorRequests,
        ResolveAllTargetGeneratorRequests(
            description_of_origin=description_of_origin, of_type=PackageJsonTarget
        ),
    )
    globs = [
        glob
        for req in requests.requests
        for glob in req.generator[PackageJsonSourceField]
        .path_globs(UnmatchedBuildFileGlobs.error())
        .globs
    ]
    return AllPackageJson(
        await Get(
            PackageJsonForGlobs,
            PathGlobs(
                globs, GlobMatchErrorBehavior.error, description_of_origin=description_of_origin
            ),
        )
    )


@dataclass(frozen=True)
class PnpmWorkspaceGlobs:
    packages: tuple[str, ...]
    digest: Digest


class PnpmWorkspaces(FrozenDict[PackageJson, PnpmWorkspaceGlobs]):
    def for_root(self, root_dir: str) -> PnpmWorkspaceGlobs | None:
        for pkg, workspaces in self.items():
            if pkg.root_dir == root_dir:
                return workspaces
        return None


@rule
async def pnpm_workspace_files(pkgs: AllPackageJson) -> PnpmWorkspaces:
    snapshot = await Get(
        Snapshot, PathGlobs(os.path.join(pkg.root_dir, "pnpm-workspace.yaml") for pkg in pkgs)
    )
    digest_contents = await Get(DigestContents, Digest, snapshot.digest)

    async def parse_package_globs(content: FileContent) -> PnpmWorkspaceGlobs:
        parsed = yaml.safe_load(content.content) or {"packages": ("**",)}
        return PnpmWorkspaceGlobs(
            tuple(parsed.get("packages", ("**",)) or ("**",)),
            await Get(Digest, CreateDigest([content])),
        )

    globs_per_root = {
        os.path.dirname(digest_content.path): await parse_package_globs(digest_content)
        for digest_content in digest_contents
    }

    return PnpmWorkspaces(
        {pkg: globs_per_root[pkg.root_dir] for pkg in pkgs if pkg.root_dir in globs_per_root}
    )


class AllPackageJsonNames(DeduplicatedCollection[str]):
    """Used to not invalidate all generated node package targets when any package.json contents are
    changed."""


@rule
async def all_package_json_names(all_pkg_jsons: AllPackageJson) -> AllPackageJsonNames:
    return AllPackageJsonNames(pkg.name for pkg in all_pkg_jsons)


@rule
async def package_json_for_source(source_field: PackageJsonSourceField) -> PackageJson:
    [pkg_json] = await Get(
        PackageJsonForGlobs, PathGlobs, source_field.path_globs(UnmatchedBuildFileGlobs.error())
    )
    return pkg_json


@rule
async def script_entrypoints_for_source(
    source_field: PackageJsonSourceField,
) -> PackageJsonEntryPoints:
    return PackageJsonEntryPoints.from_package_json(
        await Get(PackageJson, PackageJsonSourceField, source_field)
    )


@rule
async def subpath_imports_for_source(
    source_field: PackageJsonSourceField,
) -> PackageJsonImports:
    return PackageJsonImports.from_package_json(
        await Get(PackageJson, PackageJsonSourceField, source_field)
    )


class GenerateNodePackageTargets(GenerateTargetsRequest):
    generate_from = PackageJsonTarget


def _script_missing_error(entry_point: str, scripts: Iterable[str], address: Address) -> ValueError:
    return ValueError(
        softwrap(
            f"""
            {entry_point} was not found in package.json#scripts section
            of the `{PackageJsonTarget.alias}` target with address {address}.

            Available scripts are: {', '.join(scripts)}.
            """
        )
    )


@rule
async def generate_node_package_targets(
    request: GenerateNodePackageTargets,
    union_membership: UnionMembership,
    first_party_names: AllPackageJsonNames,
) -> GeneratedTargets:
    file = request.generator[PackageJsonSourceField].file_path
    file_tgt = TargetGeneratorSourcesHelperTarget(
        {TargetGeneratorSourcesHelperSourcesField.alias: os.path.basename(file)},
        request.generator.address.create_generated(file),
        union_membership,
    )

    pkg_json = await Get(
        PackageJson, PackageJsonSourceField, request.generator[PackageJsonSourceField]
    )

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
            NodePackageNameField.alias: pkg_json.name,
            NodePackageVersionField.alias: pkg_json.version,
            NodePackageDependenciesField.alias: [
                file_tgt.address.spec,
                *(tgt.address.spec for tgt in third_party_tgts),
                *request.template.get("dependencies", []),
            ],
            NodePackageTestScriptField.alias: request.generator[
                NodePackageScriptsField
            ].get_test_script(),
        },
        request.generator.address.create_generated(pkg_json.name.replace("@", "__")),
        union_membership,
    )
    scripts = PackageJsonScripts.from_package_json(pkg_json).scripts
    build_script_tgts = []
    for build_script in request.generator[NodePackageScriptsField].build_scripts():
        if build_script.entry_point in scripts:
            build_script_tgts.append(
                NodeBuildScriptTarget(
                    {
                        **request.template,
                        NodeBuildScriptEntryPointField.alias: build_script.entry_point,
                        NodeBuildScriptOutputDirectoriesField.alias: build_script.output_directories,
                        NodeBuildScriptOutputFilesField.alias: build_script.output_files,
                        NodeBuildScriptExtraEnvVarsField.alias: build_script.extra_env_vars,
                        NodeBuildScriptExtraCaches.alias: build_script.extra_caches,
                        NodePackageDependenciesField.alias: [
                            file_tgt.address.spec,
                            *(tgt.address.spec for tgt in third_party_tgts),
                            *request.template.get("dependencies", []),
                            package_target.address.spec,
                        ],
                    },
                    request.generator.address.create_generated(build_script.entry_point),
                    union_membership,
                )
            )
        else:
            raise _script_missing_error(
                build_script.entry_point, scripts, request.generator.address
            )

    coverage_script = package_target[NodePackageTestScriptField].value.coverage_entry_point
    if coverage_script and coverage_script not in scripts:
        raise _script_missing_error(coverage_script, scripts, request.generator.address)

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
    return BuildFileAliases(
        objects={
            NodeBuildScript.alias: NodeBuildScript.create,
            NodeTestScript.alias: NodeTestScript.create,
        }
    )
