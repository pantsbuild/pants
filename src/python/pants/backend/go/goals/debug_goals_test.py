# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals import debug_goals
from pants.backend.go.goals.debug_goals import GoExportCgoCodegen, ShowGoPackageAnalysis
from pants.backend.go.target_types import (
    GoModTarget,
    GoPackageTarget,
    GoThirdPartyModuleTarget,
    GoThirdPartyPackageTarget,
)
from pants.backend.go.testutil import gen_module_gomodproxy
from pants.backend.go.util_rules import (
    assembly,
    build_opts,
    build_pkg,
    build_pkg_target,
    cgo,
    first_party_pkg,
    go_mod,
    import_analysis,
    link,
    sdk,
    third_party_pkg,
)
from pants.core.util_rules import distdir
from pants.testutil.rule_runner import RuleRunner

_IMPORT_PATH = "pantsbuild.org/go-sample-for-test"
_VERSION = "v0.0.1"
# The generated `go_third_party_module` target for the sample module (module granularity).
_MODULE_TARGET = f"//:mod#{_IMPORT_PATH}"


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *debug_goals.rules(),
            *assembly.rules(),
            *build_opts.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *cgo.rules(),
            *first_party_pkg.rules(),
            *go_mod.rules(),
            *import_analysis.rules(),
            *link.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            *third_party_pkg.rules(),
            *distdir.rules(),
        ],
        target_types=[
            GoModTarget,
            GoPackageTarget,
            GoThirdPartyPackageTarget,
            GoThirdPartyModuleTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def _write_module(rule_runner: RuleRunner) -> None:
    files = gen_module_gomodproxy(
        _VERSION,
        _IMPORT_PATH,
        (
            (
                "pkg/hello/hello.go",
                dedent(
                    """\
                    package hello

                    import "fmt"

                    func Hello() {
                        fmt.Println("Hello world!")
                    }
                    """
                ),
            ),
        ),
    )
    files.update(
        {
            "go.mod": dedent(
                f"""\
                module example.com/foo
                go 1.16

                require (
                \t{_IMPORT_PATH} {_VERSION}
                )
                """
            ),
            "BUILD": "go_mod(name='mod')\n",
        }
    )
    rule_runner.write_files(files)


def _module_mode_args(rule_runner: RuleRunner) -> list[str]:
    return [
        "--golang-third-party-target-granularity=module",
        f"--golang-subprocess-env-vars=GOPROXY=file://{rule_runner.build_root}/go-mod-proxy",
        "--golang-subprocess-env-vars=GOSUMDB=off",
    ]


def test_show_package_analysis_module_granularity_selects_package_by_import_path(
    rule_runner: RuleRunner,
) -> None:
    _write_module(rule_runner)
    result = rule_runner.run_goal_rule(
        ShowGoPackageAnalysis,
        global_args=_module_mode_args(rule_runner),
        args=[f"--import-paths={_IMPORT_PATH}/pkg/hello", _MODULE_TARGET],
        env_inherit={"PATH"},
    )
    assert result.exit_code == 0
    assert f"import_path='{_IMPORT_PATH}/pkg/hello'" in result.stdout
    assert "name='hello'" in result.stdout


def test_show_package_analysis_module_granularity_missing_import_path_is_graceful(
    rule_runner: RuleRunner,
) -> None:
    _write_module(rule_runner)
    result = rule_runner.run_goal_rule(
        ShowGoPackageAnalysis,
        global_args=_module_mode_args(rule_runner),
        args=[f"--import-paths={_IMPORT_PATH}/does-not-exist", _MODULE_TARGET],
        env_inherit={"PATH"},
    )
    # An import path that is not a real package must be reported, not crash the goal.
    assert result.exit_code == 0
    assert f"No Go package with import path `{_IMPORT_PATH}/does-not-exist`" in result.stdout


def test_export_cgo_codegen_module_granularity_runs(rule_runner: RuleRunner) -> None:
    _write_module(rule_runner)
    # The sample package uses no Cgo, so nothing is exported, but the goal must build the package
    # by import path and complete without crashing under module granularity.
    result = rule_runner.run_goal_rule(
        GoExportCgoCodegen,
        global_args=_module_mode_args(rule_runner),
        args=[f"--import-paths={_IMPORT_PATH}/pkg/hello", _MODULE_TARGET],
        env_inherit={"PATH"},
    )
    assert result.exit_code == 0
