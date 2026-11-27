# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""ESLint subsystem for JavaScript and TypeScript linting & formatting.

This module provides the ESLint subsystem implementation for the Pants
build system, enabling linting and formatting of JavaScript and TypeScript
code using ESLint.

ESLint is a static code analysis tool for identifying problematic patterns
found in JavaScript code. It was originally created by Nicholas C. Zakas in
2013.

Website: https://eslint.org/
License: MIT License
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar

from pants.backend.experimental.javascript.lint.eslint.skip_field import SkipEslintField
from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolBase
from pants.backend.javascript.target_types import JSRuntimeSourceField
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import Rule, collect_rules
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.option.option_types import (
    ArgsListOption,
    BoolOption,
    FileOption,
    SkipOption,
    StrListOption,
)
from pants.util.strutil import help_text, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EslintFieldSet(FieldSet):
    """FieldSet for ESLint operations on JavaScript/TypeScript targets.

    This class represents a set of fields that ESLint can operate on,
    specifically JavaScript runtime source files (which includes TypeScript).

    Attributes:
        required_fields: Tuple of field types required for ESLint operations.
    sources: JavaScript runtime source field containing the files
    to process.
    """

    required_fields: ClassVar[tuple[type, ...]] = (JSRuntimeSourceField,)
    sources: JSRuntimeSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipEslintField).value


class EslintSubsystem(NodeJSToolBase):
    """ESLint subsystem for JavaScript and TypeScript linting and formatting."""

    options_scope = "eslint"
    name = "ESLint"
    help = help_text(
        """
        The ESLint utility for linting and formatting JS/TS code
        (https://eslint.org/).

        ESLint is a static code analysis tool for identifying problematic
        patterns found in JavaScript code. It was originally created by
        Nicholas C. Zakas in 2013.
        """
    )

    default_version = "eslint@8.57.0"

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--max-warnings=0 --cache")

    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to an ESLint config file (flat or legacy), e.g.
            `eslint.config.js` or
            `.eslintrc.cjs` (https://eslint.org/docs/latest/use/configure/).

            Setting this option will disable
            `[{cls.options_scope}].config_discovery`. Use
            this option if the config is located in a non-standard location.
            """
        ),
    )

    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include any relevant ESLint config files
            during runs.

            Use `[{cls.options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )

    extra_dev_dependencies = StrListOption(
        default=[],
        advanced=True,
        help=lambda cls: softwrap(
            """
            Additional npm devDependencies to make available when invoking
            ESLint
            (e.g. `@typescript-eslint/parser@^6.0.0`,
            `@typescript-eslint/eslint-plugin@^6.0.0`).

            These will be installed into the tool sandbox once per unique
            option
            fingerprint (avoiding per-run network installs) and replace the
            previous ad-hoc TypeScript support path.
            """
        ),
    )

    json_output = BoolOption(
        default=False,
        advanced=True,
        help=lambda cls: softwrap(
            """
            If true, Pants will invoke ESLint with `--format json` (unless a
            `--format` argument is already supplied) and parse the results to
            prepend a concise summary (counts by severity and top offending
            files) to the reported stdout.

            Disable if you supply a custom formatter via `--eslint-args`.
            """
        ),
    )

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        """ESLint will use the closest configuration file to the file currently being linted, so add
        all of them.

        In the event of multiple configuration files, ESLint has an order of
        precedence specified at: https://eslint.org/docs/latest/use/configure/configuration-files#configuration-file-resolution.
        """
        # Flat config files (ESLint 9.0+)
        flat_configs = [f"eslint.config{ext}" for ext in [".js", ".mjs", ".cjs"]]

        # Legacy config files (ESLint < 9.0)
        legacy_configs = [
            f".eslintrc{ext}"
            for ext in [
                "",
                ".js",
                ".cjs",
                ".yaml",
                ".yml",
                ".json",
            ]
        ]

        # Package.json can contain eslintConfig section
        package_json_candidates = {
            os.path.join(d, "package.json"): b'"eslintConfig"' for d in ("", *dirs)
        }

        all_configs = flat_configs + legacy_configs + ["package.json"]
        check_existence = [os.path.join(d, config) for config in all_configs for d in ("", *dirs)]

        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=check_existence,
            check_content=package_json_candidates,
        )


def rules() -> Iterable[Rule | UnionRule]:
    """Return rules for the ESLint subsystem.

    Returns:
        Rules for the ESLint subsystem and exportable tool registration.
    """
    return (
        *collect_rules(),
        UnionRule(ExportableTool, EslintSubsystem),
    )
