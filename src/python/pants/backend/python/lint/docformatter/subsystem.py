# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.goals.resolves import ExportableTool
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption


class Docformatter(PythonToolBase):
    options_scope = "docformatter"
    name = "docformatter"
    help_short = "The Python docformatter tool (https://github.com/myint/docformatter)."

    default_main = ConsoleScript("docformatter")
    # Upper bound requirement set because there is a bug in docformatter 1.7.1 that causes issues
    # with Sphinx-style :param tags.
    # https://github.com/PyCQA/docformatter/issues/264
    default_requirements = ["docformatter==1.7.0"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.lint.docformatter", "docformatter.lock")

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--wrap-summaries=100 --pre-summary-newline")


def rules():
    return [
        *collect_rules(),
        UnionRule(ExportableTool, Docformatter),
    ]
