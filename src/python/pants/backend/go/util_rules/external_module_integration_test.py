# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.go.util_rules import external_module, sdk
from pants.backend.go.util_rules.external_module import (
    DownloadedExternalModule,
    DownloadExternalModuleRequest,
    ExternalModulePkgImportPaths,
    ExternalModulePkgImportPathsRequest,
)
from pants.engine.fs import Snapshot
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *external_module.rules(),
            QueryRule(DownloadedExternalModule, [DownloadExternalModuleRequest]),
            QueryRule(ExternalModulePkgImportPaths, [ExternalModulePkgImportPathsRequest]),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_download_external_module(rule_runner: RuleRunner) -> None:
    downloaded_module = rule_runner.request(
        DownloadedExternalModule,
        [DownloadExternalModuleRequest("github.com/google/uuid", "v1.3.0")],
    )
    assert downloaded_module.path == "github.com/google/uuid"
    assert downloaded_module.version == "v1.3.0"

    snapshot = rule_runner.request(Snapshot, [downloaded_module.digest])
    assert any(
        fp == "uuid.go" for fp in snapshot.files
    ), f"Could not find `uuid.go` in {snapshot.files}"
    assert any(
        fp == "go.mod" for fp in snapshot.files
    ), f"Could not find `go.mod` in {snapshot.files}"


def test_download_external_module_with_no_gomod(rule_runner: RuleRunner) -> None:
    downloaded_module = rule_runner.request(
        DownloadedExternalModule,
        [DownloadExternalModuleRequest("cloud.google.com/go", "v0.26.0")],
    )
    assert downloaded_module.path == "cloud.google.com/go"
    assert downloaded_module.version == "v0.26.0"

    snapshot = rule_runner.request(Snapshot, [downloaded_module.digest])
    assert any(
        fp == "bigtable/filter.go" for fp in snapshot.files
    ), f"Could not find `bigtable/filter.go` in {snapshot.files}"
    assert any(
        fp == "go.mod" for fp in snapshot.files
    ), f"Could not find `go.mod` in {snapshot.files}"


def test_resolve_packages_of_go_external_module(rule_runner: RuleRunner) -> None:
    go_sum_digest = rule_runner.make_snapshot(
        {
            "go.sum": dedent(
                """\
                github.com/google/go-cmp v0.5.6 h1:BKbKCqvP6I+rmFHt06ZmyQtvB8xAkWdhFyr0ZUNZcxQ=
                github.com/google/go-cmp v0.5.6/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                """
            )
        }
    ).digest
    result = rule_runner.request(
        ExternalModulePkgImportPaths,
        [ExternalModulePkgImportPathsRequest("github.com/google/go-cmp", "v0.5.6", go_sum_digest)],
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
