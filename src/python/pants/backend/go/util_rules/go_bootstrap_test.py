# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pathlib import Path
from textwrap import dedent

from pants.backend.go.util_rules.go_bootstrap import GoBootstrap, compatible_go_version
from pants.backend.go.util_rules.go_bootstrap import rules as go_bootstrap_rules
from pants.backend.go.util_rules.testutil import EXPECTED_VERSION, mock_go_binary
from pants.core.util_rules.testutil import fake_asdf_root, materialize_indices
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def test_expand_search_paths() -> None:
    all_go_versions = [
        f"{EXPECTED_VERSION}.0",
        f"{EXPECTED_VERSION}.1",
        f"{EXPECTED_VERSION}.2",
        f"{EXPECTED_VERSION}.3",
    ]
    asdf_home_versions = [0, 1, 2]
    asdf_local_versions = [2, 1, 3]
    asdf_local_versions_str = " ".join(materialize_indices(all_go_versions, asdf_local_versions))
    rule_runner = RuleRunner(
        rules=[
            *go_bootstrap_rules(),
            QueryRule(GoBootstrap, ()),
        ]
    )
    rule_runner.write_files(
        {
            ".tool-versions": dedent(
                f"""\
                nodejs 16.0.1
                java current
                go-sdk {asdf_local_versions_str}
                rust 1.52.0
                """
            ),
        }
    )
    with fake_asdf_root(
        all_go_versions, asdf_home_versions, asdf_local_versions, tool_name="go-sdk"
    ) as (
        home_dir,
        asdf_dir,
        expected_asdf_paths,
        expected_asdf_home_paths,
        expected_asdf_local_paths,
    ):
        for asdf_path in expected_asdf_paths:
            script = mock_go_binary(
                version_output=f"go version go{EXPECTED_VERSION} darwin/arm64",
                env_output={"GOROOT": "/valid/binary"},
            )
            script_path = Path(asdf_path) / "go"
            script_path.write_text(script)
            script_path.chmod(0o755)

        paths = [
            "/foo",
            "<PATH>",
            "/bar",
            "<ASDF>",
            "<ASDF_LOCAL>",
            "/qux",
        ]
        path_str = ", ".join(f'"{p}"' for p in paths)

        rule_runner.set_options(
            [
                f"--golang-go-search-paths=[{path_str}]",
                f"--golang-minimum-expected-version={EXPECTED_VERSION}",
            ],
            env_inherit={"PATH"},
        )
        rule_runner.set_session_values(
            {
                CompleteEnvironmentVars: CompleteEnvironmentVars(
                    {
                        "HOME": home_dir,
                        "PATH": "/env/path1:/env/path2",
                        "ASDF_DATA_DIR": asdf_dir,
                    }
                ),
            }
        )
        go_bootstrap = rule_runner.request(GoBootstrap, ())

    expected = (
        "/foo",
        "/env/path1",
        "/env/path2",
        "/bar",
        *expected_asdf_home_paths,
        *expected_asdf_local_paths,
        "/qux",
    )
    assert expected == go_bootstrap.go_search_paths


def test_compatible_go_version() -> None:
    def check(version: str, expected: bool) -> None:
        assert compatible_go_version(compiler_version="1.15", target_version=version) is expected

    for v in range(16):
        check(f"1.{v}", True)
    for v in range(17, 40):
        check(f"1.{v}", False)
    for v in range(2, 4):
        check(f"{v}.0", False)
