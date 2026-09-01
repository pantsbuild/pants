# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.go_sources import load_go_binary
from pants.backend.go.target_types import GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    first_party_pkg,
    go_mod,
    import_analysis,
    import_roots,
    link,
    sdk,
    third_party_pkg,
)
from pants.backend.go.util_rules.import_roots import (
    FirstPartyImportRoots,
    FirstPartyImportRootsRequest,
    _is_nested_module_path,
    _parse_tool_directives,
)
from pants.build_graph.address import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *third_party_pkg.rules(),
            *first_party_pkg.rules(),
            *import_roots.rules(),
            *load_go_binary.rules(),
            *build_pkg.rules(),
            *import_analysis.rules(),
            *link.rules(),
            *assembly.rules(),
            *target_type_rules.rules(),
            *go_mod.rules(),
            QueryRule(FirstPartyImportRoots, [FirstPartyImportRootsRequest]),
        ],
        target_types=[GoModTarget, GoPackageTarget],
    )
    rule_runner.set_options(["--golang-cgo-enabled"], env_inherit={"PATH"})
    return rule_runner


# ------------------------------------------------------------------------------------------------
# `tool` directive parsing (Go 1.24+)
# ------------------------------------------------------------------------------------------------


def test_parse_tool_directives_single_line() -> None:
    go_mod = b"module example.com/m\n\ngo 1.24\n\ntool example.com/cmd/foo\n"
    assert _parse_tool_directives(go_mod) == ("example.com/cmd/foo",)


def test_parse_tool_directives_block() -> None:
    go_mod = dedent(
        """\
        module example.com/m

        go 1.24

        tool (
        \texample.com/cmd/foo
        \texample.com/cmd/bar
        )
        """
    ).encode()
    assert _parse_tool_directives(go_mod) == ("example.com/cmd/foo", "example.com/cmd/bar")


def test_parse_tool_directives_ignores_comments_and_lookalikes() -> None:
    go_mod = dedent(
        """\
        module example.com/toolkit

        go 1.24

        // tool example.com/cmd/commented-out
        require example.com/toolbox v1.0.0

        tool example.com/cmd/real // keep this one
        """
    ).encode()
    # `module example.com/toolkit` and `require example.com/toolbox` both start with "tool" as a
    # substring; neither is a tool directive.
    assert _parse_tool_directives(go_mod) == ("example.com/cmd/real",)


def test_parse_tool_directives_absent() -> None:
    assert _parse_tool_directives(b"module example.com/m\n\ngo 1.21\n") == ()


# ------------------------------------------------------------------------------------------------
# Nested module exclusion
# ------------------------------------------------------------------------------------------------


def test_nested_module_paths_are_excluded() -> None:
    nested = frozenset({"src/go", "src/go/vendored"})
    # The module's own directory never counts as nested against itself.
    assert not _is_nested_module_path("src/go", "src/go", nested)
    assert not _is_nested_module_path("src/go/pkg/util", "src/go", nested)
    # A nested go.mod carves out its whole subtree.
    assert _is_nested_module_path("src/go/vendored", "src/go", nested)
    assert _is_nested_module_path("src/go/vendored/deep/pkg", "src/go", nested)
    # A sibling directory sharing a name prefix is not nested.
    assert not _is_nested_module_path("src/go/vendored_helpers", "src/go", nested)


# ------------------------------------------------------------------------------------------------
# The scan itself
# ------------------------------------------------------------------------------------------------


def _roots(rule_runner: RuleRunner, *, go_mod_path: str = "go.mod") -> set[str]:
    result = rule_runner.request(
        FirstPartyImportRoots,
        [
            FirstPartyImportRootsRequest(
                go_mod_address=Address("", target_name="mod"),
                go_mod_path=go_mod_path,
                cgo_enabled=True,
            )
        ],
    )
    return set(result.import_paths)


def test_scan_finds_imports_the_host_build_would_drop(rule_runner: RuleRunner) -> None:
    """Roots must include build-tag-gated, other-platform and `tools.go` imports.

    Each of these is invisible to a normal constraint-applying analysis, and missing any of them
    means declining to generate a target the user asked for.
    """
    rule_runner.write_files(
        {
            "BUILD": "go_mod(name='mod')\n",
            "go.mod": "module example.com/m\ngo 1.16\n",
            "main.go": dedent(
                """\
                package main

                import "github.com/normal/dep"

                func main() { dep.Do() }
                """
            ),
            "main_test.go": dedent(
                """\
                package main

                import "github.com/only/intests"
                """
            ),
            "plan9.go": dedent(
                """\
                //go:build plan9

                package main

                import "github.com/other/platform"
                """
            ),
            "tools/tools.go": dedent(
                """\
                //go:build tools

                package tools

                import _ "github.com/the/tool"
                """
            ),
        }
    )
    roots = _roots(rule_runner)
    assert "github.com/normal/dep" in roots
    assert "github.com/only/intests" in roots
    assert "github.com/other/platform" in roots
    # The tools directory has no buildable Go sources at all, so the analyzer reports an error for
    # it -- the root must survive that.
    assert "github.com/the/tool" in roots


def test_scan_skips_nested_modules(rule_runner: RuleRunner) -> None:
    """A nested `go.mod` owns its subtree; its imports are not the parent's roots."""
    rule_runner.write_files(
        {
            "BUILD": "go_mod(name='mod')\n",
            "go.mod": "module example.com/m\ngo 1.16\n",
            "main.go": dedent(
                """\
                package main

                import "github.com/parent/dep"

                func main() { dep.Do() }
                """
            ),
            "nested/go.mod": "module example.com/nested\ngo 1.16\n",
            "nested/main.go": dedent(
                """\
                package main

                import "github.com/nested/dep"

                func main() { dep.Do() }
                """
            ),
        }
    )
    roots = _roots(rule_runner)
    assert "github.com/parent/dep" in roots
    assert "github.com/nested/dep" not in roots


def test_scan_includes_tool_directives(rule_runner: RuleRunner) -> None:
    """`tool` directives are roots even though no .go file imports them."""
    rule_runner.write_files(
        {
            "BUILD": "go_mod(name='mod')\n",
            "go.mod": dedent(
                """\
                module example.com/m

                go 1.24

                tool example.com/cmd/generator
                """
            ),
            "main.go": dedent(
                """\
                package main

                func main() {}
                """
            ),
        }
    )
    assert "example.com/cmd/generator" in _roots(rule_runner)
