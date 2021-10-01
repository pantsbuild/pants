# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.target_types import GoExternalPackageTarget, GoModTarget
from pants.backend.go.util_rules import external_module, go_mod, go_pkg, sdk
from pants.backend.go.util_rules.external_module import (
    DownloadedExternalModule,
    DownloadedExternalModules,
    DownloadExternalModuleRequest,
    DownloadExternalModulesRequest,
    ExternalModulePkgImportPaths,
    ExternalModulePkgImportPathsRequest,
    ResolveExternalGoPackageRequest,
)
from pants.backend.go.util_rules.go_pkg import ResolvedGoPackage
from pants.engine.addresses import Address
from pants.engine.fs import Digest, PathGlobs, Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import ProcessExecutionFailure
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *go_mod.rules(),
            *go_pkg.rules(),
            *external_module.rules(),
            *target_type_rules.rules(),
            QueryRule(DownloadedExternalModules, [DownloadExternalModulesRequest]),
            QueryRule(DownloadedExternalModule, [DownloadExternalModuleRequest]),
            QueryRule(ExternalModulePkgImportPaths, [ExternalModulePkgImportPathsRequest]),
            QueryRule(ResolvedGoPackage, [ResolveExternalGoPackageRequest]),
        ],
        target_types=[GoModTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_download_external_modules(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot(
        {
            "go.mod": dedent(
                """\
                module example.com/external-module
                go 1.17
                require (
                    // Has a `go.mod` already.
                    github.com/google/uuid v1.3.0
                    // Does not have a `go.mod`, should be generated.
                    cloud.google.com/go v0.26.0
                )
                """
            ),
            "go.sum": dedent(
                """\
                cloud.google.com/go v0.26.0 h1:e0WKqKTd5BnrG8aKH3J3h+QvEIQtSUcf2n5UZ5ZgLtQ=
                cloud.google.com/go v0.26.0/go.mod h1:aQUYkXzVsufM+DwF1aE+0xfcU+56JwCaLick0ClmMTw=
                github.com/google/uuid v1.3.0 h1:t6JiXgmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
                github.com/google/uuid v1.3.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                """
            ),
        }
    ).digest
    downloaded_modules = rule_runner.request(
        DownloadedExternalModules, [DownloadExternalModulesRequest(input_digest)]
    )
    snapshot = rule_runner.request(Snapshot, [downloaded_modules.digest])
    all_files = snapshot.files

    def assert_has_file(expected_fp: str) -> None:
        assert any(
            fp == expected_fp for fp in all_files
        ), f"Could not find `{expected_fp}` in {sorted(all_files)}"

    for fp in (
        "go.mod",
        "go.sum",
        "gopath/pkg/mod/cloud.google.com/go@v0.26.0/go.mod",
        "gopath/pkg/mod/cloud.google.com/go@v0.26.0/bigtable/filter.go",
        "gopath/pkg/mod/github.com/google/uuid@v1.3.0/go.mod",
        "gopath/pkg/mod/github.com/google/uuid@v1.3.0/uuid.go",
    ):
        assert_has_file(fp)


def test_download_external_module_invalid_go_sum(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot(
        {
            "go.mod": dedent(
                """\
                module example.com/external-module
                go 1.17
                require github.com/google/uuid v1.3.0
                """
            ),
            "go.sum": dedent(
                """\
                github.com/google/uuid v1.3.0 h1:00000gmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
                github.com/google/uuid v1.3.0/go.mod h1:00000e4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                """
            ),
        }
    ).digest
    with pytest.raises(ExecutionError) as exc:
        rule_runner.request(
            DownloadedExternalModules, [DownloadExternalModulesRequest(input_digest)]
        )
    underlying_exception = exc.value.wrapped_exceptions[0]
    assert isinstance(underlying_exception, ProcessExecutionFailure)
    assert "SECURITY ERROR" in str(underlying_exception)


def test_download_external_module_missing_go_sum(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot(
        {
            "go.mod": dedent(
                """\
                module example.com/external-module
                go 1.17
                require github.com/google/uuid v1.3.0
                """
            ),
            # `go.sum` is for a different module.
            "go.sum": dedent(
                """\
                cloud.google.com/go v0.26.0 h1:e0WKqKTd5BnrG8aKH3J3h+QvEIQtSUcf2n5UZ5ZgLtQ=
                cloud.google.com/go v0.26.0/go.mod h1:aQUYkXzVsufM+DwF1aE+0xfcU+56JwCaLick0ClmMTw=
                """
            ),
        }
    ).digest
    with pytest.raises(ExecutionError) as exc:
        rule_runner.request(
            DownloadedExternalModules, [DownloadExternalModulesRequest(input_digest)]
        )
    underlying_exception = exc.value.wrapped_exceptions[0]
    assert "`go.mod` and/or `go.sum` changed!" in str(underlying_exception)


def test_download_external_module_with_gomod(rule_runner: RuleRunner) -> None:
    go_sum_digest = rule_runner.make_snapshot(
        {
            "go.sum": dedent(
                """\
                github.com/google/uuid v1.3.0 h1:t6JiXgmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
                github.com/google/uuid v1.3.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                """
            )
        }
    ).digest
    downloaded_module = rule_runner.request(
        DownloadedExternalModule,
        [DownloadExternalModuleRequest("github.com/google/uuid", "v1.3.0", go_sum_digest)],
    )
    assert downloaded_module.path == "github.com/google/uuid"
    assert downloaded_module.version == "v1.3.0"

    snapshot = rule_runner.request(Snapshot, [downloaded_module.digest])

    def assert_has_file(expected_fp: str) -> None:
        assert any(
            fp == expected_fp for fp in snapshot.files
        ), f"Could not find `{expected_fp}` in {snapshot.files}"

    for fp in ("uuid.go", "go.mod"):
        assert_has_file(fp)


def test_download_external_module_with_no_gomod(rule_runner: RuleRunner) -> None:
    go_sum_digest = rule_runner.make_snapshot(
        {
            "go.sum": dedent(
                """\
                cloud.google.com/go v0.26.0 h1:e0WKqKTd5BnrG8aKH3J3h+QvEIQtSUcf2n5UZ5ZgLtQ=
                cloud.google.com/go v0.26.0/go.mod h1:aQUYkXzVsufM+DwF1aE+0xfcU+56JwCaLick0ClmMTw=
                """
            )
        }
    ).digest
    downloaded_module = rule_runner.request(
        DownloadedExternalModule,
        [DownloadExternalModuleRequest("cloud.google.com/go", "v0.26.0", go_sum_digest)],
    )
    assert downloaded_module.path == "cloud.google.com/go"
    assert downloaded_module.version == "v0.26.0"

    snapshot = rule_runner.request(Snapshot, [downloaded_module.digest])

    def assert_has_file(expected_fp: str) -> None:
        assert any(
            fp == expected_fp for fp in snapshot.files
        ), f"Could not find `{expected_fp}` in {snapshot.files}"

    for fp in ("bigtable/filter.go", "go.mod"):
        assert_has_file(fp)


def test_determine_external_package_info(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/external-module
                go 1.17
                require (
                    github.com/google/go-cmp v0.5.6
                    golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543  // indirect
                )
                """
            ),
            "go.sum": dedent(
                """\
                github.com/google/go-cmp v0.5.6 h1:BKbKCqvP6I+rmFHt06ZmyQtvB8xAkWdhFyr0ZUNZcxQ=
                github.com/google/go-cmp v0.5.6/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                """
            ),
            "BUILD": "go_mod(name='mod')",
        }
    )
    input_digest = rule_runner.request(Digest, [PathGlobs(["go.mod", "go.sum"])])
    pkg_addr = Address("", target_name="mod", generated_name="github.com/google/go-cmp/cmp/cmpopts")
    tgt = rule_runner.get_target(pkg_addr)
    assert isinstance(tgt, GoExternalPackageTarget)

    pkg_info = rule_runner.request(
        ResolvedGoPackage, [ResolveExternalGoPackageRequest(tgt, input_digest)]
    )
    assert pkg_info.address == pkg_addr
    assert pkg_info.module_address is None
    assert pkg_info.import_path == "github.com/google/go-cmp/cmp/cmpopts"
    assert pkg_info.module_path == "github.com/google/go-cmp"
    assert pkg_info.module_version == "v0.5.6"
    assert pkg_info.package_name == "cmpopts"
    assert pkg_info.imports == (
        "errors",
        "fmt",
        "github.com/google/go-cmp/cmp",
        "github.com/google/go-cmp/cmp/internal/function",
        "math",
        "reflect",
        "sort",
        "strings",
        "time",
        "unicode",
        "unicode/utf8",
    )
    assert pkg_info.test_imports == (
        "bytes",
        "errors",
        "fmt",
        "github.com/google/go-cmp/cmp",
        "golang.org/x/xerrors",
        "io",
        "math",
        "reflect",
        "strings",
        "sync",
        "testing",
        "time",
    )
    assert pkg_info.go_files == (
        "equate.go",
        "errors_go113.go",
        "ignore.go",
        "sort.go",
        "struct_filter.go",
        "xform.go",
    )
    assert pkg_info.test_go_files == ("util_test.go",)
    assert pkg_info.xtest_go_files == ("example_test.go",)
    assert not pkg_info.c_files
    assert not pkg_info.cgo_files
    assert not pkg_info.cxx_files
    assert not pkg_info.m_files
    assert not pkg_info.h_files
    assert not pkg_info.s_files
    assert not pkg_info.syso_files


def test_determine_external_module_package_import_paths(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot(
        {
            "go.mod": dedent(
                """\
                module example.com/external-module
                go 1.17
                require (
                    github.com/google/go-cmp v0.5.6
                    golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543  // indirect
                )
                """
            ),
            "go.sum": dedent(
                """\
                github.com/google/go-cmp v0.5.6 h1:BKbKCqvP6I+rmFHt06ZmyQtvB8xAkWdhFyr0ZUNZcxQ=
                github.com/google/go-cmp v0.5.6/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                """
            ),
        }
    ).digest
    result = rule_runner.request(
        ExternalModulePkgImportPaths,
        [ExternalModulePkgImportPathsRequest("github.com/google/go-cmp", "v0.5.6", input_digest)],
    )
    assert result == ExternalModulePkgImportPaths(
        [
            "github.com/google/go-cmp/cmp",
            "github.com/google/go-cmp/cmp/cmpopts",
            "github.com/google/go-cmp/cmp/internal/diff",
            "github.com/google/go-cmp/cmp/internal/flags",
            "github.com/google/go-cmp/cmp/internal/function",
            "github.com/google/go-cmp/cmp/internal/testprotos",
            "github.com/google/go-cmp/cmp/internal/teststructs",
            "github.com/google/go-cmp/cmp/internal/teststructs/foo1",
            "github.com/google/go-cmp/cmp/internal/teststructs/foo2",
            "github.com/google/go-cmp/cmp/internal/value",
        ]
    )
