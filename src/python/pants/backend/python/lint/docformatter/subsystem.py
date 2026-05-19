# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.goals.resolves import ExportableTool
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption

# pants: infer-dep(docformatter.lock*)


class Docformatter(PythonToolBase):
    options_scope = "docformatter"
    name = "docformatter"
    help_short = "The Python docformatter tool (https://github.com/myint/docformatter)."

    # As of 4/2026 docformatter doesn't work on python 3.14 due to an issue with its untokenize dep.
    default_interpreter_constraints = ["CPython>=3.9,<3.14"]
    default_main = ConsoleScript("docformatter")
    default_requirements = ["docformatter>=1.7.0,<1.8"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.lint.docformatter", "docformatter.lock")

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--wrap-summaries=100 --pre-summary-newline")


def rules():
    return [
        *collect_rules(),
        UnionRule(ExportableTool, Docformatter),
    ]
