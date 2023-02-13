# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.build_pkg import BuildGoPackageRequest, BuiltGoPackage
from pants.backend.go.util_rules.goroot import GoRoot
from pants.backend.go.util_rules.import_analysis import GoStdLibPackages, GoStdLibPackagesRequest
from pants.backend.go.util_rules.link import LinkedGoBinary, LinkGoBinaryRequest
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.resources import read_resource


@dataclass(frozen=True)
class LoadedGoBinary:
    digest: Digest


@dataclass(frozen=True)
class LoadedGoBinaryRequest(EngineAwareParameter):
    dir_name: str
    file_names: tuple[str, ...]
    output_name: str

    def debug_hint(self) -> str:
        return self.output_name


@dataclass(frozen=True)
class NaiveBuildGoPackageRequestForStdlibPackageRequest:
    import_path: str


# This rule is necessary because the rules in this file are used to build internal binaries including the
# package analyzer.
@rule
async def naive_build_go_package_request_for_stdlib(
    request: NaiveBuildGoPackageRequestForStdlibPackageRequest,
    goroot: GoRoot,
) -> BuildGoPackageRequest:
    stdlib_packages = await Get(
        GoStdLibPackages,
        GoStdLibPackagesRequest(with_race_detector=False, cgo_enabled=False),
    )

    pkg_info = stdlib_packages[request.import_path]

    dep_build_requests = await MultiGet(
        Get(
            BuildGoPackageRequest,
            NaiveBuildGoPackageRequestForStdlibPackageRequest(
                import_path=dep_import_path,
            ),
        )
        for dep_import_path in pkg_info.imports
        if dep_import_path not in ("C", "unsafe", "builtin")
    )

    return BuildGoPackageRequest(
        import_path=request.import_path,
        pkg_name=pkg_info.name,
        dir_path=pkg_info.pkg_source_path,
        digest=EMPTY_DIGEST,
        go_files=pkg_info.go_files,
        s_files=pkg_info.s_files,
        prebuilt_object_files=pkg_info.syso_files,
        direct_dependencies=tuple(dep_build_requests),
        minimum_go_version=goroot.version,
        build_opts=GoBuildOptions(cgo_enabled=False),
        is_stdlib=True,
    )


def setup_files(dir_name: str, file_names: tuple[str, ...]) -> tuple[FileContent, ...]:
    def get_file(file_name: str) -> bytes:
        content = read_resource(f"pants.backend.go.go_sources.{dir_name}", file_name)
        if not content:
            raise AssertionError(f"Unable to find resource for `{file_name}`.")
        return content

    return tuple(FileContent(f, get_file(f)) for f in file_names)


_IMPORTS_REGEX = re.compile(r"^import\s+\((.*?)\)", re.MULTILINE | re.DOTALL)


def _extract_imports(files: Iterable[FileContent]) -> set[str]:
    """Extract Go imports naively from given content."""
    imports: set[str] = set()
    for f in files:
        m = _IMPORTS_REGEX.search(f.content.decode())
        if m:
            f_imports = [x.strip('"') for x in m.group(1).split()]
            imports.update(f_imports)
    return imports


# TODO(13879): Maybe see if can consolidate compilation of wrapper binaries to common rules with Scala/Java?
@rule
async def setup_go_binary(request: LoadedGoBinaryRequest, goroot: GoRoot) -> LoadedGoBinary:
    file_contents = setup_files(request.dir_name, request.file_names)
    imports = _extract_imports(file_contents)
    imports.add("runtime")  # implicit linker dependency for all Go binaries

    build_opts = GoBuildOptions(cgo_enabled=False)

    source_digest = await Get(Digest, CreateDigest(file_contents))

    dep_build_requests = await MultiGet(
        Get(
            BuildGoPackageRequest,
            NaiveBuildGoPackageRequestForStdlibPackageRequest(dep_import_path),
        )
        for dep_import_path in sorted(imports)
    )

    built_pkg = await Get(
        BuiltGoPackage,
        BuildGoPackageRequest(
            import_path="main",
            pkg_name="main",
            dir_path=".",
            build_opts=build_opts,
            digest=source_digest,
            go_files=tuple(fc.path for fc in file_contents),
            s_files=(),
            direct_dependencies=dep_build_requests,
            minimum_go_version=goroot.version,
        ),
    )

    main_pkg_a_file_path = built_pkg.import_paths_to_pkg_a_files["main"]

    binary = await Get(
        LinkedGoBinary,
        LinkGoBinaryRequest(
            input_digest=built_pkg.digest,
            archives=(main_pkg_a_file_path,),
            build_opts=build_opts,
            import_paths_to_pkg_a_files=built_pkg.import_paths_to_pkg_a_files,
            output_filename=request.output_name,
            description=f"Link internal Go binary `{request.output_name}`",
        ),
    )
    return LoadedGoBinary(binary.digest)


def rules():
    return collect_rules()
