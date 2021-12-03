# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import pkgutil
from dataclasses import dataclass
from typing import ClassVar

from pants.backend.go.util_rules.build_pkg import BuildGoPackageRequest, BuiltGoPackage
from pants.backend.go.util_rules.import_analysis import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.link import LinkedGoBinary, LinkGoBinaryRequest
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class GenerateTestMainRequest(EngineAwareParameter):
    digest: Digest
    test_paths: FrozenOrderedSet[str]
    xtest_paths: FrozenOrderedSet[str]
    import_path: str
    address: Address

    def debug_hint(self) -> str:
        return self.address.spec


@dataclass(frozen=True)
class GeneratedTestMain:
    digest: Digest
    has_tests: bool
    has_xtests: bool
    failed_exit_code_and_stderr: tuple[int, str] | None

    TEST_MAIN_FILE = "_testmain.go"
    TEST_PKG = "_test"
    XTEST_PKG = "_xtest"


@dataclass(frozen=True)
class AnalyzerSetup:
    digest: Digest
    PATH: ClassVar[str] = "./analyzer"


@rule
async def setup_analyzer() -> AnalyzerSetup:
    source_entry_content = pkgutil.get_data("pants.backend.go.go_sources", "generate_testmain.go")
    if not source_entry_content:
        raise AssertionError("Unable to find resource for `generate_testmain.go`.")

    source_entry = FileContent("generate_testmain.go", source_entry_content)

    source_digest, import_config = await MultiGet(
        Get(Digest, CreateDigest([source_entry])),
        Get(ImportConfig, ImportConfigRequest, ImportConfigRequest.stdlib_only()),
    )

    built_analyzer_pkg = await Get(
        BuiltGoPackage,
        BuildGoPackageRequest(
            import_path="main",
            dir_path="",
            digest=source_digest,
            go_file_names=(source_entry.path,),
            s_file_names=(),
            direct_dependencies=(),
            minimum_go_version=None,
        ),
    )
    main_pkg_a_file_path = built_analyzer_pkg.import_paths_to_pkg_a_files["main"]
    input_digest = await Get(
        Digest, MergeDigests([built_analyzer_pkg.digest, import_config.digest])
    )

    analyzer = await Get(
        LinkedGoBinary,
        LinkGoBinaryRequest(
            input_digest=input_digest,
            archives=(main_pkg_a_file_path,),
            import_config_path=import_config.CONFIG_PATH,
            output_filename=AnalyzerSetup.PATH,
            description="Link Go test sources analyzer",
        ),
    )

    return AnalyzerSetup(analyzer.digest)


@rule
async def generate_testmain(
    request: GenerateTestMainRequest, analyzer: AnalyzerSetup
) -> GeneratedTestMain:
    input_digest = await Get(Digest, MergeDigests([request.digest, analyzer.digest]))

    test_paths = tuple(f"{GeneratedTestMain.TEST_PKG}:{path}" for path in request.test_paths)
    xtest_paths = tuple(f"{GeneratedTestMain.XTEST_PKG}:{path}" for path in request.xtest_paths)

    result = await Get(
        FallibleProcessResult,
        Process(
            argv=(analyzer.PATH, request.import_path, *test_paths, *xtest_paths),
            input_digest=input_digest,
            description=f"Analyze Go test sources for {request.address}",
            level=LogLevel.DEBUG,
            output_files=("_testmain.go",),
        ),
    )
    if result.exit_code != 0:
        return GeneratedTestMain(
            digest=EMPTY_DIGEST,
            has_tests=False,
            has_xtests=False,
            failed_exit_code_and_stderr=(result.exit_code, result.stderr.decode("utf-8")),
        )

    metadata = json.loads(result.stdout.decode("utf-8"))
    return GeneratedTestMain(
        digest=result.output_digest,
        has_tests=metadata["has_tests"],
        has_xtests=metadata["has_xtests"],
        failed_exit_code_and_stderr=None,
    )


def rules():
    return collect_rules()
