# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go.target_types import GoModTarget
from pants.backend.go.util_rules import external_pkg, sdk
from pants.backend.go.util_rules.external_pkg import (
    ExternalModuleInfo,
    ExternalModuleInfoRequest,
    ExternalPkgInfo,
    ExternalPkgInfoRequest,
    _AllDownloadedModules,
    _AllDownloadedModulesRequest,
    _DownloadedModule,
    _DownloadedModuleRequest,
)
from pants.engine.fs import Digest, PathGlobs, Snapshot
from pants.engine.process import ProcessExecutionFailure
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *external_pkg.rules(),
            QueryRule(_AllDownloadedModules, [_AllDownloadedModulesRequest]),
            QueryRule(_DownloadedModule, [_DownloadedModuleRequest]),
            QueryRule(ExternalModuleInfo, [ExternalModuleInfoRequest]),
            QueryRule(ExternalPkgInfo, [ExternalPkgInfoRequest]),
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


# -----------------------------------------------------------------------------------------------
# Download modules
# -----------------------------------------------------------------------------------------------


def test_download_modules(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot({"go.mod": GO_MOD, "go.sum": GO_SUM}).digest
    downloaded_modules = rule_runner.request(
        _AllDownloadedModules, [_AllDownloadedModulesRequest(input_digest)]
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
            _DownloadedModule, [_DownloadedModuleRequest(module, version, input_digest)]
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
            _DownloadedModule,
            [_DownloadedModuleRequest("some_project.org/project", "v1.1", input_digest)],
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
        rule_runner.request(_AllDownloadedModules, [_AllDownloadedModulesRequest(input_digest)])


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
        rule_runner.request(_AllDownloadedModules, [_AllDownloadedModulesRequest(input_digest)])


# -----------------------------------------------------------------------------------------------
# Determine package info
# -----------------------------------------------------------------------------------------------


def test_determine_pkg_info(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"go.mod": GO_MOD, "go.sum": GO_SUM, "BUILD": "go_mod(name='mod')"})
    input_digest = rule_runner.request(Digest, [PathGlobs(["go.mod", "go.sum"])])

    def assert_module(
        module: str,
        version: str,
        expected: list[str] | dict[str, ExternalPkgInfo],
        *,
        check_subset: bool = False,
        skip_checking_pkg_info: bool = False,
    ) -> None:
        module_info = rule_runner.request(
            ExternalModuleInfo, [ExternalModuleInfoRequest(module, version, input_digest)]
        )
        # If `check_subset`, check that the expected import_paths are included.
        if check_subset:
            assert isinstance(expected, list)
            assert set(expected).issubset(module_info.keys())
        else:
            # If expected is a dict, check that the ExternalPkgInfo is correct for each package.
            if isinstance(expected, dict):
                assert dict(module_info) == expected
            # Else, only check that the import paths are present.
            else:
                assert list(module_info.keys()) == expected

        # Check our subsetting logic.
        if not skip_checking_pkg_info:
            for pkg_info in module_info.values():
                extracted_pkg = rule_runner.request(
                    ExternalPkgInfo,
                    [ExternalPkgInfoRequest(pkg_info.import_path, module, version, input_digest)],
                )
                assert extracted_pkg == pkg_info

    assert_module(
        "cloud.google.com/go",
        "v0.26.0",
        ["cloud.google.com/go/bigquery", "cloud.google.com/go/firestore"],
        check_subset=True,
    )

    uuid_mod = "github.com/google/uuid"
    uuid_version = "v1.3.0"
    uuid_digest = rule_runner.request(
        _DownloadedModule, [_DownloadedModuleRequest(uuid_mod, uuid_version, input_digest)]
    ).digest
    assert_module(
        uuid_mod,
        uuid_version,
        {
            uuid_mod: ExternalPkgInfo(
                import_path=uuid_mod,
                module_path=uuid_mod,
                version=uuid_version,
                digest=uuid_digest,
                imports=(
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
                ),
                go_files=(
                    "dce.go",
                    "doc.go",
                    "hash.go",
                    "marshal.go",
                    "node.go",
                    "node_net.go",
                    "null.go",
                    "sql.go",
                    "time.go",
                    "util.go",
                    "uuid.go",
                    "version1.go",
                    "version4.go",
                ),
                s_files=(),
            )
        },
    )

    assert_module(
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
    assert_module(
        "golang.org/x/text",
        "v0.0.0-20170915032832-14c0d48ead0c",
        ["golang.org/x/text/cmd/gotext", "golang.org/x/text/collate"],
        check_subset=True,
        skip_checking_pkg_info=True,  # Contains unsupported `.cgo` files.
    )
    assert_module(
        "golang.org/x/xerrors",
        "v0.0.0-20191204190536-9bdfabe68543",
        ["golang.org/x/xerrors", "golang.org/x/xerrors/internal"],
    )

    assert_module("rsc.io/quote", "v1.5.2", ["rsc.io/quote", "rsc.io/quote/buggy"])
    assert_module("rsc.io/sampler", "v1.3.0", ["rsc.io/sampler"])


def test_determine_pkg_info_missing(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot({"go.mod": GO_MOD, "go.sum": GO_SUM}).digest
    with engine_error(
        AssertionError,
        contains=(
            "The package another_project.org/foo does not belong to the module "
            "github.com/google/uuid@v1.3.0"
        ),
    ):
        rule_runner.request(
            ExternalPkgInfo,
            [
                ExternalPkgInfoRequest(
                    "another_project.org/foo", "github.com/google/uuid", "v1.3.0", input_digest
                )
            ],
        )


def test_unsupported_sources(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot({"go.mod": GO_MOD, "go.sum": GO_SUM}).digest

    # Nothing should error when computing `ExternalModuleInfo`, we only create an exception to
    # maybe raise later.
    module_info = rule_runner.request(
        ExternalModuleInfo,
        [
            ExternalModuleInfoRequest(
                "golang.org/x/text", "v0.0.0-20170915032832-14c0d48ead0c", input_digest
            )
        ],
    )
    assert (
        module_info["golang.org/x/text/collate/tools/colcmp"].unsupported_sources_error is not None
    )

    # Error when requesting the `ExternalPkgInfo`.
    with engine_error(NotImplementedError):
        rule_runner.request(
            ExternalPkgInfo,
            [
                ExternalPkgInfoRequest(
                    "golang.org/x/text/collate/tools/colcmp",
                    "golang.org/x/text",
                    "v0.0.0-20170915032832-14c0d48ead0c",
                    input_digest,
                )
            ],
        )
