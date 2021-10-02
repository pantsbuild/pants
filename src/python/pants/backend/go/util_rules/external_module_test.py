# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
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


GO_MOD = dedent(
    """\
    module example.com/external-module
    go 1.17

    // No dependencies, already has `go.mod`.
    require github.com/google/uuid v1.3.0

    // No dependencies, but missing `go.mod`.
    require cloud.google.com/go v0.26.0

    // Has dependencies, already has a `go.sum`.
    require (
        github.com/google/go-cmp v0.5.6
        golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543  // indirect
    )

    // Has dependencies, missing `go.sum`. This causes `go list` to fail in that directory unless
    // we add `go.sum`.
    require (
        rsc.io/quote v1.5.2
        golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c // indirect
        rsc.io/sampler v1.3.0 // indirect
    )
    """
)

GO_SUM = dedent(
    """\
    cloud.google.com/go v0.26.0 h1:e0WKqKTd5BnrG8aKH3J3h+QvEIQtSUcf2n5UZ5ZgLtQ=
    cloud.google.com/go v0.26.0/go.mod h1:aQUYkXzVsufM+DwF1aE+0xfcU+56JwCaLick0ClmMTw=
    github.com/google/go-cmp v0.5.6 h1:BKbKCqvP6I+rmFHt06ZmyQtvB8xAkWdhFyr0ZUNZcxQ=
    github.com/google/go-cmp v0.5.6/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
    github.com/google/uuid v1.3.0 h1:t6JiXgmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
    github.com/google/uuid v1.3.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
    golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c h1:qgOY6WgZOaTkIIMiVjBQcw93ERBE4m30iBm00nkL0i8=
    golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c/go.mod h1:NqM8EUOU14njkJ3fqMW+pc6Ldnwhi/IjpwHt7yyuwOQ=
    golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
    golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
    rsc.io/quote v1.5.2 h1:w5fcysjrx7yqtD/aO+QwRjYZOKnaM9Uh2b40tElTs3Y=
    rsc.io/quote v1.5.2/go.mod h1:LzX7hefJvL54yjefDEDHNONDjII0t9xZLPXsUe+TKr0=
    rsc.io/sampler v1.3.0 h1:7uVkIFmeBqHfdjD+gZwtXXI+RODJ2Wc4O7MPEh/QiW4=
    rsc.io/sampler v1.3.0/go.mod h1:T1hPZKmBbMNahiBKFy5HrXp6adAjACjK9JXDnKaTXpA=
    """
)


def test_download_external_modules(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot({"go.mod": GO_MOD, "go.sum": GO_SUM}).digest
    downloaded_modules = rule_runner.request(
        DownloadedExternalModules, [DownloadExternalModulesRequest(input_digest)]
    )
    snapshot = rule_runner.request(Snapshot, [downloaded_modules.digest])
    all_files = snapshot.files

    def assert_has_file(expected_fp: str) -> None:
        assert any(
            fp == expected_fp for fp in all_files
        ), f"Could not find `{expected_fp}` in {sorted(all_files)}"

    def module_files(module_dir: str, sample_file: str) -> list[str]:
        module_dir = os.path.join("gopath/pkg/mod", module_dir)
        return [
            os.path.join(module_dir, "go.mod"),
            os.path.join(module_dir, "go.sum"),
            os.path.join(module_dir, sample_file),
        ]

    for fp in (
        "go.mod",
        "go.sum",
        *module_files("cloud.google.com/go@v0.26.0", "bigtable/filter.go"),
        *module_files("github.com/google/uuid@v1.3.0", "uuid.go"),
        *module_files("github.com/google/go-cmp@v0.5.6", "cmp/cmpopts/errors_go113.go"),
        *module_files("golang.org/x/text@v0.0.0-20170915032832-14c0d48ead0c", "width/transform.go"),
        *module_files("golang.org/x/xerrors@v0.0.0-20191204190536-9bdfabe68543", "wrap.go"),
        *module_files("rsc.io/quote@v1.5.2", "quote.go"),
        *module_files("rsc.io/sampler@v1.3.0", "sampler.go"),
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
    rule_runner.write_files({"go.mod": GO_MOD, "go.sum": GO_SUM, "BUILD": "go_mod(name='mod')"})
    input_digest = rule_runner.request(Digest, [PathGlobs(["go.mod", "go.sum"])])

    def get_pkg_info(import_path: str) -> ResolvedGoPackage:
        pkg_addr = Address("", target_name="mod", generated_name=import_path)
        tgt = rule_runner.get_target(pkg_addr)
        assert isinstance(tgt, GoExternalPackageTarget)
        result = rule_runner.request(
            ResolvedGoPackage, [ResolveExternalGoPackageRequest(tgt, input_digest)]
        )
        assert result.address == pkg_addr
        assert result.module_address is None
        assert result.import_path == import_path
        return result

    cmp_info = get_pkg_info("github.com/google/go-cmp/cmp/cmpopts")
    assert cmp_info.module_path == "github.com/google/go-cmp"
    assert cmp_info.module_version == "v0.5.6"
    assert cmp_info.package_name == "cmpopts"
    assert cmp_info.imports == (
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
    assert cmp_info.test_imports == (
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
    assert cmp_info.go_files == (
        "equate.go",
        "errors_go113.go",
        "ignore.go",
        "sort.go",
        "struct_filter.go",
        "xform.go",
    )
    assert cmp_info.test_go_files == ("util_test.go",)
    assert cmp_info.xtest_go_files == ("example_test.go",)
    assert not cmp_info.c_files
    assert not cmp_info.cgo_files
    assert not cmp_info.cxx_files
    assert not cmp_info.m_files
    assert not cmp_info.h_files
    assert not cmp_info.s_files
    assert not cmp_info.syso_files

    # Spot check that the other modules can be analyzed.
    for pkg in (
        "cloud.google.com/go/bigquery",
        "github.com/google/uuid",
        "golang.org/x/text/collate",
        "golang.org/x/xerrors",
        "rsc.io/quote",
        "rsc.io/sampler",
    ):
        get_pkg_info(pkg)


def test_determine_external_module_package_import_paths(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot({"go.mod": GO_MOD, "go.sum": GO_SUM}).digest

    def assert_packages(
        module_path: str, version: str, expected: list[str], *, check_subset: bool = False
    ) -> None:
        result = rule_runner.request(
            ExternalModulePkgImportPaths,
            [ExternalModulePkgImportPathsRequest(module_path, version, input_digest)],
        )
        if check_subset:
            assert set(expected).issubset(result)
        else:
            assert list(result) == expected

    assert_packages(
        "cloud.google.com/go",
        "v0.26.0",
        ["cloud.google.com/go/bigquery", "cloud.google.com/go/firestore"],
        check_subset=True,
    )
    assert_packages("github.com/google/uuid", "v1.3.0", ["github.com/google/uuid"])

    assert_packages(
        "github.com/google/go-cmp",
        "v0.5.6",
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
        ],
    )
    assert_packages(
        "golang.org/x/text",
        "v0.0.0-20170915032832-14c0d48ead0c",
        ["golang.org/x/text/cmd/gotext", "golang.org/x/text/collate"],
        check_subset=True,
    )
    assert_packages(
        "golang.org/x/xerrors",
        "v0.0.0-20191204190536-9bdfabe68543",
        ["golang.org/x/xerrors", "golang.org/x/xerrors/internal"],
    )

    assert_packages("rsc.io/quote", "v1.5.2", ["rsc.io/quote", "rsc.io/quote/buggy"])
    assert_packages("rsc.io/sampler", "v1.3.0", ["rsc.io/sampler"])
