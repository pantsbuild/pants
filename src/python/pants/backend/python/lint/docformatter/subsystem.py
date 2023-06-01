# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.subsystems.python_tool_base import (
    ExportToolOption,
    LockfileRules,
    PythonToolBase,
)
from pants.backend.python.target_types import ConsoleScript
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption


class Docformatter(PythonToolBase):
    options_scope = "docformatter"
    name = "docformatter"
    help = "The Python docformatter tool (https://github.com/myint/docformatter)."

    default_version = "docformatter>=1.4,<1.5"
    default_main = ConsoleScript("docformatter")
    default_requirements = ["docformatter>=1.4,<1.6"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.lint.docformatter", "docformatter.lock")
    lockfile_rules_type = LockfileRules.SIMPLE

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--wrap-summaries=100 --pre-summary-newline")
    export = ExportToolOption()


class DocformatterExportSentinel(ExportPythonToolSentinel):
    pass


@rule
def docformatter_export(
    _: DocformatterExportSentinel, docformatter: Docformatter
) -> ExportPythonTool:
    if not docformatter.export:
        return ExportPythonTool(resolve_name=docformatter.options_scope, pex_request=None)
    return ExportPythonTool(
        resolve_name=docformatter.options_scope, pex_request=docformatter.to_pex_request()
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(ExportPythonToolSentinel, DocformatterExportSentinel),
    )
