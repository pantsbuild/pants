# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.subsystems.python_tool_base import (
    ExportToolOption,
    LockfileRules,
    PythonToolBase,
)
from pants.backend.python.target_types import ConsoleScript
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import Dependencies, FieldSet, SingleSourceField, Target
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, BoolOption, SkipOption
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class SemgrepFieldSet(FieldSet):
    required_fields = (SingleSourceField, Dependencies)
    source: SingleSourceField
    dependencies: Dependencies

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        # FIXME: global skip_semgrep field?
        return False


class SemgrepSubsystem(PythonToolBase):
    name = "Semgrep"
    options_scope = "semgrep"
    help = "Lightweight static analysis for many languages. Find bug variants with patterns that look like source code. (https://semgrep.dev/)"

    default_version = "semgrep>=1.20.0,<2"
    default_main = ConsoleScript("semgrep")
    default_requirements = [default_version]

    register_interpreter_constraints = True

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.tools.semgrep", "semgrep.lock")
    lockfile_rules_type = LockfileRules.SIMPLE

    export = ExportToolOption()

    args = ArgsListOption(
        example="--verbose",
        default=["--quiet"],
        extra_help="This includes --quiet by default to reduce the volume of output.",
    )

    skip = SkipOption("lint")

    tailor_rule_targets = BoolOption(
        default=True,
        help="If true, add `semgrep_rule_sources` targets with the `tailor` goal.",
        advanced=True,
    )

    force = BoolOption(
        default=False,
        help=softwrap(
            """\
            If true, semgrep is always run, even if the input files haven't changed. This can be
            used to run cloud rulesets like `pants lint --semgrep-force
            --semgrep-args='--config=p/python' ::`. Without `--semgrep-force`, using the cloud
            rulesets may give inconsistent results on different machines, due to caching, because
            the rulesets may change.
            """
        ),
        advanced=True,
    )


class SemgrepExportSentinel(ExportPythonToolSentinel):
    pass


@rule
def semgrep_export(_: SemgrepExportSentinel, semgrep: SemgrepSubsystem) -> ExportPythonTool:
    if not semgrep.export:
        return ExportPythonTool(resolve_name=semgrep.options_scope, pex_request=None)
    return ExportPythonTool(
        resolve_name=semgrep.options_scope, pex_request=semgrep.to_pex_request()
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        UnionRule(ExportPythonToolSentinel, SemgrepExportSentinel),
    )
