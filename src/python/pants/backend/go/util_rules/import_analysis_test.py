# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from textwrap import dedent

import pytest

from pants.backend.go.util_rules import import_analysis, sdk
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.import_analysis import (
    GoStdLibPackages,
    GoStdLibPackagesRequest,
    ImportConfig,
    ImportConfigRequest,
)
from pants.engine.fs import DigestContents
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *import_analysis.rules(),
            QueryRule(GoStdLibPackages, (GoStdLibPackagesRequest,)),
            QueryRule(ImportConfig, (ImportConfigRequest,)),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


@pytest.mark.parametrize("with_race_detector", (False, True))
def test_stdlib_package_resolution(rule_runner: RuleRunner, with_race_detector: bool) -> None:
    std_lib_imports = rule_runner.request(
        GoStdLibPackages, [GoStdLibPackagesRequest(with_race_detector=with_race_detector)]
    )
    assert "fmt" in std_lib_imports


def test_import_config_creation(rule_runner: RuleRunner) -> None:
    mapping = FrozenDict(
        {
            "some/import-path": "__pkgs__/some_import-path/__pkg__.a",
            "another/import-path/pkg1": "__pkgs__/another_import-path_pkg1/__pkg__.a",
            "another/import-path/pkg2": "__pkgs__/another_import-path_pkg2/__pkg__.a",
        }
    )

    def create_config(stdlib: bool) -> str:
        config = rule_runner.request(
            ImportConfig,
            [
                ImportConfigRequest(
                    mapping,
                    build_opts=GoBuildOptions(),
                    import_map=FrozenDict({"foo": "bar"}),
                    include_stdlib=stdlib,
                )
            ],
        )
        digest_contents = rule_runner.request(DigestContents, [config.digest])
        assert len(digest_contents) == 1
        file_content = digest_contents[0]
        assert file_content.path == os.path.normpath(ImportConfig.CONFIG_PATH)
        return file_content.content.decode()

    assert create_config(stdlib=False) == dedent(
        """\
        # import config
        packagefile another/import-path/pkg1=__pkgs__/another_import-path_pkg1/__pkg__.a
        packagefile another/import-path/pkg2=__pkgs__/another_import-path_pkg2/__pkg__.a
        packagefile some/import-path=__pkgs__/some_import-path/__pkg__.a
        importmap foo=bar"""
    )
    assert "packagefile fmt=" in create_config(stdlib=True)
