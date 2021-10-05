# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.target_types import GoExternalPackageTarget, GoModTarget
from pants.backend.go.util_rules import external_module, go_mod, go_pkg, sdk
from pants.backend.go.util_rules.external_module import (
    AllDownloadedModules,
    AllDownloadedModulesRequest,
    DownloadedModule,
    DownloadedModuleRequest,
    ExternalModulePackages,
    ExternalModulePackagesRequest,
    ResolveExternalGoPackageRequest,
)
from pants.backend.go.util_rules.go_pkg import ResolvedGoPackage
from pants.engine.addresses import Address
from pants.engine.fs import Digest, PathGlobs, Snapshot
from pants.engine.process import ProcessExecutionFailure
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *go_mod.rules(),
            *go_pkg.rules(),
            *external_module.rules(),
            *target_type_rules.rules(),
            QueryRule(AllDownloadedModules, [AllDownloadedModulesRequest]),
            QueryRule(DownloadedModule, [DownloadedModuleRequest]),
            QueryRule(ExternalModulePackages, [ExternalModulePackagesRequest]),
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


def test_download_modules(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot({"go.mod": GO_MOD, "go.sum": GO_SUM}).digest
    downloaded_modules = rule_runner.request(
        AllDownloadedModules, [AllDownloadedModulesRequest(input_digest)]
    )
    assert len(downloaded_modules) == 7

    def assert_module(module: str, version: str, sample_file: str) -> None:
        assert (module, version) in downloaded_modules
        digest = downloaded_modules[(module, version)]
        snapshot = rule_runner.request(Snapshot, [digest])
        assert "go.mod" in snapshot.files
        assert "go.sum" in snapshot.files
        assert sample_file in snapshot.files

        extracted_module = rule_runner.request(
            DownloadedModule, [DownloadedModuleRequest(module, version, input_digest)]
        )
        extracted_snapshot = rule_runner.request(Snapshot, [extracted_module.digest])
        assert extracted_snapshot == snapshot

    assert_module("cloud.google.com/go", "v0.26.0", "bigtable/filter.go")
    assert_module("github.com/google/uuid", "v1.3.0", "uuid.go")
    assert_module("github.com/google/go-cmp", "v0.5.6", "cmp/cmpopts/errors_go113.go")
    assert_module("golang.org/x/text", "v0.0.0-20170915032832-14c0d48ead0c", "width/transform.go")
    assert_module("golang.org/x/xerrors", "v0.0.0-20191204190536-9bdfabe68543", "wrap.go")
    assert_module("rsc.io/quote", "v1.5.2", "quote.go")
    assert_module("rsc.io/sampler", "v1.3.0", "sampler.go")


def test_download_modules_missing_module(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot({"go.mod": GO_MOD, "go.sum": GO_SUM}).digest
    with engine_error(
        AssertionError, contains="The module some_project.org/project@v1.1 was not downloaded"
    ):
        rule_runner.request(
            DownloadedModule,
            [DownloadedModuleRequest("some_project.org/project", "v1.1", input_digest)],
        )


def test_download_modules_invalid_go_sum(rule_runner: RuleRunner) -> None:
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
    with engine_error(ProcessExecutionFailure, contains="SECURITY ERROR"):
        rule_runner.request(AllDownloadedModules, [AllDownloadedModulesRequest(input_digest)])


def test_download_modules_missing_go_sum(rule_runner: RuleRunner) -> None:
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
    with engine_error(contains="`go.mod` and/or `go.sum` changed!"):
        rule_runner.request(AllDownloadedModules, [AllDownloadedModulesRequest(input_digest)])


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


def test_determine_external_module_packages(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot({"go.mod": GO_MOD, "go.sum": GO_SUM}).digest

    def assert_packages(
        module_path: str,
        version: str,
        expected: list[str] | dict[str, list[str]],
        *,
        check_subset: bool = False
    ) -> None:
        result = rule_runner.request(
            ExternalModulePackages,
            [ExternalModulePackagesRequest(module_path, version, input_digest)],
        )
        if check_subset:
            assert isinstance(expected, list)
            assert set(expected).issubset(result.keys())
        else:
            if isinstance(expected, dict):
                assert dict(result) == {k: tuple(v) for k, v in expected.items()}
            else:
                assert list(result.keys()) == expected

    assert_packages(
        "cloud.google.com/go",
        "v0.26.0",
        ["cloud.google.com/go/bigquery", "cloud.google.com/go/firestore"],
        check_subset=True,
    )
    assert_packages(
        "github.com/google/uuid",
        "v1.3.0",
        {
            "github.com/google/uuid": [
                "bytes",
                "crypto/md5",
                "crypto/rand",
                "crypto/sha1",
                "database/sql/driver",
                "encoding/binary",
                "encoding/hex",
                "encoding/json",
                "errors",
                "fmt",
                "hash",
                "io",
                "net",
                "os",
                "strings",
                "sync",
                "time",
            ]
        },
    )

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
        {
            "golang.org/x/xerrors": [
                "bytes",
                "fmt",
                "golang.org/x/xerrors/internal",
                "io",
                "reflect",
                "runtime",
                "strconv",
                "strings",
                "unicode",
                "unicode/utf8",
            ],
            "golang.org/x/xerrors/internal": [],
        },
    )

    assert_packages("rsc.io/quote", "v1.5.2", ["rsc.io/quote", "rsc.io/quote/buggy"])
    assert_packages("rsc.io/sampler", "v1.3.0", ["rsc.io/sampler"])
