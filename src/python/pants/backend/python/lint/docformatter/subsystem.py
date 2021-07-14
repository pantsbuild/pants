# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple, cast

from pants.backend.experimental.python.lockfile import (
    PythonToolLockfileRequest,
    PythonToolLockfileSentinel,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.custom_types import shell_str


class Docformatter(PythonToolBase):
    options_scope = "docformatter"
    help = "The Python docformatter tool (https://github.com/myint/docformatter)."

    default_version = "docformatter>=1.4,<1.5"
    default_main = ConsoleScript("docformatter")
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]

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
        register(
            "--experimental-lockfile",
            type=str,
            default="<none>",
            advanced=True,
            help=(
                "Path to a lockfile used for installing the tool.\n\n"
                "Set to the string '<default>' to use a lockfile provided by "
                "Pants, so long as you have not changed the `--version`, `--extra-requirements`, "
                "and `--interpreter-constraints` options. See {} for the default lockfile "
                "contents.\n\n"
                "Set to the string '<none>' to opt out of using a lockfile. We do not recommend "
                "this, as lockfiles are essential for reproducible builds.\n\n"
                "To use a custom lockfile, set this option to a file path relative to the build "
                "root, then activate the backend_package `pants.backend.experimental.python` and "
                "run `./pants tool-lock`.\n\n"
                "This option is experimental and will likely change. It does not follow the normal "
                "deprecation cycle."
            ),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> Tuple[str, ...]:
        return tuple(self.options.args)

    @property
    def lockfile(self) -> str:
        return cast(str, self.options.experimental_lockfile)


class DocformatterLockfileSentinel(PythonToolLockfileSentinel):
    pass


@rule
def setup_lockfile_request(
    _: DocformatterLockfileSentinel, docformatter: Docformatter
) -> PythonToolLockfileRequest:
    return PythonToolLockfileRequest(
        tool_name=docformatter.options_scope,
        lockfile_path=docformatter.lockfile,
        requirements=docformatter.all_requirements,
        interpreter_constraints=docformatter.interpreter_constraints,
    )


def rules():
    return (*collect_rules(), UnionRule(PythonToolLockfileSentinel, DocformatterLockfileSentinel))
