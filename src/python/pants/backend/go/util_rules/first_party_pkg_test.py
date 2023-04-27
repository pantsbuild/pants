# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.target_types import GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    first_party_pkg,
    go_mod,
    link,
    sdk,
    third_party_pkg,
)
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.embedcfg import EmbedConfig
from pants.backend.go.util_rules.first_party_pkg import (
    FallibleFirstPartyPkgAnalysis,
    FallibleFirstPartyPkgDigest,
    FirstPartyPkgAnalysisRequest,
    FirstPartyPkgDigestRequest,
    FirstPartyPkgImportPath,
    FirstPartyPkgImportPathRequest,
)
from pants.core.target_types import ResourcesGeneratorTarget
from pants.engine.addresses import Address
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *go_mod.rules(),
            *first_party_pkg.rules(),
            *sdk.rules(),
            *third_party_pkg.rules(),
            *target_type_rules.rules(),
            *build_pkg.rules(),
            *link.rules(),
            *assembly.rules(),
            QueryRule(FallibleFirstPartyPkgAnalysis, [FirstPartyPkgAnalysisRequest]),
            QueryRule(FallibleFirstPartyPkgDigest, [FirstPartyPkgDigestRequest]),
            QueryRule(FirstPartyPkgImportPath, [FirstPartyPkgImportPathRequest]),
        ],
        target_types=[
            GoModTarget,
            GoPackageTarget,
            ResourcesGeneratorTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


@pytest.mark.parametrize("mod_dir", ("", "src/go/"))
def test_import_path(rule_runner: RuleRunner, mod_dir: str) -> None:
    rule_runner.write_files(
        {
            f"{mod_dir}BUILD": "go_mod(name='mod')\ngo_package(name='pkg')",
            f"{mod_dir}go.mod": "module go.example.com/foo",
            f"{mod_dir}f.go": "",
            f"{mod_dir}dir/f.go": "",
            f"{mod_dir}dir/BUILD": "go_package()",
        }
    )
    info = rule_runner.request(
        FirstPartyPkgImportPath,
        [FirstPartyPkgImportPathRequest(Address(mod_dir, target_name="pkg"))],
    )
    assert info.import_path == "go.example.com/foo"
    assert info.dir_path_rel_to_gomod == ""

    info = rule_runner.request(
        FirstPartyPkgImportPath,
        [FirstPartyPkgImportPathRequest(Address(os.path.join(mod_dir, "dir")))],
    )
    assert info.import_path == "go.example.com/foo/dir"
    assert info.dir_path_rel_to_gomod == "dir"


def test_package_analysis(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod()\n",
            "foo/go.mod": dedent(
                """\
                module go.example.com/foo
                go 1.16
                require github.com/google/uuid v1.3.0
                require (
                    rsc.io/quote v1.5.2
                    golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c // indirect
                    rsc.io/sampler v1.3.0 // indirect
                )
                """
            ),
            "foo/go.sum": dedent(
                """\
                github.com/google/uuid v1.3.0 h1:t6JiXgmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
                github.com/google/uuid v1.3.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c h1:qgOY6WgZOaTkIIMiVjBQcw93ERBE4m30iBm00nkL0i8=
                golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c/go.mod h1:NqM8EUOU14njkJ3fqMW+pc6Ldnwhi/IjpwHt7yyuwOQ=
                rsc.io/quote v1.5.2 h1:w5fcysjrx7yqtD/aO+QwRjYZOKnaM9Uh2b40tElTs3Y=
                rsc.io/quote v1.5.2/go.mod h1:LzX7hefJvL54yjefDEDHNONDjII0t9xZLPXsUe+TKr0=
                rsc.io/sampler v1.3.0 h1:7uVkIFmeBqHfdjD+gZwtXXI+RODJ2Wc4O7MPEh/QiW4=
                rsc.io/sampler v1.3.0/go.mod h1:T1hPZKmBbMNahiBKFy5HrXp6adAjACjK9JXDnKaTXpA=
                """
            ),
            "foo/pkg/foo.go": dedent(
                """\
                package pkg
                import "github.com/google/uuid"
                import "rsc.io/quote"

                func Grok() string {
                    return "Hello World"
                }
                """
            ),
            "foo/pkg/BUILD": "go_package()",
            "foo/cmd/main.go": dedent(
                """\
                package main
                import (
                    "fmt"
                    "go.example.com/foo/pkg"
                )
                func main() {
                    fmt.Printf("%s\n", pkg.Grok())
                }
                """
            ),
            "foo/cmd/bar_test.go": dedent(
                """\
                package main
                import "testing"
                func TestBar(t *testing.T) {}
                """
            ),
            "foo/cmd/BUILD": "go_package()",
        }
    )

    def assert_analysis(
        dir_path: str,
        *,
        imports: list[str],
        test_imports: list[str],
        xtest_imports: list[str],
        go_files: list[str],
        test_files: list[str],
        xtest_files: list[str],
    ) -> None:
        addr = Address(os.path.join("foo", dir_path))
        maybe_analysis = rule_runner.request(
            FallibleFirstPartyPkgAnalysis,
            [FirstPartyPkgAnalysisRequest(addr, build_opts=GoBuildOptions())],
        )
        assert maybe_analysis.analysis is not None
        analysis = maybe_analysis.analysis

        assert analysis.imports == tuple(imports)
        assert analysis.test_imports == tuple(test_imports)
        assert analysis.xtest_imports == tuple(xtest_imports)
        assert analysis.go_files == tuple(go_files)
        assert analysis.test_go_files == tuple(test_files)
        assert analysis.xtest_go_files == tuple(xtest_files)
        assert not analysis.s_files

        assert analysis.minimum_go_version == "1.16"

        assert analysis.embed_patterns == ()
        assert analysis.test_embed_patterns == ()
        assert analysis.xtest_embed_patterns == ()

        maybe_digest = rule_runner.request(
            FallibleFirstPartyPkgDigest,
            [FirstPartyPkgDigestRequest(addr, build_opts=GoBuildOptions())],
        )
        assert maybe_digest.pkg_digest is not None
        pkg_digest = maybe_digest.pkg_digest
        actual_snapshot = rule_runner.request(Snapshot, [pkg_digest.digest])
        expected_snapshot = rule_runner.request(Snapshot, [PathGlobs([f"foo/{dir_path}/*.go"])])
        assert actual_snapshot == expected_snapshot
        assert pkg_digest.embed_config is None
        assert pkg_digest.xtest_embed_config is None
        assert pkg_digest.xtest_embed_config is None

    assert_analysis(
        "pkg",
        imports=["github.com/google/uuid", "rsc.io/quote"],
        test_imports=[],
        xtest_imports=[],
        go_files=["foo.go"],
        test_files=[],
        xtest_files=[],
    )
    assert_analysis(
        "cmd",
        imports=["fmt", "go.example.com/foo/pkg"],
        test_imports=["testing"],
        xtest_imports=[],
        go_files=["main.go"],
        test_files=["bar_test.go"],
        xtest_files=[],
    )


def test_invalid_package(rule_runner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')",
            "go.mod": dedent(
                """\
                module go.example.com/foo
                go 1.17
                """
            ),
            "bad.go": "invalid!!!",
        }
    )
    maybe_analysis = rule_runner.request(
        FallibleFirstPartyPkgAnalysis,
        [FirstPartyPkgAnalysisRequest(Address("", target_name="pkg"), build_opts=GoBuildOptions())],
    )
    assert maybe_analysis.analysis is None
    assert maybe_analysis.exit_code == 1
    assert "bad.go:1:1: expected 'package', found invalid\n" in maybe_analysis.stderr


@pytest.mark.xfail(reason="cgo is ignored")
def test_cgo_not_supported(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')",
            "go.mod": dedent(
                """\
                module go.example.com/foo
                go 1.17
                """
            ),
            "hello.go": dedent(
                """\
                package main

                // int fortytwo()
                // {
                //	    return 42;
                // }
                import "C"
                import "fmt"

                func main() {
                    f := C.intFunc(C.fortytwo)
                    fmt.Println(C.intFunc(C.fortytwo))
                }
                """
            ),
        }
    )
    with engine_error(NotImplementedError):
        rule_runner.request(
            FallibleFirstPartyPkgAnalysis,
            [
                FirstPartyPkgAnalysisRequest(
                    Address("", target_name="pkg"), build_opts=GoBuildOptions()
                )
            ],
        )


def test_embeds_supported(rule_runner: RuleRunner) -> None:
    go_sources = {
        "foo.go": dedent(
            """\
            package foo
            import _ "embed"
            //go:embed grok.txt
            var message
            """
        ),
        "foo_test.go": dedent(
            """\
            package foo
            import _ "embed"
            //go:embed test_grok.txt
            var testMessage
            """
        ),
        "bar_test.go": dedent(
            """\
            package foo_test
            import _ "embed"
            //go:embed xtest_grok.txt
            var testMessage
            """
        ),
    }
    resources = {
        "grok.txt": "This will be embedded in a Go binary.",
        "test_grok.txt": "This will be embedded in a Go binary.",
        "xtest_grok.txt": "This will be embedded in a Go binary.",
    }
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
                go_mod(name='mod')
                go_package(name='pkg', dependencies=[":resources"])
                resources(
                  name="resources",
                  sources=["*.txt"],
                )
                """
            ),
            "go.mod": dedent(
                """\
                module go.example.com/foo
                go 1.17
                """
            ),
            **resources,
            **go_sources,
        }
    )
    maybe_analysis = rule_runner.request(
        FallibleFirstPartyPkgAnalysis,
        [FirstPartyPkgAnalysisRequest(Address("", target_name="pkg"), build_opts=GoBuildOptions())],
    )
    assert maybe_analysis.analysis is not None
    analysis = maybe_analysis.analysis
    assert analysis.embed_patterns == ("grok.txt",)
    assert analysis.test_embed_patterns == ("test_grok.txt",)
    assert analysis.xtest_embed_patterns == ("xtest_grok.txt",)

    maybe_digest = rule_runner.request(
        FallibleFirstPartyPkgDigest,
        [FirstPartyPkgDigestRequest(Address("", target_name="pkg"), build_opts=GoBuildOptions())],
    )
    assert maybe_digest.pkg_digest is not None
    pkg_digest = maybe_digest.pkg_digest
    actual_snapshot = rule_runner.request(Snapshot, [pkg_digest.digest])
    expected_snapshot = rule_runner.make_snapshot(
        {
            **go_sources,
            **resources,
        }
    )
    assert actual_snapshot == expected_snapshot

    assert pkg_digest.embed_config == EmbedConfig(
        {"grok.txt": ["grok.txt"]}, {"grok.txt": "grok.txt"}
    )
    assert pkg_digest.test_embed_config == EmbedConfig(
        {"grok.txt": ["grok.txt"], "test_grok.txt": ["test_grok.txt"]},
        {"grok.txt": "grok.txt", "test_grok.txt": "test_grok.txt"},
    )
    assert pkg_digest.xtest_embed_config == EmbedConfig(
        {"xtest_grok.txt": ["xtest_grok.txt"]}, {"xtest_grok.txt": "xtest_grok.txt"}
    )


def test_missing_embeds(rule_runner: RuleRunner) -> None:
    """Failing to set up embeds should not crash Pants."""
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
                go_mod(name='mod')
                go_package(name='pkg')
                """
            ),
            "go.mod": dedent(
                """\
                module go.example.com/foo
                go 1.17
                """
            ),
            "foo.go": dedent(
                """\
                package foo
                import _ "embed"
                //go:embed fake.txt
                var message
                """
            ),
        }
    )
    maybe_digest = rule_runner.request(
        FallibleFirstPartyPkgDigest,
        [FirstPartyPkgDigestRequest(Address("", target_name="pkg"), build_opts=GoBuildOptions())],
    )
    assert maybe_digest.pkg_digest is None
    assert maybe_digest.exit_code != 0
    assert maybe_digest.stderr is not None
    assert "Failed to find embedded resources: could not embed fake.txt" in maybe_digest.stderr
