# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple, cast

from pants.backend.python.goals.lockfile import PythonLockfileRequest, PythonToolLockfileSentinel
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.custom_types import shell_str
from pants.util.docutil import git_url


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

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=(
                f"Don't use docformatter when running `{register.bootstrap.pants_bin_name} fmt` "
                f"and `{register.bootstrap.pants_bin_name} lint`."
            ),
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to docformatter, e.g. "
                f'`--{cls.options_scope}-args="--wrap-summaries=100 --pre-summary-newline"`.'
            ),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> Tuple[str, ...]:
        return tuple(self.options.args)


class DocformatterLockfileSentinel(PythonToolLockfileSentinel):
    options_scope = Docformatter.options_scope


@rule
def setup_lockfile_request(
    _: DocformatterLockfileSentinel, docformatter: Docformatter
) -> PythonLockfileRequest:
    return PythonLockfileRequest.from_tool(docformatter)


def rules():
    return (*collect_rules(), UnionRule(PythonToolLockfileSentinel, DocformatterLockfileSentinel))
