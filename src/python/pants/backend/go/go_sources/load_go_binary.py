# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.go.util_rules.build_pkg import BuildGoPackageRequest, BuiltGoPackage
from pants.backend.go.util_rules.import_analysis import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.link import LinkedGoBinary, LinkGoBinaryRequest
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
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


def setup_files(dir_name: str, file_names: tuple[str, ...]) -> tuple[FileContent, ...]:
    def get_file(file_name: str) -> bytes:
        content = read_resource(f"pants.backend.go.go_sources.{dir_name}", file_name)
        if not content:
            raise AssertionError(f"Unable to find resource for `{file_name}`.")
        return content

    return tuple(FileContent(f, get_file(f)) for f in file_names)


# TODO(13879): Maybe see if can consolidate compilation of wrapper binaries to common rules with Scala/Java?
@rule
async def setup_go_binary(request: LoadedGoBinaryRequest) -> LoadedGoBinary:
    file_contents = setup_files(request.dir_name, request.file_names)

    source_digest, import_config = await MultiGet(
        Get(Digest, CreateDigest(file_contents)),
        Get(ImportConfig, ImportConfigRequest, ImportConfigRequest.stdlib_only()),
    )

    built_pkg = await Get(
        BuiltGoPackage,
        BuildGoPackageRequest(
            import_path="main",
            dir_path="",
            digest=source_digest,
            go_file_names=tuple(fc.path for fc in file_contents),
            s_file_names=(),
            direct_dependencies=(),
            minimum_go_version=None,
        ),
    )
    main_pkg_a_file_path = built_pkg.import_paths_to_pkg_a_files["main"]
    input_digest = await Get(Digest, MergeDigests([built_pkg.digest, import_config.digest]))

    binary = await Get(
        LinkedGoBinary,
        LinkGoBinaryRequest(
            input_digest=input_digest,
            archives=(main_pkg_a_file_path,),
            import_config_path=import_config.CONFIG_PATH,
            output_filename=request.output_name,
            description="Link Go package analyzer",
        ),
    )
    return LoadedGoBinary(binary.digest)


def rules():
    return collect_rules()
