# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, BoolOption
from pants.util.docutil import bin_name, git_url


class Docformatter(PythonToolBase):
    options_scope = "docformatter"
    help = "The Python docformatter tool (https://github.com/myint/docformatter)."

    default_version = "docformatter>=1.4,<1.5"
    default_main = ConsoleScript("docformatter")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.docformatter", "lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/python/lint/docformatter/lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    skip = BoolOption(
        "--skip",
        default=False,
        help=f"Don't use docformatter when running `{bin_name()} fmt` and `{bin_name()} lint`.",
    )
    args = ArgsListOption(
        help=lambda cls: (
            "Arguments to pass directly to docformatter, e.g. "
            f'`--{cls.options_scope}-args="--wrap-summaries=100 --pre-summary-newline"`.'
        ),
    )


class DocformatterLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = Docformatter.options_scope


@rule
def setup_lockfile_request(
    _: DocformatterLockfileSentinel, docformatter: Docformatter
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(docformatter)


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, DocformatterLockfileSentinel),
    )
