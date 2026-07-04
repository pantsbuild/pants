# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Building Go standard library packages as `__pkg__.a` archives."""

from __future__ import annotations

import json
from dataclasses import dataclass

from pants.backend.go.go_sources.load_go_binary import LoadedGoBinaryRequest, setup_go_binary
from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.util_rules import stdlib_archives
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    FallibleBuildGoPackageRequest,
)
from pants.backend.go.util_rules.coverage import GoCoverMode
from pants.backend.go.util_rules.embedcfg import EmbedConfig
from pants.backend.go.util_rules.goroot import GoRoot
from pants.backend.go.util_rules.import_analysis import (
    GoStdLibPackage,
    GoStdLibPackagesRequest,
    analyze_go_stdlib_packages,
)
from pants.backend.go.util_rules.pkg_pattern import match_simple_pattern
from pants.backend.go.util_rules.stdlib_archives import (
    GoStdlibArchivesRequest,
    harvest_go_stdlib_archives,
    stdlib_archives_compatible,
)
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import EMPTY_DIGEST, MergeDigests
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import create_digest, execute_process, merge_digests
from pants.engine.process import Process
from pants.engine.rules import collect_rules, implicitly, rule
from pants.util.logging import LogLevel


# Return True if coverage should be enabled for a standard library package.
# See https://github.com/golang/go/blob/1e9ff255a130200fcc4ec5e911d28181fce947d5/src/cmd/go/internal/test/test.go#L839-L853
# for the exceptions.
def _is_coverage_enabled_for_stdlib_package(import_path: str, build_opts: GoBuildOptions) -> bool:
    coverage_config = build_opts.coverage_config
    if not coverage_config:
        return False

    # Silently ignore attempts to run coverage on sync/atomic when using atomic coverage mode.
    # Atomic coverage mode uses sync/atomic, so we can't also do coverage on it.
    if coverage_config.cover_mode == GoCoverMode.ATOMIC and import_path == "sync/atomic":
        return False

    # If using the race detector, silently ignore attempts to run coverage on the runtime packages.
    # It will cause the race detector to be invoked before it has been initialized.
    if build_opts.with_race_detector and (
        import_path == "runtime" or import_path.startswith("runtime/internal")
    ):
        return False

    for pattern in coverage_config.import_path_include_patterns:
        if match_simple_pattern(pattern)(import_path):
            return True

    return False


@dataclass(frozen=True)
class _ResolveStdlibEmbedConfigRequest:
    package: GoStdLibPackage


@dataclass(frozen=True)
class _ResolveStdlibEmbedConfigResult:
    embed_config: EmbedConfig | None
    stderr: str | None


@rule
async def resolve_go_stdlib_embed_config(
    request: _ResolveStdlibEmbedConfigRequest,
) -> _ResolveStdlibEmbedConfigResult:
    patterns_json = json.dumps(
        {
            "EmbedPatterns": request.package.embed_patterns,
            "TestEmbedPatterns": [],
            "XTestEmbedPatterns": [],
        }
    ).encode("utf-8")

    embedder, patterns_json_digest = await concurrently(
        setup_go_binary(
            LoadedGoBinaryRequest("embedcfg", ("main.go",), "./embedder"), **implicitly()
        ),
        create_digest(CreateDigest([FileContent("patterns.json", patterns_json)])),
    )
    input_digest = await merge_digests(MergeDigests((patterns_json_digest, embedder.digest)))
    embed_result = await execute_process(
        Process(
            ("./embedder", "patterns.json", request.package.pkg_source_path),
            input_digest=input_digest,
            description=f"Create embed mapping for {request.package.import_path}",
            level=LogLevel.DEBUG,
        ),
        **implicitly(),
    )
    if embed_result.exit_code != 0:
        return _ResolveStdlibEmbedConfigResult(
            embed_config=None,
            stderr=embed_result.stderr.decode(),
        )
    metadata = json.loads(embed_result.stdout)
    embed_config = EmbedConfig.from_json_dict(metadata.get("EmbedConfig", {}))
    return _ResolveStdlibEmbedConfigResult(
        embed_config=embed_config,
        stderr=None,
    )


@dataclass(frozen=True)
class BuildGoPackageRequestForStdlibRequest:
    import_path: str
    build_opts: GoBuildOptions


@rule
async def setup_build_go_package_target_request_for_stdlib(
    request: BuildGoPackageRequestForStdlibRequest,
    goroot: GoRoot,
    golang: GolangSubsystem,
) -> FallibleBuildGoPackageRequest:
    # Standard library packages on compatible build configurations use the pre-compiled
    # archives from the one-shot `go install std` harvest. Return a "slim" request: no
    # sources, no dependency recursion, and no embed-config resolution (the harvested archive
    # already incorporates embedded files). `build_go_package` short-circuits any stdlib
    # request passing this same gate to the pre-built archive, so the slim request is never
    # compiled from source. Import paths without an archive (e.g. `unsafe`) fall through to
    # the from-source request below, as does everything when the gate is off.
    if stdlib_archives_compatible(request.build_opts, golang):
        archives = await harvest_go_stdlib_archives(
            GoStdlibArchivesRequest(cgo_enabled=request.build_opts.cgo_enabled), goroot
        )
        if request.import_path in archives.import_paths_to_pkg_a_files:
            stdlib_packages = await analyze_go_stdlib_packages(
                GoStdLibPackagesRequest(
                    with_race_detector=False, cgo_enabled=request.build_opts.cgo_enabled
                )
            )
            pkg_info = stdlib_packages[request.import_path]
            return FallibleBuildGoPackageRequest(
                request=BuildGoPackageRequest(
                    import_path=pkg_info.import_path,
                    pkg_name=pkg_info.name,
                    digest=EMPTY_DIGEST,
                    dir_path=pkg_info.pkg_source_path,
                    build_opts=request.build_opts,
                    go_files=(),
                    s_files=(),
                    direct_dependencies=(),
                    import_map=pkg_info.import_map,
                    minimum_go_version=goroot.version,
                    is_stdlib=True,
                ),
                import_path=request.import_path,
            )

    stdlib_packages = await analyze_go_stdlib_packages(
        GoStdLibPackagesRequest(
            with_race_detector=request.build_opts.with_race_detector,
            cgo_enabled=request.build_opts.cgo_enabled,
        )
    )

    pkg_info = stdlib_packages[request.import_path]

    direct_dependency_import_pats = set(pkg_info.imports)
    if pkg_info.cgo_files:
        if request.import_path != "runtime/cgo":
            direct_dependency_import_pats.add("runtime/cgo")
        if pkg_info.import_path not in (
            "runtime/cgo",
            "runtime/race",
            "runtime/msan",
            "runtime/asan",
        ):
            direct_dependency_import_pats.add("syscall")

    direct_dependencies_wrapped = await concurrently(
        # TODO need to move setup_build_go_package_target_request_for_stdlib around above this rule
        setup_build_go_package_target_request_for_stdlib(
            BuildGoPackageRequestForStdlibRequest(
                import_path=dep_import_path,
                build_opts=request.build_opts,
            ),
            **implicitly(),
        )
        for dep_import_path in sorted(direct_dependency_import_pats)
        if dep_import_path not in {"builtin", "C", "unsafe"}
    )

    direct_dependencies: list[BuildGoPackageRequest] = []
    for dep in direct_dependencies_wrapped:
        assert dep.request is not None
        direct_dependencies.append(dep.request)
    direct_dependencies.sort(key=lambda p: p.import_path)

    with_coverage = _is_coverage_enabled_for_stdlib_package(request.import_path, request.build_opts)

    embed_config: EmbedConfig | None = None
    if pkg_info.embed_patterns and pkg_info.embed_files:
        embed_config_result = await resolve_go_stdlib_embed_config(
            _ResolveStdlibEmbedConfigRequest(pkg_info)
        )
        if not embed_config_result.embed_config:
            assert embed_config_result.stderr is not None
            return FallibleBuildGoPackageRequest(
                request=None,
                import_path=request.import_path,
                exit_code=1,
                stderr=embed_config_result.stderr,
            )
        embed_config = embed_config_result.embed_config

    return FallibleBuildGoPackageRequest(
        request=BuildGoPackageRequest(
            import_path=pkg_info.import_path,
            pkg_name=pkg_info.name,
            digest=EMPTY_DIGEST,
            dir_path=pkg_info.pkg_source_path,
            build_opts=request.build_opts,
            go_files=pkg_info.go_files,
            s_files=pkg_info.s_files,
            direct_dependencies=tuple(direct_dependencies),
            import_map=pkg_info.import_map,
            minimum_go_version=goroot.version,
            cgo_files=pkg_info.cgo_files,
            c_files=pkg_info.c_files,
            header_files=pkg_info.h_files,
            cxx_files=pkg_info.cxx_files,
            objc_files=pkg_info.m_files,
            fortran_files=pkg_info.f_files,
            prebuilt_object_files=pkg_info.syso_files,
            cgo_flags=pkg_info.cgo_flags,
            with_coverage=with_coverage,
            is_stdlib=True,
            embed_config=embed_config,
        ),
        import_path=request.import_path,
    )


def rules():
    return (
        *collect_rules(),
        *stdlib_archives.rules(),
    )
