# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""JVM-generic BSP rules for `buildTarget/dependencyModules` and
`buildTarget/dependencySources`.

These are usable by any JVM language backend (Scala, Java, ...) that registers
a `BSPDependencyModulesRequest` / `BSPDependencySourcesRequest` union member;
the language-specific @rule body is a thin wrapper that delegates to the
helpers here.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass

from pants.base.build_root import BuildRoot
from pants.bsp.spec.targets import DependencyModule
from pants.bsp.util_rules.targets import (
    BSPDependencyModulesRequest,
    BSPDependencyModulesResult,
    BSPDependencySourcesRequest,
    BSPDependencySourcesResult,
)
from pants.engine.addresses import Addresses
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestSubset,
    FileContent,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
)
from pants.engine.internals.graph import resolve_coarsened_targets as coarsened_targets_get
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import (
    add_prefix,
    create_digest,
    digest_subset_to_digest,
    execute_process,
    get_digest_contents,
    merge_digests,
    remove_prefix,
)
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import CoarsenedTarget
from pants.jvm.bsp.spec import MavenDependencyModule, MavenDependencyModuleArtifact
from pants.jvm.compile import (
    ClasspathEntry,
    ClasspathEntryRequest,
    ClasspathEntryRequestFactory,
    get_fallible_classpath_entry,
    required_classfiles,
)
from pants.jvm.resolve.common import ArtifactRequirement, ArtifactRequirements
from pants.jvm.resolve.coordinate import SOURCES_CLASSIFIER, Coordinate
from pants.jvm.resolve.coursier_fetch import (
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
    classpath_dest_filename,
    get_coursier_lockfile_for_resolve,
    prepare_coursier_resolve_info,
    select_coursier_resolve_for_targets,
)
from pants.jvm.resolve.coursier_setup import CoursierFetchProcess
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.target_types import JvmArtifactFieldSet

_logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------------------------
# Third-party modules collection
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThirdpartyModulesRequest:
    addresses: Addresses


@dataclass(frozen=True)
class ThirdpartyModules:
    resolve: CoursierResolveKey
    entries: dict[CoursierLockfileEntry, ClasspathEntry]
    merged_digest: Digest


def get_entry_for_coord(
    lockfile: CoursierResolvedLockfile, coord: Coordinate
) -> CoursierLockfileEntry | None:
    # Match on (group, artifact, classifier) only — Coursier resolves a single
    # version per (group, artifact, classifier) and may coerce upward from the
    # BUILD-declared version when a transitive dep requires a newer version
    # (e.g. BUILD pins commons-codec:1.18.0 but a sibling artifact transitively
    # requires 1.19.0, so the lockfile records 1.19.0). The lockfile is the
    # source of truth for what's on the classpath, so we want to find the
    # entry regardless of the BUILD-declared version.
    for entry in lockfile.entries:
        if (
            entry.coord.group == coord.group
            and entry.coord.artifact == coord.artifact
            and entry.coord.classifier == coord.classifier
        ):
            return entry
    return None


@rule
async def collect_thirdparty_modules(
    request: ThirdpartyModulesRequest,
    classpath_entry_request: ClasspathEntryRequestFactory,
) -> ThirdpartyModules:
    coarsened_targets = await coarsened_targets_get(**implicitly(request.addresses))
    resolve = await select_coursier_resolve_for_targets(coarsened_targets, **implicitly())
    lockfile = await get_coursier_lockfile_for_resolve(resolve)

    applicable_lockfile_entries: dict[CoursierLockfileEntry, CoarsenedTarget] = {}
    for ct in coarsened_targets.coarsened_closure():
        for tgt in ct.members:
            if not JvmArtifactFieldSet.is_applicable(tgt):
                continue

            artifact_requirement = ArtifactRequirement.from_jvm_artifact_target(tgt)
            entry = get_entry_for_coord(lockfile, artifact_requirement.coordinate)
            if not entry:
                _logger.warning(
                    f"No lockfile entry for {artifact_requirement.coordinate} in resolve {resolve.name}."
                )
                continue
            applicable_lockfile_entries[entry] = ct

    fallible_classpath_entries = await concurrently(
        get_fallible_classpath_entry(
            **implicitly(
                {
                    classpath_entry_request.for_targets(
                        component=target, resolve=resolve
                    ): ClasspathEntryRequest
                }
            )
        )
        for target in applicable_lockfile_entries.values()
    )
    classpath_entries = await concurrently(
        required_classfiles(fce) for fce in fallible_classpath_entries
    )

    resolve_digest = await merge_digests(MergeDigests(cpe.digest for cpe in classpath_entries))

    return ThirdpartyModules(
        resolve,
        dict(zip(applicable_lockfile_entries, classpath_entries)),
        resolve_digest,
    )


# -----------------------------------------------------------------------------------------------
# Single-coord intransitive fetch (used for out-of-lockfile artifacts like sources jars)
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchOneCoordRequest:
    """Fetch a single Maven coord intransitively (no lockfile verification).

    Unlike `pants.jvm.resolve.coursier_fetch.coursier_fetch_one_coord`, this
    does NOT require a pre-existing `CoursierLockfileEntry` — the file digest
    is captured from the live coursier fetch rather than verified against a
    known-good one. Designed for one-off artifacts (e.g. source jars) that
    callers fetch outside the resolve's lockfile pipeline, where the lockfile
    does not record file digests for the sources counterpart.
    """

    coord: Coordinate


@dataclass(frozen=True)
class FetchOneCoordResult:
    coord: Coordinate
    # `None` when the artifact isn't published or the fetch fails (e.g. a
    # third-party lib that doesn't ship a `-sources.jar`). Callers should
    # treat a `None` here as "no sources available" rather than an error.
    classpath_entry: ClasspathEntry | None


@rule
async def fetch_one_coord(request: FetchOneCoordRequest) -> FetchOneCoordResult:
    req = ArtifactRequirement(request.coord)
    coursier_resolve_info = await prepare_coursier_resolve_info(ArtifactRequirements([req]))

    coursier_report_file_name = "coursier_report.json"

    process_result = await execute_process(
        **implicitly(
            CoursierFetchProcess(
                args=(
                    coursier_report_file_name,
                    "--intransitive",
                    *coursier_resolve_info.argv,
                ),
                input_digest=coursier_resolve_info.digest,
                output_directories=("classpath",),
                output_files=(coursier_report_file_name,),
                description=f"Fetching with coursier: {request.coord.to_coord_str()}",
            )
        )
    )
    if process_result.exit_code != 0:
        _logger.debug(
            "fetch_one_coord(%s): exit=%d stderr=%r",
            request.coord.to_coord_arg_str(),
            process_result.exit_code,
            process_result.stderr.decode("utf-8", "replace")[:500],
        )
        return FetchOneCoordResult(coord=request.coord, classpath_entry=None)

    report_digest = await digest_subset_to_digest(
        DigestSubset(process_result.output_digest, PathGlobs([coursier_report_file_name]))
    )
    report_contents = await get_digest_contents(report_digest)
    report = json.loads(report_contents[0].content)

    report_deps = report.get("dependencies") or []
    if len(report_deps) == 0:
        return FetchOneCoordResult(coord=request.coord, classpath_entry=None)
    dep = report_deps[0]
    file_path = dep.get("file")
    if not file_path:
        return FetchOneCoordResult(coord=request.coord, classpath_entry=None)

    classpath_dest_name = classpath_dest_filename(dep["coord"], file_path)
    classpath_dest = f"classpath/{classpath_dest_name}"

    resolved_file_digest = await digest_subset_to_digest(
        DigestSubset(process_result.output_digest, PathGlobs([classpath_dest]))
    )
    stripped_digest = await remove_prefix(RemovePrefix(resolved_file_digest, "classpath"))

    return FetchOneCoordResult(
        coord=request.coord,
        classpath_entry=ClasspathEntry(digest=stripped_digest, filenames=(classpath_dest_name,)),
    )


# -----------------------------------------------------------------------------------------------
# Third-party source jars collection
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThirdpartySourceJarsRequest:
    """Companion to `ThirdpartyModulesRequest`, fetches `*-sources.jar` artifacts.

    Sources are fetched out-of-band (not through the resolve lockfile), so
    callers should treat missing entries as "no source jar published" rather
    than an error.
    """

    addresses: Addresses


@dataclass(frozen=True)
class ThirdpartySourceJars:
    resolve: CoursierResolveKey
    # Map: lockfile entry of the binary jar -> sources ClasspathEntry, or None
    # when the artifact has no `-sources.jar` published.
    entries: dict[CoursierLockfileEntry, ClasspathEntry | None]
    merged_digest: Digest


def _sources_jar_basename(coord: Coordinate) -> str:
    """Source-jar filename in a format the IntelliJ-Scala BSP plugin pairs with the
    binary jar.

    `bsp-builtin/.../BspResolverLogic.scala` matches source jars to binaries via
    `libraryPrefix(path)` — full canonical path, with `.jar`, `-sources`/`-src`,
    `-javadoc` stripped — then finds the source jar via
    `sourcesSuffixes.exists(fileName.contains)`. So the source jar must (a)
    contain literal `-sources` in its basename and (b) share the binary's path
    prefix once `-sources.jar` is stripped. We mirror the binary's underscore-
    coord scheme (`classpath_dest_filename` in `pants/jvm/resolve/coursier_fetch.py`)
    and append `-sources`.
    """
    return f"{coord.group}_{coord.artifact}_{coord.version}-sources.jar"


async def _rename_single_file_in_classpath_entry(
    entry: ClasspathEntry, new_basename: str
) -> ClasspathEntry:
    """Return a new ClasspathEntry whose single file is renamed to `new_basename`.

    Used to relabel source jars emitted by `fetch_one_coord` (which names them
    after Coursier's JSON-report coord — `{group}_{artifact}_jar_sources_{version}.jar`)
    to the `-sources.jar` suffix IntelliJ-Scala BSP recognises.
    """
    contents = await get_digest_contents(entry.digest)
    if len(contents) != 1:
        raise AssertionError(
            f"Expected exactly one file in source-jar ClasspathEntry, got {len(contents)}: "
            f"{[fc.path for fc in contents]}"
        )
    (file_content,) = contents
    if file_content.path == new_basename:
        return entry
    renamed_digest = await create_digest(
        CreateDigest([FileContent(new_basename, file_content.content)])
    )
    return ClasspathEntry(digest=renamed_digest, filenames=(new_basename,))


@rule
async def collect_thirdparty_source_jars(
    request: ThirdpartySourceJarsRequest,
) -> ThirdpartySourceJars:
    thirdparty_modules = await collect_thirdparty_modules(
        ThirdpartyModulesRequest(request.addresses), **implicitly()
    )

    # For each binary jar's coord, rewrite the classifier to "sources" and fetch.
    sources_coords = [
        dataclasses.replace(entry.coord, classifier=SOURCES_CLASSIFIER)
        for entry in thirdparty_modules.entries
    ]
    results = await concurrently(
        fetch_one_coord(FetchOneCoordRequest(coord=coord)) for coord in sources_coords
    )

    # Rename each fetched source jar to `{group}_{artifact}_{version}-sources.jar`
    # so IntelliJ-Scala pairs it with the binary jar. Done concurrently.
    rename_targets: list[tuple[CoursierLockfileEntry, ClasspathEntry]] = []
    for lockfile_entry, result in zip(thirdparty_modules.entries, results):
        if result.classpath_entry is not None:
            rename_targets.append((lockfile_entry, result.classpath_entry))

    renamed_entries = await concurrently(
        _rename_single_file_in_classpath_entry(
            cp_entry, _sources_jar_basename(lockfile_entry.coord)
        )
        for lockfile_entry, cp_entry in rename_targets
    )
    renamed_by_lockfile_entry = dict(
        zip((lfe for lfe, _ in rename_targets), renamed_entries)
    )

    entries: dict[CoursierLockfileEntry, ClasspathEntry | None] = {}
    digests: list[Digest] = []
    for lockfile_entry, result in zip(thirdparty_modules.entries, results):
        if result.classpath_entry is None:
            entries[lockfile_entry] = None
            continue
        renamed = renamed_by_lockfile_entry[lockfile_entry]
        entries[lockfile_entry] = renamed
        digests.append(renamed.digest)

    merged = await merge_digests(MergeDigests(digests)) if digests else EMPTY_DIGEST

    return ThirdpartySourceJars(
        resolve=thirdparty_modules.resolve,
        entries=entries,
        merged_digest=merged,
    )


# -----------------------------------------------------------------------------------------------
# BSP rule helpers
# -----------------------------------------------------------------------------------------------


async def _jvm_bsp_dependency_modules(
    request: BSPDependencyModulesRequest,
    build_root: BuildRoot,
) -> BSPDependencyModulesResult:
    """Generic JVM `buildTarget/dependencyModules` body.

    Language backends register a `BSPDependencyModulesRequest` union member
    with their own `field_set_type`, and the language `@rule` body just
    delegates here. Mirrors `_jvm_bsp_compile` / `_jvm_bsp_resources`.
    """
    thirdparty_modules = await collect_thirdparty_modules(
        ThirdpartyModulesRequest(Addresses(fs.address for fs in request.field_sets)),
        **implicitly(),
    )
    resolve = thirdparty_modules.resolve

    resolve_digest = await add_prefix(
        AddPrefix(thirdparty_modules.merged_digest, f"jvm/resolves/{resolve.name}/lib")
    )

    modules = [
        DependencyModule(
            name=f"{entry.coord.group}:{entry.coord.artifact}",
            version=entry.coord.version,
            data=MavenDependencyModule(
                organization=entry.coord.group,
                name=entry.coord.artifact,
                version=entry.coord.version,
                scope=None,
                artifacts=tuple(
                    MavenDependencyModuleArtifact(
                        uri=build_root.pathlib_path.joinpath(
                            f".pants.d/bsp/jvm/resolves/{resolve.name}/lib/{filename}"
                        ).as_uri()
                    )
                    for filename in cp_entry.filenames
                ),
            ),
        )
        for entry, cp_entry in thirdparty_modules.entries.items()
    ]

    return BSPDependencyModulesResult(
        modules=tuple(modules),
        digest=resolve_digest,
    )


async def _jvm_bsp_dependency_sources(
    request: BSPDependencySourcesRequest,
    build_root: BuildRoot,
) -> BSPDependencySourcesResult:
    """Generic JVM `buildTarget/dependencySources` body. See `_jvm_bsp_dependency_modules`."""
    addresses = Addresses(fs.address for fs in request.field_sets)
    source_jars = await collect_thirdparty_source_jars(ThirdpartySourceJarsRequest(addresses))
    resolve = source_jars.resolve
    # Co-locate source jars under `lib/` next to the binary jars emitted by
    # `_jvm_bsp_dependency_modules`. The IntelliJ-Scala BSP plugin pairs source
    # and binary by full canonical path prefix, so they must share a directory.
    sources_prefix = f"jvm/resolves/{resolve.name}/lib"

    digest = await add_prefix(AddPrefix(source_jars.merged_digest, sources_prefix))

    source_uris = tuple(
        build_root.pathlib_path.joinpath(f".pants.d/bsp/{sources_prefix}/{filename}").as_uri()
        for cp_entry in source_jars.entries.values()
        if cp_entry is not None
        for filename in cp_entry.filenames
    )

    return BSPDependencySourcesResult(sources=source_uris, digest=digest)


def rules():
    return collect_rules()
