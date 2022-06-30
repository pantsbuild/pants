# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import io
import json
import zipfile
from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals.test import GoTestFieldSet
from pants.backend.go.goals.test import rules as _test_rules
from pants.backend.go.target_types import GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    link,
    sdk,
    tests_analysis,
    third_party_pkg,
)
from pants.backend.go.util_rules.embedcfg import EmbedConfig
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult, get_filtered_environment
from pants.core.target_types import ResourceTarget
from pants.core.util_rules import source_files
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *_test_rules(),
            *assembly.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *first_party_pkg.rules(),
            *go_mod.rules(),
            *link.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            *tests_analysis.rules(),
            *third_party_pkg.rules(),
            *source_files.rules(),
            get_filtered_environment,
            QueryRule(TestResult, [GoTestFieldSet]),
        ],
        target_types=[GoModTarget, GoPackageTarget, ResourceTarget],
    )
    rule_runner.set_options(["--go-test-args=-v -bench=."], env_inherit={"PATH"})
    return rule_runner


def test_merge_embedcfg() -> None:
    x = EmbedConfig(
        patterns={
            "*.go": ["foo.go", "bar.go"],
            "*.x": ["only_in_x"],
        },
        files={"foo.go": "path/to/foo.go", "bar.go": "path/to/bar.go", "only_in_x": "only_in_x"},
    )
    y = EmbedConfig(
        patterns={
            "*.go": ["foo.go", "bar.go"],
            "*.y": ["only_in_y"],
        },
        files={"foo.go": "path/to/foo.go", "bar.go": "path/to/bar.go", "only_in_y": "only_in_y"},
    )
    merged = x.merge(y)
    assert merged == EmbedConfig(
        patterns={
            "*.go": ["foo.go", "bar.go"],
            "*.x": ["only_in_x"],
            "*.y": ["only_in_y"],
        },
        files={
            "foo.go": "path/to/foo.go",
            "bar.go": "path/to/bar.go",
            "only_in_x": "only_in_x",
            "only_in_y": "only_in_y",
        },
    )

    a = EmbedConfig(
        patterns={
            "*.go": ["foo.go"],
        },
        files={"foo.go": "path/to/foo.go"},
    )
    b = EmbedConfig(
        patterns={
            "*.go": ["bar.go"],
        },
        files={"bar.go": "path/to/bar.go"},
    )
    with pytest.raises(AssertionError):
        _ = a.merge(b)


def test_embed_in_source_code(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
                go_mod(name='mod')
                go_package(name='pkg', dependencies=[":hello"])
                resource(name='hello', source='hello.txt')
                """
            ),
            "go.mod": dedent(
                """\
                module go.example.com/foo
                go 1.17
                """
            ),
            "hello.txt": "hello",
            "foo.go": dedent(
                """\
                package foo
                import _ "embed"
                //go:embed hello.txt
                var message string
                """
            ),
            "foo_test.go": dedent(
                """\
                package foo
                import "testing"

                func TestFoo(t *testing.T) {
                  if message != "hello" {
                    t.Fatalf("message mismatch: want=%s; got=%s", "hello", message)
                  }
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0


def test_embed_in_internal_test(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
                go_mod(name='mod')
                go_package(name='pkg', dependencies=[":hello"])
                resource(name='hello', source='hello.txt')
                """
            ),
            "go.mod": dedent(
                """\
                module go.example.com/foo
                go 1.17
                """
            ),
            "hello.txt": "hello",
            "foo.go": dedent(
                """\
                package foo
                """
            ),
            "foo_test.go": dedent(
                """\
                package foo
                import (
                  _ "embed"
                  "testing"
                )
                //go:embed hello.txt
                var testMessage string

                func TestFoo(t *testing.T) {
                  if testMessage != "hello" {
                    t.Fatalf("testMessage mismatch: want=%s; got=%s", "hello", testMessage)
                  }
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0


def test_embed_in_external_test(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
                go_mod(name='mod')
                go_package(name='pkg', dependencies=[":hello"])
                resource(name='hello', source='hello.txt')
                """
            ),
            "go.mod": dedent(
                """\
                module go.example.com/foo
                go 1.17
                """
            ),
            "hello.txt": "hello",
            "foo.go": dedent(
                """\
                package foo
                """
            ),
            "bar_test.go": dedent(
                """\
                package foo_test
                import (
                  _ "embed"
                  "testing"
                )
                //go:embed hello.txt
                var testMessage string

                func TestBar(t *testing.T) {
                  if testMessage != "hello" {
                    t.Fatalf("testMessage mismatch: want=%s; got=%s", "hello", testMessage)
                  }
                }
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0


def test_third_party_package_embed(rule_runner: RuleRunner) -> None:
    # Build the zip file and other content needed to simulate a third-party module.
    import_path = "pantsbuild.org/go-embed-sample-for-test"
    version = "v0.0.1"
    go_mod_content = dedent(
        f"""\
        module {import_path}
        go 1.16
        """
    )
    embed_content = "This message comes from an embedded file."
    mod_zip_bytes = io.BytesIO()
    with zipfile.ZipFile(mod_zip_bytes, "w") as mod_zip:
        prefix = f"{import_path}@{version}"
        mod_zip.writestr(f"{prefix}/go.mod", go_mod_content)
        mod_zip.writestr(
            f"{prefix}/pkg/message.go",
            dedent(
                """\
            package pkg
            import _ "embed"
            //go:embed message.txt
            var Message string
            """
            ),
        )
        mod_zip.writestr(f"{prefix}/pkg/message.txt", embed_content)

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
                go_mod(name='mod')
                go_package(name='pkg')
                """
            ),
            "go.mod": dedent(
                f"""\
                module go.example.com/foo
                go 1.17

                require (
                \t{import_path} {version}
                )
                """
            ),
            # Note: At least one Go file is necessary due to bug in Go backend even if package is only for tests.
            "foo.go": "package foo\n",
            "foo_test.go": dedent(
                f"""\
                package foo_test
                import (
                  "testing"
                  "{import_path}/pkg"
                )

                func TestFoo(t *testing.T) {{
                  if pkg.Message != "{embed_content}" {{
                    t.Fatalf("third-party embedded content did not match")
                  }}
                }}
                """
            ),
            # Setup the third-party dependency as a custom Go module proxy site.
            # See https://go.dev/ref/mod#goproxy-protocol for details.
            f"go-mod-proxy/{import_path}/@v/list": f"{version}\n",
            f"go-mod-proxy/{import_path}/@v/{version}.info": json.dumps(
                {
                    "Version": version,
                    "Time": "2022-01-01T01:00:00Z",
                }
            ),
            f"go-mod-proxy/{import_path}/@v/{version}.mod": go_mod_content,
            f"go-mod-proxy/{import_path}/@v/{version}.zip": mod_zip_bytes.getvalue(),
        }
    )

    rule_runner.set_options(
        [
            "--go-test-args=-v -bench=.",
            f"--golang-subprocess-env-vars=GOPROXY=file://{rule_runner.build_root}/go-mod-proxy",
            "--golang-subprocess-env-vars=GOSUMDB=off",
        ],
        env_inherit={"PATH"},
    )

    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0
