# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.go.util_rules import external_module, sdk
from pants.backend.go.util_rules.external_module import (
    DownloadedExternalModule,
    DownloadExternalModuleRequest,
    PackagesFromExternalModule,
    PackagesFromExternalModuleRequest,
)
from pants.engine.fs import EMPTY_DIGEST, Snapshot
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *external_module.rules(),
            QueryRule(DownloadedExternalModule, [DownloadExternalModuleRequest]),
            QueryRule(PackagesFromExternalModule, [PackagesFromExternalModuleRequest]),
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
    result = rule_runner.request(
        PackagesFromExternalModule,
        [
            PackagesFromExternalModuleRequest(
                "github.com/google/go-cmp", "v0.5.6", go_sum_digest=EMPTY_DIGEST
            )
        ],
    )

    import_path_to_package = {pkg.import_path: pkg for pkg in result}
    assert len(import_path_to_package) > 1

    pkg = import_path_to_package["github.com/google/go-cmp/cmp"]
    assert pkg.address is None
    assert pkg.package_name == "cmp"
    assert len(pkg.go_files) > 0
