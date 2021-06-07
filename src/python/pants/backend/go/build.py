# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Dict, List, Tuple

from pants.backend.go.distribution import GoLangDistribution
from pants.backend.go.target_types import GoBinaryMainAddress, GoBinaryName, GoImportPath, GoSources
from pants.build_graph.address import Address, AddressInput
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import AddPrefix, CreateDigest, Digest, FileContent, MergeDigests, Snapshot
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import (
    FieldSet,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

_logger = logging.getLogger(__name__)


class GoBuildSubsystem(GoalSubsystem):
    name = "go-build"
    help = "Compile Go targets that contain source code (i.e., `go_package`)."


class GoBuildGoal(Goal):
    subsystem_cls = GoBuildSubsystem


@dataclass(frozen=True)
class BuildGoPackageFieldSet(FieldSet):
    required_fields = (GoSources, GoImportPath)
    sources: GoSources
    import_path: GoImportPath


@dataclass(frozen=True)
class BuildGoPackageRequest:
    field_sets: BuildGoPackageFieldSet
    is_main: bool = False


@dataclass(frozen=True)
class BuiltGoPackage:
    import_path: str
    object_digest: Digest


@dataclass(frozen=True)
class GoBinaryFieldSet(PackageFieldSet):
    required_fields = (GoBinaryName, GoBinaryMainAddress)

    binary_name: GoBinaryName
    main_address: GoBinaryMainAddress
    output_path: OutputPathField


@dataclass(frozen=True)
class EnrichedGoLangDistribution:
    stdlib_packages: FrozenDict[str, str]


@dataclass(frozen=True)
class EnrichGoLangDistributionRequest:
    downloaded_goroot: DownloadedExternalTool


@goal_rule
async def run_go_build(targets: Targets) -> GoBuildGoal:
    await MultiGet(
        Get(BuiltGoPackage, BuildGoPackageRequest(BuildGoPackageFieldSet.create(target)))
        for target in targets
        if BuildGoPackageFieldSet.is_applicable(target)
    )
    return GoBuildGoal(exit_code=0)


@rule
async def grok_goroot(
    request: EnrichGoLangDistributionRequest, platform: Platform
) -> EnrichedGoLangDistribution:
    snapshot = await Get(Snapshot, Digest, request.downloaded_goroot.digest)

    packages: Dict[str, str] = {}

    for filename in snapshot.files:
        # TODO: Substitute GOOS and GARCH values into path.
        # TODO: Handle race detection version of stdlib packages. (Append `_race` to directory.
        if not filename.startswith(f"go/pkg/{platform.value}_amd64/"):
            continue
        if not filename.endswith(".a"):
            continue
        p = PurePath(filename).relative_to(f"go/pkg/{platform.value}_amd64")
        key = p.name[0:-2]
        if len(p.parts) > 1:
            key = f"{os.path.normpath(p.parent)}/{key}"
        packages[key] = filename

    if not packages:
        raise ValueError("Did not find any SDK packages in Go SDK")

    return EnrichedGoLangDistribution(FrozenDict(packages))


@rule
async def build_target(
    request: BuildGoPackageRequest, goroot: GoLangDistribution
) -> BuiltGoPackage:
    download_goroot_request = Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        goroot.get_request(Platform.current),
    )

    source_files_request = Get(
        SourceFiles,
        SourceFilesRequest((request.field_sets.sources,)),
    )

    downloaded_goroot, source_files = await MultiGet(download_goroot_request, source_files_request)

    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest([request.field_sets.address])
    )
    transitive_go_deps = [
        dep for dep in transitive_targets.dependencies if BuildGoPackageFieldSet.is_applicable(dep)
    ]
    built_transitive_go_deps_requests = [
        Get(BuiltGoPackage, BuildGoPackageRequest(BuildGoPackageFieldSet.create(tgt)))
        for tgt in transitive_go_deps
    ]
    built_transitive_go_deps = await MultiGet(built_transitive_go_deps_requests)

    import_config_digests: Dict[str, Tuple[str, Digest]] = {}
    for built_transitive_go_dep in built_transitive_go_deps:
        # TODO: Should we normalize the input path or use a random string instead of digest's fingerprint?
        # The concern is different packages with same exact code resulting in same archive bytes.
        fp = built_transitive_go_dep.object_digest.fingerprint
        prefixed_digest = await Get(
            Digest, AddPrefix(built_transitive_go_dep.object_digest, f"__pkgs__/{fp}")
        )
        import_config_digests[built_transitive_go_dep.import_path] = (fp, prefixed_digest)

    merged_packages_digest = await Get(
        Digest, MergeDigests([d for _, d in import_config_digests.values()])
    )

    enriched_goroot = await Get(
        EnrichedGoLangDistribution, EnrichGoLangDistributionRequest(downloaded_goroot)
    )

    import_config: List[str] = ["# import config"]
    for import_path, (fp, _) in import_config_digests.items():
        import_config.append(f"packagefile {import_path}=__pkgs__/{fp}/__pkg__.a")
    for pkg, path in enriched_goroot.stdlib_packages.items():
        import_config.append(f"packagefile {pkg}={os.path.normpath(path)}")
    import_config_content = "\n".join(import_config).encode("utf-8")
    _logger.info(f"import_config_content={import_config_content!r}")
    import_config_digest = await Get(
        Digest, CreateDigest([FileContent(path="./importcfg", content=import_config_content)])
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                source_files.snapshot.digest,
                downloaded_goroot.digest,
                merged_packages_digest,
                import_config_digest,
            )
        ),
    )

    import_path = request.field_sets.import_path.value or ""
    if not import_path:
        raise ValueError("expected import_path to be non-empty")
    if request.is_main:
        import_path = "main"

    argv = [
        "./go/bin/go",
        "tool",
        "compile",
        "-p",
        import_path,
        "-importcfg",
        "./importcfg",
        "-pack",
        "-o",
        "__pkg__.a",
        *source_files.files,
    ]

    process = Process(
        argv=argv,
        env={
            "GOROOT": "./go",
        },
        input_digest=input_digest,
        output_files=["__pkg__.a"],
        description=f"Compile Go package with {pluralize(len(source_files.files), 'file')}.",
        level=LogLevel.DEBUG,
    )

    result = await Get(ProcessResult, Process, process)
    return BuiltGoPackage(import_path=import_path, object_digest=result.output_digest)


@rule
async def package_go_binary(
    field_set: GoBinaryFieldSet,
    goroot: GoLangDistribution,
) -> BuiltPackage:
    main_address = field_set.main_address.value or ""
    main_go_package_address = await Get(
        Address,
        AddressInput,
        AddressInput.parse(main_address, relative_to=field_set.address.spec_path),
    )
    _logger.info(f"main_go_package_address={main_go_package_address}")
    main_go_package_target = await Get(WrappedTarget, Address, main_go_package_address)
    main_go_package_field_set = BuildGoPackageFieldSet.create(main_go_package_target.target)
    built_main_go_package = await Get(
        BuiltGoPackage, BuildGoPackageRequest(field_sets=main_go_package_field_set, is_main=True)
    )

    downloaded_goroot = await Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        goroot.get_request(Platform.current),
    )

    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest([main_go_package_target.target.address])
    )
    transitive_go_deps = [
        dep for dep in transitive_targets.dependencies if BuildGoPackageFieldSet.is_applicable(dep)
    ]
    built_transitive_go_deps_requests = [
        Get(BuiltGoPackage, BuildGoPackageRequest(BuildGoPackageFieldSet.create(tgt)))
        for tgt in transitive_go_deps
    ]
    built_transitive_go_deps = await MultiGet(built_transitive_go_deps_requests)

    import_config_digests: Dict[str, Tuple[str, Digest]] = {}
    for built_transitive_go_dep in built_transitive_go_deps:
        # TODO: Should we normalize the input path or use a random string instead of digest's fingerprint?
        # The concern is different packages with same exact code resulting in same archive bytes.
        fp = built_transitive_go_dep.object_digest.fingerprint
        prefixed_digest = await Get(
            Digest, AddPrefix(built_transitive_go_dep.object_digest, f"__pkgs__/{fp}")
        )
        import_config_digests[built_transitive_go_dep.import_path] = (fp, prefixed_digest)

    merged_packages_digest = await Get(
        Digest, MergeDigests([d for _, d in import_config_digests.values()])
    )

    enriched_goroot = await Get(
        EnrichedGoLangDistribution, EnrichGoLangDistributionRequest(downloaded_goroot)
    )

    import_config: List[str] = ["# import config"]
    for import_path, (fp, _) in import_config_digests.items():
        import_config.append(f"packagefile {import_path}=__pkgs__/{fp}/__pkg__.a")
    for pkg, path in enriched_goroot.stdlib_packages.items():
        import_config.append(f"packagefile {pkg}={os.path.normpath(path)}")
    import_config_content = "\n".join(import_config).encode("utf-8")
    import_config_digest = await Get(
        Digest, CreateDigest([FileContent(path="./importcfg", content=import_config_content)])
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                built_main_go_package.object_digest,
                downloaded_goroot.digest,
                merged_packages_digest,
                import_config_digest,
            )
        ),
    )
    input_snapshot = await Get(Snapshot, Digest, input_digest)
    _logger.info(f"input_snapshot={input_snapshot.files}")

    output_filename_str = field_set.output_path.value
    if output_filename_str:
        output_filename = PurePath(output_filename_str)
    else:
        # TODO: Figure out default for binary_name. Had to do `or "name-not-set"` to satisfy mypy.
        binary_name = field_set.binary_name.value or "name-not-set"
        output_filename = PurePath(field_set.address.spec_path.replace(os.sep, ".")) / binary_name

    _logger.info(f"parent={output_filename.parent}")
    _logger.info(f"name={output_filename.name}")

    argv = [
        "./go/bin/go",
        "tool",
        "link",
        "-importcfg",
        "./importcfg",
        "-o",
        f"./{output_filename.name}",
        "./__pkg__.a",
    ]

    process = Process(
        argv=argv,
        input_digest=input_digest,
        output_files=[f"./{output_filename.name}"],
        description="Link Go binary.",
        level=LogLevel.DEBUG,
    )

    result = await Get(ProcessResult, Process, process)

    renamed_output_digest = await Get(
        Digest, AddPrefix(result.output_digest, output_filename.parent.as_posix())
    )
    ss = await Get(Snapshot, Digest, renamed_output_digest)
    _logger.info(f"ss={ss}")

    artifact = BuiltPackageArtifact(relpath=output_filename.as_posix())
    return BuiltPackage(digest=renamed_output_digest, artifacts=(artifact,))


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, GoBinaryFieldSet),
    ]
