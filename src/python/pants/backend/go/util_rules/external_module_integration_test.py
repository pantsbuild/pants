# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.go.target_types import GoModule, GoPackage
from pants.backend.go.util_rules import external_module, sdk
from pants.backend.go.util_rules.external_module import (
    DownloadedExternalModule,
    DownloadExternalModuleRequest,
    ResolveExternalGoModuleToPackagesRequest,
    ResolveExternalGoModuleToPackagesResult,
)
from pants.core.util_rules import external_tool, source_files
from pants.engine import fs
from pants.engine.fs import EMPTY_DIGEST, Digest, DigestContents
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *external_tool.rules(),
            *source_files.rules(),
            *fs.rules(),
            *sdk.rules(),
            *external_module.rules(),
            QueryRule(DownloadedExternalModule, [DownloadExternalModuleRequest]),
            QueryRule(
                ResolveExternalGoModuleToPackagesResult, [ResolveExternalGoModuleToPackagesRequest]
            ),
            QueryRule(DigestContents, [Digest]),
        ],
        target_types=[GoPackage, GoModule],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_download_external_module(rule_runner: RuleRunner) -> None:
    downloaded_module = rule_runner.request(
        DownloadedExternalModule,
        [DownloadExternalModuleRequest(path="github.com/google/uuid", version="v1.3.0")],
    )
    assert downloaded_module.path == "github.com/google/uuid"
    assert downloaded_module.version == "v1.3.0"

    digest_contents = rule_runner.request(DigestContents, [downloaded_module.digest])
    found_uuid_go_file = False
    for file_content in digest_contents:
        if file_content.path == "uuid.go":
            found_uuid_go_file = True
            break
    assert found_uuid_go_file


def test_download_external_module_with_no_gomod(rule_runner: RuleRunner) -> None:
    downloaded_module = rule_runner.request(
        DownloadedExternalModule,
        [DownloadExternalModuleRequest(path="cloud.google.com/go", version="v0.26.0")],
    )
    assert downloaded_module.path == "cloud.google.com/go"
    assert downloaded_module.version == "v0.26.0"

    digest_contents = rule_runner.request(DigestContents, [downloaded_module.digest])
    found_go_mod = False
    for file_content in digest_contents:
        if file_content.path == "go.mod":
            found_go_mod = True
            break
    assert found_go_mod


def test_resolve_packages_of_go_external_module(rule_runner: RuleRunner) -> None:
    result = rule_runner.request(
        ResolveExternalGoModuleToPackagesResult,
        [
            ResolveExternalGoModuleToPackagesRequest(
                path="github.com/google/go-cmp",
                version="v0.5.6",
                go_sum_digest=EMPTY_DIGEST,
            )
        ],
    )

    import_path_to_package = {pkg.import_path: pkg for pkg in result.packages}
    assert len(import_path_to_package) > 1

    pkg = import_path_to_package["github.com/google/go-cmp/cmp"]
    assert pkg is not None
    assert pkg.address is None
    assert pkg.package_name == "cmp"
    assert len(pkg.go_files) > 0
