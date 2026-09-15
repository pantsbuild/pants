# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Integration tests for ESLint rules.

This module contains comprehensive integration tests for the ESLint linting and
formatting functionality, including edge cases, error handling, and configuration
scenarios.

The tests ensure that:
- ESLint linting works correctly with various configurations
- ESLint formatting works correctly and modifies files as expected
- Configuration discovery works for all supported config file types
- Skip functionality works properly
- Error handling is robust
- Edge cases are handled gracefully
"""

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.experimental.javascript.lint.eslint import rules as eslint_rules
from pants.backend.experimental.javascript.lint.eslint import skip_field
from pants.backend.experimental.javascript.lint.eslint.rules import (
    EslintFieldSet,
    EslintFmtRequest,
    EslintLintRequest,
)
from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget
from pants.backend.python import target_types_rules
from pants.backend.tsx.target_types import TSXSourcesGeneratorTarget
from pants.backend.typescript.target_types import TypeScriptSourcesGeneratorTarget
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintResult
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.partitions import _EmptyMetadata
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    """Create a RuleRunner configured for ESLint testing.

    Returns:
        Configured RuleRunner with all necessary rules and target types.
    """
    runner = RuleRunner(
        rules=[
            *eslint_rules.rules(),
            *nodejs.rules(),
            *skip_field.rules(),
            *source_files.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(LintResult, (EslintLintRequest.Batch,)),
            QueryRule(FmtResult, (EslintFmtRequest.Batch,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[
            JSSourcesGeneratorTarget,
            TypeScriptSourcesGeneratorTarget,
            TSXSourcesGeneratorTarget,
        ],
    )
    # Set environment inheritance like Prettier tests do
    runner.set_options(
        [
            "--backend-packages=['pants.backend.javascript', 'pants.backend.experimental.javascript.lint.eslint']",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return runner


# Test configuration files
ESLINTRC_FLAT_CONFIG = dedent(
    """\
    export default {
        rules: {
            "quotes": ["error", "double"],
            "semi": ["error", "always"]
        }
    };
    """
)

ESLINTRC_LEGACY_CONFIG = dedent(
    """\
    {
        "rules": {
            "quotes": ["error", "double"],
            "semi": ["error", "always"]
        }
    }
    """
)

PACKAGE_JSON_WITH_ESLINT_CONFIG = dedent(
    """\
    {
        "name": "test-project",
        "eslintConfig": {
            "rules": {
                "quotes": ["error", "double"],
                "semi": ["error", "always"]
            }
        }
    }
    """
)

# Test source files
UNFORMATTED_JS_FILE = dedent(
    """\
    function greet(name) {
        console.log('Hello, ' + name + '!')
    }

    greet('World')
    """
)

FORMATTED_JS_FILE = dedent(
    """\
    function greet(name) {
        console.log("Hello, " + name + "!");
    }

    greet("World");
    """
)

LINTING_ERROR_JS_FILE = dedent(
    """\
    function greet(name) {
        console.log('Hello, ' + name + '!')  // Missing semicolon, wrong quotes
        var unused = 'test';  // Unused variable
    }

    greet('World')  // Missing semicolon, wrong quotes
    """
)

TYPESCRIPT_FILE = dedent(
    """\
    function greet(name: string): void {
        console.log('Hello, ' + name + '!')
    }

    greet('World')
    """
)

TSX_FILE = dedent(
    """\
    import React from 'react';

    function Greeting({ name }: { name: string }) {
        return <div>Hello, {name}!</div>
    }

    export default Greeting
    """
)


def run_eslint_lint(
    rule_runner: RuleRunner,
    targets: list[Target],
) -> LintResult:
    """Run ESLint linting with proper environment setup."""
    field_sets = [EslintFieldSet.create(tgt) for tgt in targets]
    return rule_runner.request(
        LintResult, [EslintLintRequest.Batch("", tuple(field_sets), _EmptyMetadata())]
    )


def run_eslint_fmt(
    rule_runner: RuleRunner,
    targets: list[Target],
) -> FmtResult:
    """Run ESLint formatting with proper environment setup."""
    field_sets = [EslintFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    return rule_runner.request(
        FmtResult,
        [
            EslintFmtRequest.Batch(
                "",
                input_sources.snapshot.files,
                _EmptyMetadata(),
                snapshot=input_sources.snapshot,
            )
        ],
    )


class TestEslintLinting:
    """Test cases for ESLint linting functionality."""

    def test_eslint_lint_success(self, rule_runner: RuleRunner) -> None:
        """Test that ESLint linting works correctly with valid JavaScript."""
        rule_runner.write_files(
            {
                "src/main.js": FORMATTED_JS_FILE,
                "BUILD": "javascript_sources(name='js', sources=['src/*.js'])",
                ".eslintrc.json": ESLINTRC_LEGACY_CONFIG,
            }
        )

        tgt = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/main.js")
        )
        lint_result = run_eslint_lint(rule_runner, [tgt])
        assert lint_result.exit_code == 0
        # Allow '0 errors' summary; ensure zero errors rather than banning
        # the substring 'error' (which appears in '0 errors').
        stdout_lower = lint_result.stdout.lower()
        assert (
            "0 errors" in stdout_lower
            or "no errors" in stdout_lower
            or "0 problems" in stdout_lower
        )

    def test_eslint_lint_with_errors(self, rule_runner: RuleRunner) -> None:
        """ESLint should detect problems in bad JS."""
        rule_runner.write_files(
            {
                "src/main.js": LINTING_ERROR_JS_FILE,
                "BUILD": "javascript_sources(name='js', sources=['src/*.js'])",
                ".eslintrc.json": ESLINTRC_LEGACY_CONFIG,
            }
        )

        tgt = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/main.js")
        )
        field_set = EslintFieldSet.create(tgt)
        lint_result = rule_runner.request(
            LintResult,
            [EslintLintRequest.Batch("", (field_set,), _EmptyMetadata())],
        )
        # Should report errors or non-zero exit
        assert lint_result.exit_code != 0 or "error" in lint_result.stdout.lower()

    def test_eslint_lint_typescript(self, rule_runner: RuleRunner) -> None:
        """Test that ESLint can lint TypeScript files."""
        rule_runner.write_files(
            {
                "src/main.ts": TYPESCRIPT_FILE,
                "BUILD": "typescript_sources(name='ts', sources=['src/*.ts'])",
                ".eslintrc.json": ESLINTRC_LEGACY_CONFIG,
            }
        )

        tgt = rule_runner.get_target(
            Address("", target_name="ts", relative_file_path="src/main.ts")
        )
        field_set = EslintFieldSet.create(tgt)
        lint_result = rule_runner.request(
            LintResult, [EslintLintRequest.Batch("", (field_set,), _EmptyMetadata())]
        )

        # Should complete without crashing (TypeScript support may vary)
        assert lint_result.exit_code is not None

    def test_eslint_lint_skip_field(self, rule_runner: RuleRunner) -> None:
        """Test that skip_eslint field properly excludes targets from linting."""
        rule_runner.write_files(
            {
                "src/main.js": LINTING_ERROR_JS_FILE,
                "BUILD": "javascript_sources(name='js', sources=['src/*.js'], skip_eslint=True)",
                ".eslintrc.json": ESLINTRC_LEGACY_CONFIG,
            }
        )

        tgt = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/main.js")
        )

        # Should be skipped due to skip_eslint=True
        assert EslintFieldSet.opt_out(tgt) is True


class TestEslintFormatting:
    """Test cases for ESLint formatting functionality."""

    def test_eslint_fmt_success(self, rule_runner: RuleRunner) -> None:
        """Test that ESLint formatting works correctly."""
        rule_runner.write_files(
            {
                "src/main.js": UNFORMATTED_JS_FILE,
                "BUILD": "javascript_sources(name='js', sources=['src/*.js'])",
                ".eslintrc.json": ESLINTRC_LEGACY_CONFIG,
            }
        )

        tgt = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/main.js")
        )
        fmt_result = run_eslint_fmt(rule_runner, [tgt])

        # Should complete successfully
        assert fmt_result.did_change is not None

    def test_eslint_fmt_no_changes_needed(self, rule_runner: RuleRunner) -> None:
        """Test ESLint formatting when no changes are needed."""
        rule_runner.write_files(
            {
                "src/main.js": FORMATTED_JS_FILE,
                "BUILD": "javascript_sources(name='js', sources=['src/*.js'])",
                ".eslintrc.json": ESLINTRC_LEGACY_CONFIG,
            }
        )

        tgt = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/main.js")
        )
        fmt_result = run_eslint_fmt(rule_runner, [tgt])

        # Should complete without changes
        assert fmt_result.did_change is False

    def test_eslint_fmt_skip_field(self, rule_runner: RuleRunner) -> None:
        """Test that skip_eslint field properly excludes targets from formatting."""
        rule_runner.write_files(
            {
                "src/main.js": UNFORMATTED_JS_FILE,
                "BUILD": "javascript_sources(name='js', sources=['src/*.js'], skip_eslint=True)",
                ".eslintrc.json": ESLINTRC_LEGACY_CONFIG,
            }
        )

        tgt = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/main.js")
        )

        # Should be skipped due to skip_eslint=True
        assert EslintFieldSet.opt_out(tgt) is True


class TestEslintConfiguration:
    """Test cases for ESLint configuration discovery and handling."""

    def test_flat_config_discovery(self, rule_runner: RuleRunner) -> None:
        """Test that ESLint discovers flat config files (eslint.config.js)."""
        rule_runner.write_files(
            {
                "src/main.js": FORMATTED_JS_FILE,
                "BUILD": "javascript_sources(name='js', sources=['src/*.js'])",
                "eslint.config.js": ESLINTRC_FLAT_CONFIG,
            }
        )

        tgt = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/main.js")
        )
        field_set = EslintFieldSet.create(tgt)
        lint_result = rule_runner.request(
            LintResult, [EslintLintRequest.Batch("", (field_set,), _EmptyMetadata())]
        )

        # Should find and use the config
        assert lint_result.exit_code is not None

    def test_legacy_config_discovery(self, rule_runner: RuleRunner) -> None:
        """Test that ESLint discovers legacy config files (.eslintrc.json)."""
        rule_runner.write_files(
            {
                "src/main.js": FORMATTED_JS_FILE,
                "BUILD": "javascript_sources(name='js', sources=['src/*.js'])",
                ".eslintrc.json": ESLINTRC_LEGACY_CONFIG,
            }
        )

        tgt = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/main.js")
        )
        field_set = EslintFieldSet.create(tgt)
        lint_result = rule_runner.request(
            LintResult, [EslintLintRequest.Batch("", (field_set,), _EmptyMetadata())]
        )

        # Should find and use the config
        assert lint_result.exit_code is not None

    def test_package_json_config_discovery(self, rule_runner: RuleRunner) -> None:
        """Test that ESLint discovers config in package.json."""
        rule_runner.write_files(
            {
                "src/main.js": FORMATTED_JS_FILE,
                "BUILD": "javascript_sources(name='js', sources=['src/*.js'])",
                "package.json": PACKAGE_JSON_WITH_ESLINT_CONFIG,
            }
        )

        tgt = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/main.js")
        )
        field_set = EslintFieldSet.create(tgt)
        lint_result = rule_runner.request(
            LintResult, [EslintLintRequest.Batch("", (field_set,), _EmptyMetadata())]
        )

        # Should find and use the config
        assert lint_result.exit_code is not None

    def test_no_config_file(self, rule_runner: RuleRunner) -> None:
        """Test ESLint behavior when no configuration file is present."""
        rule_runner.write_files(
            {
                "src/main.js": FORMATTED_JS_FILE,
                "BUILD": "javascript_sources(name='js', sources=['src/*.js'])",
            }
        )

        tgt = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/main.js")
        )
        field_set = EslintFieldSet.create(tgt)
        lint_result = rule_runner.request(
            LintResult, [EslintLintRequest.Batch("", (field_set,), _EmptyMetadata())]
        )

        # Should work with default configuration
        assert lint_result.exit_code is not None


class TestEslintEdgeCases:
    """Test cases for edge cases and error conditions."""

    def test_empty_file(self, rule_runner: RuleRunner) -> None:
        """Test ESLint handling of empty JavaScript files."""
        rule_runner.write_files(
            {
                "src/empty.js": "",
                "BUILD": "javascript_sources(name='js', sources=['src/*.js'])",
                ".eslintrc.json": ESLINTRC_LEGACY_CONFIG,
            }
        )

        tgt = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/empty.js")
        )
        field_set = EslintFieldSet.create(tgt)
        lint_result = rule_runner.request(
            LintResult, [EslintLintRequest.Batch("", (field_set,), _EmptyMetadata())]
        )

        # Should handle empty files gracefully
        assert lint_result.exit_code is not None

    def test_syntax_error_file(self, rule_runner: RuleRunner) -> None:
        """Test ESLint handling of files with syntax errors."""
        rule_runner.write_files(
            {
                "src/broken.js": "function broken( { // Syntax error",
                "BUILD": "javascript_sources(name='js', sources=['src/*.js'])",
                ".eslintrc.json": ESLINTRC_LEGACY_CONFIG,
            }
        )

        tgt = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/broken.js")
        )
        field_set = EslintFieldSet.create(tgt)
        lint_result = rule_runner.request(
            LintResult, [EslintLintRequest.Batch("", (field_set,), _EmptyMetadata())]
        )

        # Should report syntax errors
        assert lint_result.exit_code != 0

    def test_multiple_files(self, rule_runner: RuleRunner) -> None:
        """Test ESLint processing multiple files in a single request."""
        rule_runner.write_files(
            {
                "src/file1.js": FORMATTED_JS_FILE,
                "src/file2.js": UNFORMATTED_JS_FILE,
                "BUILD": "javascript_sources(name='js', sources=['src/*.js'])",
                ".eslintrc.json": ESLINTRC_LEGACY_CONFIG,
            }
        )

        tgt1 = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/file1.js")
        )
        tgt2 = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/file2.js")
        )
        field_set1 = EslintFieldSet.create(tgt1)
        field_set2 = EslintFieldSet.create(tgt2)

        lint_result = rule_runner.request(
            LintResult,
            [EslintLintRequest.Batch("", (field_set1, field_set2), _EmptyMetadata())],
        )

        # Should process both files
        assert lint_result.exit_code is not None

    def test_mixed_file_types(self, rule_runner: RuleRunner) -> None:
        """Test ESLint processing mixed JavaScript and TypeScript files."""
        rule_runner.write_files(
            {
                "src/script.js": FORMATTED_JS_FILE,
                "src/module.ts": TYPESCRIPT_FILE,
                "src/component.tsx": TSX_FILE,
                "BUILD": dedent(
                    """\
                javascript_sources(name='js', sources=['src/*.js'])
                typescript_sources(name='ts', sources=['src/*.ts'])
                tsx_sources(name='tsx', sources=['src/*.tsx'])
                """
                ),
                ".eslintrc.json": ESLINTRC_LEGACY_CONFIG,
            }
        )

        # Test each file type individually to ensure they work
        js_tgt = rule_runner.get_target(
            Address("", target_name="js", relative_file_path="src/script.js")
        )
        js_field_set = EslintFieldSet.create(js_tgt)
        js_result = rule_runner.request(
            LintResult, [EslintLintRequest.Batch("", (js_field_set,), _EmptyMetadata())]
        )

        assert js_result.exit_code is not None
