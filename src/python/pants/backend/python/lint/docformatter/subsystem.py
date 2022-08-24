# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.goals import lockfile
from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    GeneratePythonToolLockfileSentinel,
)
from pants.backend.python.subsystems.python_tool_base import ExportToolOption, PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption
from pants.util.docutil import git_url


class Docformatter(PythonToolBase):
    options_scope = "docformatter"
    name = "docformatter"
    help = "The Python docformatter tool (https://github.com/myint/docformatter)."

    default_version = "docformatter>=1.4,<1.5"
    default_main = ConsoleScript("docformatter")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.docformatter", "docformatter.lock")
    default_lockfile_path = "src/python/pants/backend/python/lint/docformatter/docformatter.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--wrap-summaries=100 --pre-summary-newline")
    export = ExportToolOption()


class DocformatterLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = Docformatter.options_scope


@rule
def setup_lockfile_request(
    _: DocformatterLockfileSentinel, docformatter: Docformatter
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(docformatter)


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
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, DocformatterLockfileSentinel),
        UnionRule(ExportPythonToolSentinel, DocformatterExportSentinel),
    )
